import torch
import numpy as np
from PIL import Image
from sam3.model_builder import build_sam3_video_model
from sam3.model.data_misc import FindStage, convert_my_tensors
from sam3.model.utils.misc import copy_data_to_device
import gc

class Sam3OnlineTracker:
    def __init__(self, checkpoint_path=None, device="cuda", max_frames=15): # ★15フレーム(0.5秒)に制限
        print("Sam3OnlineTracker: Initializing...", flush=True)
        self.device = device
        
        # 徹底的なメモリ掃除
        gc.collect()
        torch.cuda.empty_cache()

        # FP32 (OOM回避のためフレーム数を削る方針)
        self.dtype = torch.float32
        
        print(f"Sam3OnlineTracker: Building model on {device} (FP32, Default Size)...", flush=True)
        
        self.model = build_sam3_video_model(
            checkpoint_path=checkpoint_path,
            device=device,
            apply_temporal_disambiguation=True,
        )
        
        # ★重要: 解像度変更は削除 (AssertionError回避)
        # self.model.image_size = 512  <-- DELETE
        
        self.model.to(device)
        self.model.eval()
        
        self.inference_state = None
        self.max_frames = max_frames
        self.lost_count = 0 
        print(f"Sam3OnlineTracker: Model built. Memory limit: {self.max_frames} frames.", flush=True)

    def reset_state(self):
        if self.inference_state is not None:
            del self.inference_state
            self.inference_state = None
            self.lost_count = 0
            gc.collect()
            torch.cuda.empty_cache()

    @torch.inference_mode()
    def init_track(self, image_np, text_prompt=None, mask_prompt=None):
        # Autocast有効化
        with torch.autocast(device_type=self.device, dtype=torch.float16):
            self.reset_state()
            
            img_pil = Image.fromarray(image_np)
            
            self.inference_state = self.model.init_state(
                resource_path=[img_pil],
                video_loader_type="cv2",
            )
            
            if mask_prompt is not None:
                mask_tensor = torch.tensor(mask_prompt, dtype=torch.bool, device=self.device)
                if mask_tensor.ndim == 2:
                    mask_tensor = mask_tensor.unsqueeze(0)
                
                self.model.add_prompt(
                    self.inference_state,
                    frame_idx=0,
                    obj_id=0,
                    masks=mask_tensor
                )
            elif text_prompt is not None:
                self.model.add_prompt(
                    self.inference_state,
                    frame_idx=0,
                    obj_id=0,
                    text_str=text_prompt
                )
            
            masks = self._run_propagate(start_idx=0)
            return masks

    @torch.inference_mode()
    def step(self, image_np):
        if self.inference_state is None:
            return None
        
        with torch.autocast(device_type=self.device, dtype=torch.float16):
            # ロスト判定 (10フレームまで許容)
            if self.lost_count > 10: 
                print("[Tracker] Object lost for too long. Resetting memory.", flush=True)
                self.reset_state()
                return None

            current_num_frames = self.inference_state["num_frames"]
            
            # メモリ上限管理
            if current_num_frames >= self.max_frames:
                last_mask = self._get_mask(current_num_frames - 1)
                
                if last_mask and len(last_mask) > 0:
                    # メモリ掃除を行ってからハンドオーバー
                    gc.collect() 
                    return self.init_track(image_np, mask_prompt=last_mask[0])
                else:
                    print("[Memory] Limit reached & Object Lost. Resetting.", flush=True)
                    self.reset_state()
                    return None

            img_pil = Image.fromarray(image_np)
            new_frame_tensor, _, _ = self._process_image(img_pil)
            new_frame_tensor = new_frame_tensor.to(self.device)
            
            self._append_frame_to_state(new_frame_tensor)
            
            frame_idx = self.inference_state["num_frames"] - 1
            
            masks = self._run_propagate(start_idx=frame_idx)
            
            if masks and len(masks) > 0:
                self.lost_count = 0
            else:
                self.lost_count += 1
            
            return masks

    def _run_propagate(self, start_idx):
        for _ in self.model.propagate_in_video(
            self.inference_state,
            start_frame_idx=start_idx,
            max_frame_num_to_track=1,
            reverse=False
        ):
            pass
        return self._get_mask(start_idx)

    def _process_image(self, img_pil):
        image_size = self.model.image_size # デフォルト(1024)を使用
        img_mean = torch.tensor(self.model.image_mean, dtype=torch.float32)[:, None, None]
        img_std = torch.tensor(self.model.image_std, dtype=torch.float32)[:, None, None]
        
        img_np = np.array(img_pil.convert("RGB").resize((image_size, image_size)))
        img_np = img_np / 255.0
        img = torch.as_tensor(img_np).permute(2, 0, 1)
        
        img = img.to(dtype=torch.float32)
        img -= img_mean
        img /= img_std
        return img.unsqueeze(0), img_pil.height, img_pil.width

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
            input_boxes=[torch.zeros(input_box_embedding_dim)],
            input_boxes_mask=[torch.empty(0, dtype=torch.bool)],
            input_boxes_label=[torch.empty(0, dtype=torch.long)],
            input_points=[torch.empty(0, input_points_embedding_dim)],
            input_points_mask=[torch.empty(0)],
            object_ids=[],
        )
        new_stage = convert_my_tensors(new_stage)
        new_stage = copy_data_to_device(new_stage, device)
        
        input_batch.find_inputs.append(new_stage)
        input_batch.find_targets.append(None)
        input_batch.find_metadatas.append(None)

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
                    masks.append(mask_np)
        
        return masks