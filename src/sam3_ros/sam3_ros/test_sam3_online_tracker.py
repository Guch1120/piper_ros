import torch
import numpy as np
import cv2
from PIL import Image
from sam3.model_builder import build_sam3_video_model
from sam3.model.data_misc import FindStage, convert_my_tensors
from sam3.model.utils.misc import copy_data_to_device
# import gc # Removed for performance

class Sam3OnlineTracker:
    def __init__(self, checkpoint_path=None, device="cuda", max_frames=10, processing_size=512):
        print("Sam3OnlineTracker: Initializing...", flush=True)
        self.device = device
        
        # Determine best dtype
        if torch.cuda.is_available() and torch.cuda.is_bf16_supported():
            self.dtype = torch.bfloat16
            print("Sam3OnlineTracker: Using bfloat16 for best performance.")
        else:
            self.dtype = torch.float16
            print("Sam3OnlineTracker: Using float16.")

        # Performance tuning: Image resolution
        # Setting this lower (e.g. 512, 640) significantly speeds up the image encoder
        self.processing_size = processing_size
        
        print(f"Sam3OnlineTracker: Building model on {device} (Resolution: {processing_size}x{processing_size})...", flush=True)
        
        self.model = build_sam3_video_model(
            checkpoint_path=checkpoint_path,
            device=device,
            apply_temporal_disambiguation=True,
        )
        
        self.model.to(device)
        self.model.eval()
        
        # Initialize variables
        self.inference_state = None
        self.max_frames = max_frames
        self.lost_count = 0
        self.current_text_prompt = None
        self.original_wh = (1024, 1024) # Default placeholder
        
        print(f"Sam3OnlineTracker: Ready. Max Memory: {self.max_frames} frames.", flush=True)

    def reset_state(self):
        """Reset state and clear memory efficienty"""
        if self.inference_state is not None:
            # We don't call gc.collect() every time to avoid stuttering
            # Just clearing the reference is usually enough for PyTorch allocator
            del self.inference_state
            self.inference_state = None
            self.lost_count = 0
            # torch.cuda.empty_cache() # Avoid synchronous GPU calls

    @torch.inference_mode()
    def init_track(self, image_np, text_prompt=None, mask_prompt=None):
        """Initialize tracking with Autocast"""
        with torch.autocast(device_type=self.device, dtype=self.dtype):
            self.reset_state()

            # Store original size for mask rescaling
            h, w = image_np.shape[:2]
            self.original_wh = (w, h)
            
            # Save prompt for auto-recovery
            if text_prompt is not None:
                self.current_text_prompt = text_prompt

            # Resize input for model initialization
            img_pil = Image.fromarray(image_np)
            img_pil_resized = img_pil.resize((self.processing_size, self.processing_size), Image.BILINEAR)
            
            self.inference_state = self.model.init_state(
                resource_path=[img_pil_resized],
                video_loader_type="cv2",
            )
            
            if mask_prompt is not None:
                # Resize mask prompt if necessary? 
                # If mask prompt comes from original image, it needs to be resized to processing_size
                # Assuming mask_prompt is boolean mask of original size
                if mask_prompt.shape[-2:] != (self.processing_size, self.processing_size):
                     # Resize mask prompt
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
            
            # If initialization failed
            if not masks or len(masks) == 0:
                self.reset_state()
                return None
                
            return masks

    @torch.inference_mode()
    def step(self, image_np):
        """Per-frame processing"""
        # Auto-recovery if not initialized
        if self.inference_state is None:
            if self.current_text_prompt is not None:
                return self.init_track(image_np)
            else:
                return None
        
        with torch.autocast(device_type=self.device, dtype=self.dtype):
            # Update original size
            h, w = image_np.shape[:2]
            self.original_wh = (w, h)

            # 1. Lost check
            if self.lost_count > 10: # Increased tolerance as we want robustness
                self.reset_state()
                return self.init_track(image_np) 

            current_num_frames = self.inference_state["num_frames"]
            
            # 2. Memory limits
            if current_num_frames >= self.max_frames:
                # FIFO Strategy: Keep the initial frame and recent frames?
                # SAM 2 API handles rolling buffer usually, but here we do manual reset?
                # For continuous tracking, it's better to keep the last mask and restart.
                
                # Careful: The mask returned by _get_mask is RESIZED (Original).
                # We need the processing-size mask for restart to avoid double resizing errors?
                # Actually init_track helps resizing mask. So it is fine.
                
                last_mask = self._get_mask(current_num_frames - 1)
                
                if last_mask and len(last_mask) > 0:
                    # Restart with the last known mask to clear extensive history
                    return self.init_track(image_np, mask_prompt=last_mask[0])
                else:
                    self.reset_state()
                    return self.init_track(image_np)

            # 3. Image Processing
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
        # Use the configured processing size
        target_size = self.processing_size
        
        # Standardize normalization for SAM
        img_mean = torch.tensor(self.model.image_mean, device=self.device, dtype=torch.float32)[:, None, None]
        img_std = torch.tensor(self.model.image_std, device=self.device, dtype=torch.float32)[:, None, None]
        
        # Resize logic
        img_np = np.array(img_pil.convert("RGB").resize((target_size, target_size)))
        img_np = img_np / 255.0
        img = torch.as_tensor(img_np).permute(2, 0, 1)
        
        img = img.to(device=self.device, dtype=torch.float32)
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
                    # Handle multiple mask dimensions
                    if mask_np.ndim == 3:
                        mask_np = mask_np[0]
                    
                    # Resize mask back to original resolution
                    target_w, target_h = self.original_wh
                    if mask_np.shape[0] != target_h or mask_np.shape[1] != target_w:
                         mask_np = cv2.resize(mask_np, (target_w, target_h), interpolation=cv2.INTER_NEAREST)

                    masks.append(mask_np)
        
        return masks