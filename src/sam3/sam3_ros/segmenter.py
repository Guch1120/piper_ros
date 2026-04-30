"""SAM3 inference helper used by both ROS1 and ROS2 nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
import time

import numpy as np
from PIL import Image

import torch

from sam3.model.sam3_image_processor import Sam3Processor
from sam3.model_builder import build_sam3_image_model

from .config import Sam3ModelConfig


@dataclass(slots=True)
class SegmentationResult:
    """Normalized inference output."""

    masks: list[np.ndarray]
    boxes: list[tuple[float, float, float, float]]
    scores: list[float]
    annotated_bgr: np.ndarray | None
    timings: dict[str, float] = field(default_factory=dict)


def _normalize_mask_array(mask: object) -> np.ndarray | None:
    array = np.asarray(mask)
    array = np.squeeze(array)
    if array.ndim != 2:
        return None
    return array.astype(bool)


def _to_numpy_masks(masks: object) -> list[np.ndarray]:
    if masks is None:
        return []
    if torch.is_tensor(masks):
        masks = masks.detach().cpu().numpy()
    if isinstance(masks, np.ndarray):
        if masks.ndim == 2:
            normalized = _normalize_mask_array(masks)
            return [] if normalized is None else [normalized]
        normalized_masks = []
        for mask in masks:
            normalized = _normalize_mask_array(mask)
            if normalized is not None:
                normalized_masks.append(normalized)
        return normalized_masks
    if isinstance(masks, (list, tuple)):
        normalized_masks = []
        for mask in masks:
            normalized = _normalize_mask_array(mask)
            if normalized is not None:
                normalized_masks.append(normalized)
        return normalized_masks
    normalized = _normalize_mask_array(masks)
    return [] if normalized is None else [normalized]


def _to_box_list(boxes: object) -> list[tuple[float, float, float, float]]:
    if boxes is None:
        return []
    if torch.is_tensor(boxes):
        boxes = boxes.detach().cpu().numpy()
    array = np.asarray(boxes)
    array = np.squeeze(array)
    if array.size == 0:
        return []
    if array.ndim == 1:
        if array.shape[0] != 4:
            return []
        array = array.reshape(1, 4)
    if array.ndim != 2 or array.shape[1] != 4:
        return []
    return [tuple(float(v) for v in row) for row in array]


def _to_score_list(scores: object) -> list[float]:
    if scores is None:
        return []
    if torch.is_tensor(scores):
        scores = scores.detach().to(dtype=torch.float32).cpu().numpy()
    array = np.asarray(scores, dtype=np.float32)
    array = np.squeeze(array)
    if array.size == 0:
        return []
    if array.ndim == 0:
        return [float(array)]
    return [float(v) for v in array.reshape(-1)]


def _draw_box(image: np.ndarray, box: Sequence[float], color: tuple[int, int, int]) -> None:
    height, width = image.shape[:2]
    x1 = max(0, min(width - 1, int(round(box[0]))))
    y1 = max(0, min(height - 1, int(round(box[1]))))
    x2 = max(0, min(width - 1, int(round(box[2]))))
    y2 = max(0, min(height - 1, int(round(box[3]))))
    if x2 <= x1 or y2 <= y1:
        return
    thickness = max(1, min(height, width) // 300)
    image[y1 : min(y1 + thickness, y2 + 1), x1 : x2 + 1] = color
    image[max(y2 - thickness + 1, y1) : y2 + 1, x1 : x2 + 1] = color
    image[y1 : y2 + 1, x1 : min(x1 + thickness, x2 + 1)] = color
    image[y1 : y2 + 1, max(x2 - thickness + 1, x1) : x2 + 1] = color


def _color_for_index(index: int) -> tuple[int, int, int]:
    palette = (
        (54, 162, 235),
        (255, 99, 132),
        (75, 192, 192),
        (255, 206, 86),
        (153, 102, 255),
        (255, 159, 64),
    )
    return palette[index % len(palette)]


def _render_overlay(
    image_bgr: np.ndarray,
    masks: Sequence[np.ndarray],
    boxes: Sequence[Sequence[float]],
) -> np.ndarray:
    overlay = image_bgr.copy()
    alpha = 0.35
    for index, mask in enumerate(masks):
        color = np.asarray(_color_for_index(index), dtype=np.float32)
        binary_mask = mask.astype(bool)
        if binary_mask.ndim != 2 or not binary_mask.any():
            continue
        overlay[binary_mask] = (
            (1.0 - alpha) * overlay[binary_mask].astype(np.float32) + alpha * color
        ).astype(np.uint8)
    for index, box in enumerate(boxes):
        _draw_box(overlay, box, _color_for_index(index))
    return overlay


class Sam3ImageSegmenter:
    """Small convenience wrapper around the SAM3 image predictor."""

    def __init__(self, config: Sam3ModelConfig) -> None:
        self._config = config
        device = config.device
        if device == "cuda" and not torch.cuda.is_available():
            device = "cpu"
        self._device = device
        self._model = build_sam3_image_model(
            bpe_path=None,
            device=device,
            eval_mode=True,
            checkpoint_path=config.checkpoint_path,
            load_from_HF=config.load_from_hf,
            enable_segmentation=config.enable_segmentation,
            enable_inst_interactivity=config.enable_inst_interactivity,
            compile=config.compile,
        )
        if config.query_limit > 0:
            self._model.transformer.decoder.inference_num_queries = config.query_limit
        if config.decoder_layers > 0:
            self._model.transformer.decoder.inference_num_layers = config.decoder_layers
        self._processor = Sam3Processor(
            self._model,
            resolution=config.resolution,
            device=device,
            use_autocast=config.use_autocast,
            use_channels_last=config.use_channels_last,
            cache_text_features=config.cache_text_features,
            image_encoder_onnx_path=config.image_encoder_onnx_path,
            onnx_provider=config.onnx_provider,
            onnx_trt_fp16=config.onnx_trt_fp16,
        )
        self._processor.set_profile_enabled(True)

    @property
    def default_prompt(self) -> str:
        return self._config.text_prompt

    @property
    def device(self) -> str:
        return self._device

    @property
    def autocast_dtype_name(self) -> str:
        return str(self._processor.autocast_dtype).replace("torch.", "")

    @property
    def channels_last_enabled(self) -> bool:
        return self._processor.use_channels_last

    @property
    def image_encoder_backend(self) -> str:
        if self._processor.image_encoder_session is None:
            return "pytorch"
        providers = ",".join(self._processor.image_encoder_session_providers)
        return f"onnx:{providers}"

    def segment(
        self,
        image_bgr: np.ndarray,
        prompt: str | None = None,
        render_annotated: bool = True,
    ) -> SegmentationResult:
        if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
            raise ValueError("Expected a BGR image with shape (H, W, 3)")
        prompt_text = prompt if prompt is not None else self._config.text_prompt
        image_rgb = image_bgr[:, :, ::-1]
        pil_image = Image.fromarray(image_rgb)
        timings: dict[str, float] = {}
        with torch.inference_mode():
            self._processor.reset_profile_timings()
            start = time.perf_counter()
            state = self._processor.set_image(pil_image)
            timings["set_image_total"] = time.perf_counter() - start
            start = time.perf_counter()
            output = self._processor.set_text_prompt(prompt_text, state)
            timings["set_text_prompt_total"] = time.perf_counter() - start
        timings.update(self._processor.get_profile_timings())
        start = time.perf_counter()
        masks = _to_numpy_masks(output.get("masks"))
        timings["normalize_masks"] = time.perf_counter() - start
        start = time.perf_counter()
        boxes = _to_box_list(output.get("boxes"))
        timings["normalize_boxes"] = time.perf_counter() - start
        start = time.perf_counter()
        scores = _to_score_list(output.get("scores"))
        timings["normalize_scores"] = time.perf_counter() - start
        start = time.perf_counter()
        annotated = _render_overlay(image_bgr, masks, boxes) if render_annotated else None
        timings["render_overlay"] = time.perf_counter() - start
        return SegmentationResult(
            masks=masks,
            boxes=boxes,
            scores=scores,
            annotated_bgr=annotated,
            timings=timings,
        )
