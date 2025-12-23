from sam3.model_builder import build_sam3_video_model
from sam3.model.sam3_video_base import Sam3VideoBase
from sam3.model.data_misc import BatchedDatapoint
from typing import Any, Dict
import torch
import sys

# Monkey patch
def patched_run_backbone_and_detection(
    self,
    frame_idx: int,
    num_frames: int,
    input_batch: BatchedDatapoint,
    geometric_prompt: Any,
    feature_cache: Dict,
    reverse: bool,
    allow_new_detections: bool,
):
    print("Executing patched run_backbone_and_detection", flush=True)
    # Step 1: if text feature is not cached in `feature_cache`, compute and cache it
    text_batch_key = tuple(input_batch.find_text_batch)
    if "text" not in feature_cache or text_batch_key not in feature_cache["text"]:
        text_outputs = self.detector.backbone.forward_text(
            input_batch.find_text_batch, device=self.device
        )
        # note: we only cache the text feature of the most recent prompt
        feature_cache["text"] = {text_batch_key: text_outputs}
    else:
        text_outputs = feature_cache["text"][text_batch_key]

    # Step 2: run backbone, detector, and post-processing with NMS
    if "multigpu_buffer" not in feature_cache:
        # "multigpu_buffer" is a buffer cache used by `self.detector` and it needs
        # to be passed to `forward_video_grounding_multigpu` for every call
        feature_cache["multigpu_buffer"] = {}

    # Extract max_frame_num_to_track from feature_cache if available
    tracking_bounds = feature_cache.get("tracking_bounds", {})
    max_frame_num_to_track = tracking_bounds.get("max_frame_num_to_track")
    start_frame_idx = tracking_bounds.get("propagate_in_video_start_frame_idx")

    sam3_image_out, _ = self.detector.forward_video_grounding_multigpu(
        backbone_out={
            "img_batch_all_stages": input_batch.img_batch,
            **text_outputs,
        },
        find_inputs=input_batch.find_inputs,
        geometric_prompt=geometric_prompt,
        frame_idx=frame_idx,
        num_frames=num_frames,
        multigpu_buffer=feature_cache["multigpu_buffer"],
        track_in_reverse=reverse,
        # also get the SAM2 backbone features
        return_tracker_backbone_feats=True,
        # run NMS as a part of distributed computation
        run_nms=self.det_nms_thresh > 0.0,
        nms_prob_thresh=self.score_threshold_detection,
        nms_iou_thresh=self.det_nms_thresh,
        # pass max_frame_num_to_track to respect tracking limits
        max_frame_num_to_track=max_frame_num_to_track,
        propagate_in_video_start_frame_idx=start_frame_idx,
    )
    # note: detections in `sam3_image_out` has already gone through NMS
    pred_probs = sam3_image_out["pred_logits"].squeeze(-1).sigmoid()
    if not allow_new_detections:
        pred_probs = pred_probs - 1e8  # make sure no detections are kept
    pred_boxes_xyxy = sam3_image_out["pred_boxes_xyxy"]
    pred_masks = sam3_image_out["pred_masks"]
    # get the positive detection outputs above threshold
    pos_pred_idx = torch.where(pred_probs > self.score_threshold_detection)
    det_out = {
        "bbox": pred_boxes_xyxy[pos_pred_idx[0], pos_pred_idx[1]],
        "mask": pred_masks[pos_pred_idx[0], pos_pred_idx[1]],
        "scores": pred_probs[pos_pred_idx[0], pos_pred_idx[1]],
    }

    # Step 3: build SAM2 backbone features and store them in `feature_cache`
    backbone_cache = {}
    sam_mask_decoder = self.tracker.sam_mask_decoder
    
    fpn0 = sam3_image_out["tracker_backbone_fpn_0"]
    fpn1 = sam3_image_out["tracker_backbone_fpn_1"]
    fpn2 = sam3_image_out["tracker_backbone_fpn_2"]
    if self.device.type == "cpu":
        fpn0 = fpn0.float()
        fpn1 = fpn1.float()
        fpn2 = fpn2.float()

    tracker_backbone_fpn = [
        sam_mask_decoder.conv_s0(fpn0),
        sam_mask_decoder.conv_s1(fpn1),
        fpn2,  # fpn_2 doesn't need conv
    ]
    tracker_backbone_out = {
        "vision_features": tracker_backbone_fpn[-1],  # top-level feature
        "vision_pos_enc": sam3_image_out["tracker_backbone_pos_enc"],
        "backbone_fpn": tracker_backbone_fpn,
    }
    backbone_cache["tracker_backbone_out"] = tracker_backbone_out
    feature_cache[frame_idx] = (
        input_batch.img_batch[frame_idx],
        backbone_cache,
    )
    # remove from `feature_cache` old features to save GPU memory
    feature_cache.pop(frame_idx - 1 if not reverse else frame_idx + 1, None)
    return det_out

Sam3VideoBase.run_backbone_and_detection = patched_run_backbone_and_detection

def main():
    print("Building model...", flush=True)
    checkpoint_path = "/home/guch1/.cache/huggingface/hub/models--facebook--sam3/snapshots/3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt"
    try:
        model = build_sam3_video_model(checkpoint_path=checkpoint_path, device='cpu')
        print("Model built.", flush=True)
    except Exception as e:
        print(f"Failed: {e}", flush=True)

if __name__ == "__main__":
    main()
