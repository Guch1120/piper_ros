import torch
import numpy as np
from PIL import Image
from sam3.model_builder import build_sam3_video_model
from sam3.model.data_misc import BatchedDatapoint, FindStage, convert_my_tensors
from sam3.model.utils.misc import copy_data_to_device

class Sam3OnlineTracker:
    def __init__(self, checkpoint_path=None, device="cuda"):
        print("Sam3OnlineTracker: Initializing...", flush=True)
        self.device = device
        print(f"Sam3OnlineTracker: Building model on {device}...", flush=True)
        self.model = build_sam3_video_model(
            checkpoint_path=checkpoint_path,
            device=device,
            apply_temporal_disambiguation=True,
        )
        if device == "cpu":
            self.model.float()

        print("Sam3OnlineTracker: Model built.", flush=True)
        self.inference_state = None

    def init_track(self, image_np, text_prompt):
        """
        Initialize tracking with the first frame and a text prompt.
        image_np: HxWx3, RGB, 0-255, numpy array
        text_prompt: str
        """
        img_pil = Image.fromarray(image_np)
        
        # Initialize state with one frame
        # We pass a list of PIL images to init_state
        self.inference_state = self.model.init_state(
            resource_path=[img_pil],
            video_loader_type="cv2", # ignored for list input
        )
        
        # Add text prompt to the first frame
        print("Sam3OnlineTracker.init_track: init_state done", flush=True)
        
        self.model.add_prompt(
            self.inference_state,
            frame_idx=0,
            text_str=text_prompt
        )
        print("Sam3OnlineTracker.init_track: add_prompt done", flush=True)
        
        # Propagate to get initial mask
        for _ in self.model.propagate_in_video(
            self.inference_state,
            start_frame_idx=0,
            max_frame_num_to_track=1,
            reverse=False
        ):
            pass
            
        return self._get_mask(0)

    def step(self, image_np):
        """
        Process the next frame.
        image_np: HxWx3, RGB, 0-255, numpy array
        """
        if self.inference_state is None:
            raise RuntimeError("Tracker not initialized")
            
        # Prepare new frame
        img_pil = Image.fromarray(image_np)
        new_frame_tensor, _, _ = self._process_image(img_pil)
        new_frame_tensor = new_frame_tensor.to(self.device)
        
        # Update inference state
        self._append_frame_to_state(new_frame_tensor)
        
        frame_idx = self.inference_state["num_frames"] - 1
        
        # Propagate on the new frame
        for _ in self.model.propagate_in_video(
            self.inference_state,
            start_frame_idx=frame_idx,
            max_frame_num_to_track=1,
            reverse=False
        ):
            pass
            
        return self._get_mask(frame_idx)

    def _process_image(self, img_pil):
        image_size = self.model.image_size
        img_mean = torch.tensor(self.model.image_mean, dtype=torch.float16)[:, None, None]
        img_std = torch.tensor(self.model.image_std, dtype=torch.float16)[:, None, None]
        
        img_np = np.array(img_pil.convert("RGB").resize((image_size, image_size)))
        img_np = img_np / 255.0
        img = torch.as_tensor(img_np).permute(2, 0, 1)
        img = img.to(dtype=torch.float16)
        img -= img_mean
        img /= img_std
        return img.unsqueeze(0), img_pil.height, img_pil.width

    def _append_frame_to_state(self, new_frame_tensor):
        state = self.inference_state
        device = self.device
        
        # 1. Update input_batch
        input_batch = state["input_batch"]
        
        # Append new frame to img_batch
        # img_batch is (N, 3, H, W)
        input_batch.img_batch = torch.cat([input_batch.img_batch, new_frame_tensor], dim=0)
        
        # Update num_frames
        state["num_frames"] += 1
        
        # 2. Add new FindStage
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
        # Move to device
        new_stage = copy_data_to_device(new_stage, device)
        
        input_batch.find_inputs.append(new_stage)
        input_batch.find_targets.append(None)
        input_batch.find_metadatas.append(None)

    def _get_mask(self, frame_idx):
        # Extract mask from cached outputs
        cached_outputs = self.inference_state["cached_frame_outputs"].get(frame_idx)
        if cached_outputs is None:
            return None
            
        # cached_outputs is obj_id_to_mask
        masks = []
        # Sort by obj_id to ensure consistent order
        for obj_id in sorted(cached_outputs.keys()):
            mask = cached_outputs[obj_id]
            # mask is boolean tensor, convert to uint8 0-255 for ROS
            mask_np = (mask.cpu().numpy().astype(np.uint8) * 255)
            # mask shape is 1xHxW, remove channel dim
            if mask_np.ndim == 3:
                mask_np = mask_np[0]
            masks.append(mask_np)
        
        if not masks:
            return None
            
        return masks # List of HxW numpy arrays
