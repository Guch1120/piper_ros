# test_sam3_online_tracker.py

import torch
import numpy as np
import cv2
from PIL import Image
from sam3.model_builder import build_sam3_video_model
from sam3.model.data_misc import FindStage, convert_my_tensors
from sam3.model.utils.misc import copy_data_to_device

class Sam3OnlineTracker:
    def __init__(self, checkpoint_path=None, device="cuda", max_frames=10, processing_size=384):
        print("Sam3OnlineTracker: Initializing...", flush=True)
        self.device = device
        
        # Use float16 for better compatibility with RTX 20 series (Turing) and torch.compile
        # Bfloat16 support on 20 series is limited and causes compilation skip/warnings
        self.dtype = torch.float16
        print("Sam3OnlineTracker: Using float16 weights (Forced for RTX 2070 compatibility).")
        
        self.processing_size = processing_size
        
        print(f"Sam3OnlineTracker: Building model on {device} (Resolution: {processing_size}x{processing_size})...", flush=True)
        
        self.model = build_sam3_video_model(
            checkpoint_path=checkpoint_path,
            device=device,
            apply_temporal_disambiguation=True,
            compile=True, # [Optimization] Enable compilation for speed
        )
        # [Fix] Overwrite default image_size (1008) with processing_size (384)
        self.model.image_size = self.processing_size
        if hasattr(self.model, "tracker"):
             self.model.tracker.image_size = self.processing_size
        
        # [Tuning] Adjust tracking parameters for low-res / robust tracking
        # Lower threshold to detect objects more easily
        self.model.score_threshold_detection = 0.35
        # Reduce coasting persistence (don't keep 'Lost' tracks for too long)
        self.model.max_trk_keep_alive = 8
        # Update memory more frequently
        self.model.recondition_every_nth_frame = 8
        
        # Cast model to the selected dtype to save VRAM
        self.model.to(device, dtype=self.dtype)
        self.model.eval()
        
        # 掃除
        torch.cuda.empty_cache()
        
        self.inference_state = None
        self.max_frames = max_frames
        self.lost_count = 0
        self.current_text_prompt = None
        self.original_wh = (1024, 1024)
        
        # Mean/Std
        self.img_mean = torch.tensor(self.model.image_mean, device=device, dtype=self.dtype).view(-1, 1, 1)
        self.img_std = torch.tensor(self.model.image_std, device=device, dtype=self.dtype).view(-1, 1, 1)
        
        print(f"Sam3OnlineTracker: Ready. Max Memory: {self.max_frames} frames.", flush=True)

    def reset_state(self):
        if self.inference_state is not None:
            del self.inference_state
            self.inference_state = None
            self.lost_count = 0
            torch.cuda.empty_cache()

    @torch.inference_mode()
    def init_track(self, image_np, text_prompt=None, mask_prompt=None):
        # 【修正3】Autocastを復活させる（これが計算メモリをFP16並に下げる）
        # bfloat16が使えるならbf16、そうでなければfloat16
        # Use the same dtype for autocast
        cast_dtype = self.dtype
        
        with torch.autocast(device_type=self.device, dtype=cast_dtype):
            self.reset_state()
            h, w = image_np.shape[:2]
            self.original_wh = (w, h)
            
            if text_prompt is not None:
                self.current_text_prompt = text_prompt

            img_pil = Image.fromarray(image_np)
            img_pil_resized = img_pil.resize((self.processing_size, self.processing_size), Image.BILINEAR)
            
            self.inference_state = self.model.init_state(
                resource_path=[img_pil_resized],
                video_loader_type="cv2",
            )
            
            # Cast all floating point tensors in the state to self.dtype (bf16/fp16)
            self._cast_inference_state(self.inference_state)
            
            # Explicitly verify/cast img_batch to be safe
            if "input_batch" in self.inference_state:
                ib = self.inference_state["input_batch"]
                if hasattr(ib, "img_batch") and isinstance(ib.img_batch, torch.Tensor):
                    if ib.img_batch.dtype != self.dtype:
                        print(f"Warning: img_batch was {ib.img_batch.dtype}, casting to {self.dtype}")
                        ib.img_batch = ib.img_batch.to(dtype=self.dtype)
            
            # Verify constants
            if "constants" in self.inference_state:
                consts = self.inference_state["constants"]
                if "empty_geometric_prompt" in consts:
                     # Force recursion on this object explicitly if needed
                     self._cast_recursive_in_place(consts["empty_geometric_prompt"])

            if mask_prompt is not None:
                if mask_prompt.shape[-2:] != (self.processing_size, self.processing_size):
                     mask_pil = Image.fromarray(mask_prompt.astype(np.uint8))
                     mask_pil = mask_pil.resize((self.processing_size, self.processing_size), Image.NEAREST)
                     mask_prompt = np.array(mask_pil).astype(bool)

                mask_tensor = torch.tensor(mask_prompt, dtype=torch.bool, device=self.device)
                if mask_tensor.ndim == 2:
                    mask_tensor = mask_tensor.unsqueeze(0)
                
                self.model.add_prompt(
                    self.inference_state,
                    frame_idx=0,
                    obj_id=0,
                    masks=mask_tensor
                )
            elif self.current_text_prompt is not None:
                self.model.add_prompt(
                    self.inference_state,
                    frame_idx=0,
                    obj_id=0,
                    text_str=self.current_text_prompt
                )
            
            masks = self._run_propagate(start_idx=0)
            
            if not masks or len(masks) == 0:
                self.reset_state()
                return None
            return masks

    @torch.inference_mode()
    def step(self, image_np):
        if self.inference_state is None:
            if self.current_text_prompt is not None:
                return self.init_track(image_np)
            else:
                return None
        
        # 【修正3】Autocast復活
        cast_dtype = self.dtype
        with torch.autocast(device_type=self.device, dtype=cast_dtype):
            h, w = image_np.shape[:2]
            self.original_wh = (w, h)

            if self.lost_count > 10:
                self.reset_state()
                return self.init_track(image_np) 

            current_num_frames = self.inference_state["num_frames"]
            
            if current_num_frames >= self.max_frames:
                last_mask = self._get_mask(current_num_frames - 1)
                if last_mask and len(last_mask) > 0:
                    return self.init_track(image_np, mask_prompt=last_mask[0])
                else:
                    self.reset_state()
                    return self.init_track(image_np)

            img_pil = Image.fromarray(image_np)
            new_frame_tensor, _, _ = self._process_image(img_pil)
            
            new_frame_tensor = new_frame_tensor.to(self.device) 
            
            self._append_frame_to_state(new_frame_tensor)
            
            # Ensure the newly expanded batch allows gradients if needed (though we use inference_mode)
            # and verify dtype of the appended state parts if possible.
            # (The _append_frame_to_state method is updated below to use self.dtype)
            
            frame_idx = self.inference_state["num_frames"] - 1
            masks = self._run_propagate(start_idx=frame_idx)
            
            if masks and len(masks) > 0:
                self.lost_count = 0
            else:
                self.lost_count += 1
            
            return masks
            
    # _process_image の修正（dtype=self.dtype が float32 になるのでOK）
    def _process_image(self, img_pil):
        target_size = self.processing_size
        img_np = np.array(img_pil.convert("RGB").resize((target_size, target_size)))
        img_np = img_np / 255.0
        img = torch.as_tensor(img_np).permute(2, 0, 1)
        img = img.to(device=self.device, dtype=self.dtype) # self.dtype is float32
        img -= self.img_mean
        img /= self.img_std
        return img.unsqueeze(0), img_pil.height, img_pil.width

    # _run_propagate, _append_frame_to_state, _get_mask は変更なし
    def _run_propagate(self, start_idx):
        for _ in self.model.propagate_in_video(
            self.inference_state,
            start_frame_idx=start_idx,
            max_frame_num_to_track=1,
            reverse=False
        ):
            pass
        return self._get_mask(start_idx)

    def _append_frame_to_state(self, new_frame_tensor):
        state = self.inference_state
        device = self.device
        input_batch = state["input_batch"]
        input_batch.img_batch = torch.cat([input_batch.img_batch, new_frame_tensor], dim=0)
        state["num_frames"] += 1
        input_box_embedding_dim = 258
        input_points_embedding_dim = 257
        new_stage = FindStage(
            img_ids=[state["num_frames"] - 1],
            text_ids=[0],
            input_boxes=[torch.zeros(input_box_embedding_dim, device=device, dtype=self.dtype)],
            input_boxes_mask=[torch.empty(0, dtype=torch.bool, device=device)],
            input_boxes_label=[torch.empty(0, dtype=torch.long, device=device)],
            input_points=[torch.empty(0, input_points_embedding_dim, device=device, dtype=self.dtype)],
            input_points_mask=[torch.empty(0, device=device)],
            object_ids=[],
        )
        new_stage = convert_my_tensors(new_stage)
        new_stage = copy_data_to_device(new_stage, device)
        input_batch.find_inputs.append(new_stage)
        input_batch.find_targets.append(None)
        input_batch.find_metadatas.append(None)
    
    def _cast_recursive_in_place(self, obj):
         if isinstance(obj, torch.Tensor):
             if obj.is_floating_point():
                 return obj.to(dtype=self.dtype)
             return obj
         elif isinstance(obj, dict):
             return {k: self._cast_recursive_in_place(v) for k, v in obj.items()}
         elif isinstance(obj, list):
             return [self._cast_recursive_in_place(v) for v in obj]
         elif hasattr(obj, "__dict__"):
             for k, v in obj.__dict__.items():
                 setattr(obj, k, self._cast_recursive_in_place(v))
             return obj
         return obj

    def _cast_inference_state(self, state):
        # Apply to known keys that contain tensors
        if "input_batch" in state:
            self._cast_recursive_in_place(state["input_batch"])
        if "constants" in state:
            # Update dict in place
            state["constants"] = self._cast_recursive_in_place(state["constants"])
        if "visual_prompt_embed" in state:
            state["visual_prompt_embed"] = self._cast_recursive_in_place(state["visual_prompt_embed"])

    def _get_mask(self, frame_idx):
        cached_outputs = self.inference_state["cached_frame_outputs"].get(frame_idx)
        if cached_outputs is None:
            return None
        masks = []
        for obj_id in sorted(cached_outputs.keys()):
            mask = cached_outputs[obj_id]
            if mask is not None and mask.numel() > 0:
                 if mask.sum() > 0:
                    mask_np = (mask.cpu().numpy().astype(np.uint8) * 255)
                    if mask_np.ndim == 3:
                        mask_np = mask_np[0]
                    target_w, target_h = self.original_wh
                    if mask_np.shape[0] != target_h or mask_np.shape[1] != target_w:
                         mask_np = cv2.resize(mask_np, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
                    masks.append(mask_np)
        return masks