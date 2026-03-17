# Copyright (c) Meta Platforms, Inc. and affiliates. All Rights Reserved
from contextlib import nullcontext
import time
from typing import Dict, List

import numpy as np
import PIL
import torch

from sam3.model import box_ops

from sam3.model.data_misc import FindStage, interpolate
from torchvision.transforms import v2


class Sam3Processor:
    """ """

    def __init__(
        self,
        model,
        resolution=1008,
        device="cuda",
        confidence_threshold=0.5,
        use_autocast=None,
        autocast_dtype=torch.bfloat16,
        cache_text_features=True,
        image_encoder_onnx_path=None,
        onnx_provider="tensorrt",
        onnx_trt_cache_dir="/tmp/ort_trt_cache",
        onnx_trt_fp16=True,
    ):
        self.model = model
        self.resolution = resolution
        self.device = device
        self.image_encoder_onnx_path = image_encoder_onnx_path
        self.transform = v2.Compose(
            [
                v2.ToDtype(torch.uint8, scale=True),
                v2.Resize(size=(resolution, resolution)),
                v2.ToDtype(torch.float32, scale=True),
                v2.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
            ]
        )
        self.confidence_threshold = confidence_threshold
        self.profile_enabled = False
        self.profile_timings = {}
        self.use_autocast = (device == "cuda") if use_autocast is None else use_autocast
        self.autocast_dtype = autocast_dtype
        self.cache_text_features = cache_text_features
        self.text_feature_cache = {}
        self.onnx_provider = onnx_provider
        self.onnx_trt_cache_dir = onnx_trt_cache_dir
        self.onnx_trt_fp16 = onnx_trt_fp16
        self.image_encoder_session = None
        self.image_encoder_session_providers = []
        self.image_encoder_io_binding = None
        self.image_encoder_input_name = None
        self.image_encoder_output_names = []
        self.image_encoder_output_shapes = []
        self.image_encoder_output_buffers = None
        self._init_image_encoder_backend()

        self.find_stage = FindStage(
            img_ids=torch.tensor([0], device=device, dtype=torch.long),
            text_ids=torch.tensor([0], device=device, dtype=torch.long),
            input_boxes=None,
            input_boxes_mask=None,
            input_boxes_label=None,
            input_points=None,
            input_points_mask=None,
        )

    def _init_image_encoder_backend(self):
        if not self.image_encoder_onnx_path:
            return
        try:
            import onnxruntime as ort
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "ONNX image encoder is requested but onnxruntime is not installed."
            ) from exc

        session_options = ort.SessionOptions()
        session_options.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        providers = self._build_onnx_providers()
        self.image_encoder_session = ort.InferenceSession(
            self.image_encoder_onnx_path,
            sess_options=session_options,
            providers=providers,
        )
        self.image_encoder_session_providers = (
            self.image_encoder_session.get_providers()
        )
        self.image_encoder_input_name = self.image_encoder_session.get_inputs()[0].name
        self.image_encoder_output_names = [
            output.name for output in self.image_encoder_session.get_outputs()
        ]
        self.image_encoder_output_shapes = self._infer_onnx_output_shapes()
        self.image_encoder_output_buffers = None

    def _build_onnx_providers(self):
        if self.onnx_provider == "cpu":
            return ["CPUExecutionProvider"]
        if self.onnx_provider == "cuda":
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if self.onnx_provider == "tensorrt":
            return [
                (
                    "TensorrtExecutionProvider",
                    {
                        "trt_fp16_enable": "True" if self.onnx_trt_fp16 else "False",
                        "trt_engine_cache_enable": "True",
                        "trt_engine_cache_path": self.onnx_trt_cache_dir,
                    },
                ),
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ]
        raise ValueError(f"Unsupported ONNX provider: {self.onnx_provider}")

    def _infer_onnx_output_shapes(self):
        feature_hw = self.resolution // 14
        shapes = []
        for scale in (4, 2, 1):
            size = feature_hw * scale
            shapes.append((1, 256, size, size))
        shapes.append((1, 256, feature_hw // 2, feature_hw // 2))
        return shapes

    def _ensure_onnx_output_buffers(self, image: torch.Tensor):
        if self.device != "cuda":
            self.image_encoder_output_buffers = None
            return None
        if self.image_encoder_output_buffers is not None:
            return self.image_encoder_output_buffers
        buffers = []
        for shape in self.image_encoder_output_shapes:
            buffers.append(
                torch.empty(shape, device=image.device, dtype=torch.float32)
            )
        self.image_encoder_output_buffers = buffers
        return buffers

    def _run_image_encoder_onnx(self, image: torch.Tensor):
        outputs = self.image_encoder_session.run(
            self.image_encoder_output_names,
            {self.image_encoder_input_name: image.detach().cpu().numpy()},
        )
        return [torch.as_tensor(np.asarray(output), device=self.device) for output in outputs]

    def _forward_image(self, image: torch.Tensor):
        if self.image_encoder_session is None:
            with self._autocast_context():
                return self.model.backbone.forward_image(image)

        features = self._run_image_encoder_onnx(image)
        sam3_pos = [
            self.model.backbone.vision_backbone.position_encoding(feature).to(
                feature.dtype
            )
            for feature in features
        ]
        return {
            "vision_features": features[-1],
            "vision_pos_enc": sam3_pos,
            "backbone_fpn": features,
            "sam2_backbone_out": None,
        }

    def _sync_if_needed(self):
        if self.device == "cuda":
            torch.cuda.synchronize()

    def _profile_step(self, name, func):
        if not self.profile_enabled:
            return func()
        self._sync_if_needed()
        start = time.perf_counter()
        result = func()
        self._sync_if_needed()
        self.profile_timings[name] = time.perf_counter() - start
        return result

    def _autocast_context(self):
        if self.device != "cuda" or not self.use_autocast:
            return nullcontext()
        return torch.autocast(device_type="cuda", dtype=self.autocast_dtype)

    def set_profile_enabled(self, enabled: bool):
        self.profile_enabled = enabled
        if not enabled:
            self.profile_timings = {}

    def reset_profile_timings(self):
        self.profile_timings = {}

    def get_profile_timings(self):
        return dict(self.profile_timings)

    def reset_text_cache(self):
        self.text_feature_cache = {}

    @torch.inference_mode()
    def set_image(self, image, state=None):
        """Sets the image on which we want to do predictions."""
        if state is None:
            state = {}

        if isinstance(image, PIL.Image.Image):
            width, height = image.size
        elif isinstance(image, (torch.Tensor, np.ndarray)):
            height, width = image.shape[-2:]
        else:
            raise ValueError("Image must be a PIL image or a tensor")

        image = self._profile_step(
            "set_image_to_device",
            lambda: v2.functional.to_image(image).to(self.device),
        )
        image = self._profile_step(
            "set_image_transform",
            lambda: self.transform(image).unsqueeze(0),
        )

        state["original_height"] = height
        state["original_width"] = width
        state["backbone_out"] = self._profile_step(
            "set_image_forward_image",
            lambda: self._forward_image(image),
        )
        inst_interactivity_en = self.model.inst_interactive_predictor is not None
        if inst_interactivity_en and "sam2_backbone_out" in state["backbone_out"]:
            sam2_backbone_out = state["backbone_out"]["sam2_backbone_out"]
            sam2_backbone_out["backbone_fpn"][0] = (
                self.model.inst_interactive_predictor.model.sam_mask_decoder.conv_s0(
                    sam2_backbone_out["backbone_fpn"][0]
                )
            )
            sam2_backbone_out["backbone_fpn"][1] = (
                self.model.inst_interactive_predictor.model.sam_mask_decoder.conv_s1(
                    sam2_backbone_out["backbone_fpn"][1]
                )
            )
        return state

    @torch.inference_mode()
    def set_image_batch(self, images: List[np.ndarray], state=None):
        """Sets the image batch on which we want to do predictions."""
        if state is None:
            state = {}

        if not isinstance(images, list):
            raise ValueError("Images must be a list of PIL images or tensors")
        assert len(images) > 0, "Images list must not be empty"
        assert isinstance(
            images[0], PIL.Image.Image
        ), "Images must be a list of PIL images"

        state["original_heights"] = [image.height for image in images]
        state["original_widths"] = [image.width for image in images]

        images = [
            self.transform(v2.functional.to_image(image).to(self.device))
            for image in images
        ]
        images = torch.stack(images, dim=0)
        state["backbone_out"] = self.model.backbone.forward_image(images)
        inst_interactivity_en = self.model.inst_interactive_predictor is not None
        if inst_interactivity_en and "sam2_backbone_out" in state["backbone_out"]:
            sam2_backbone_out = state["backbone_out"]["sam2_backbone_out"]
            sam2_backbone_out["backbone_fpn"][0] = (
                self.model.inst_interactive_predictor.model.sam_mask_decoder.conv_s0(
                    sam2_backbone_out["backbone_fpn"][0]
                )
            )
            sam2_backbone_out["backbone_fpn"][1] = (
                self.model.inst_interactive_predictor.model.sam_mask_decoder.conv_s1(
                    sam2_backbone_out["backbone_fpn"][1]
                )
            )
        return state

    @torch.inference_mode()
    def set_text_prompt(self, prompt: str, state: Dict):
        """Sets the text prompt and run the inference"""

        if "backbone_out" not in state:
            raise ValueError("You must call set_image before set_text_prompt")

        text_outputs = None
        if self.cache_text_features:
            text_outputs = self.text_feature_cache.get(prompt)

        if text_outputs is None:
            with self._autocast_context():
                text_outputs = self._profile_step(
                    "set_text_prompt_forward_text",
                    lambda: self.model.backbone.forward_text(
                        [prompt], device=self.device
                    ),
                )
            if self.cache_text_features:
                self.text_feature_cache[prompt] = text_outputs
        elif self.profile_enabled:
            self.profile_timings["set_text_prompt_forward_text"] = 0.0
        # will erase the previous text prompt if any
        state["backbone_out"].update(text_outputs)
        if "geometric_prompt" not in state:
            state["geometric_prompt"] = self.model._get_dummy_prompt()

        with self._autocast_context():
            return self._profile_step(
                "set_text_prompt_forward_grounding",
                lambda: self._forward_grounding(state),
            )

    @torch.inference_mode()
    def add_geometric_prompt(self, box: List, label: bool, state: Dict):
        """Adds a box prompt and run the inference.
        The image needs to be set, but not necessarily the text prompt.
        The box is assumed to be in [center_x, center_y, width, height] format and normalized in [0, 1] range.
        The label is True for a positive box, False for a negative box.
        """
        if "backbone_out" not in state:
            raise ValueError("You must call set_image before set_text_prompt")

        if "language_features" not in state["backbone_out"]:
            # Looks like we don't have a text prompt yet. This is allowed, but we need to set the text prompt to "visual" for the model to rely only on the geometric prompt
            dummy_text_outputs = self.model.backbone.forward_text(
                ["visual"], device=self.device
            )
            state["backbone_out"].update(dummy_text_outputs)

        if "geometric_prompt" not in state:
            state["geometric_prompt"] = self.model._get_dummy_prompt()

        # adding a batch and sequence dimension
        boxes = torch.tensor(box, device=self.device, dtype=torch.float32).view(1, 1, 4)
        labels = torch.tensor([label], device=self.device, dtype=torch.bool).view(1, 1)
        state["geometric_prompt"].append_boxes(boxes, labels)

        return self._forward_grounding(state)

    def reset_all_prompts(self, state: Dict):
        """Removes all the prompts and results"""
        if "backbone_out" in state:
            backbone_keys_to_del = [
                "language_features",
                "language_mask",
                "language_embeds",
            ]
            for key in backbone_keys_to_del:
                if key in state["backbone_out"]:
                    del state["backbone_out"][key]

        keys_to_del = ["geometric_prompt", "boxes", "masks", "masks_logits", "scores"]
        for key in keys_to_del:
            if key in state:
                del state[key]

    @torch.inference_mode()
    def set_confidence_threshold(self, threshold: float, state=None):
        """Sets the confidence threshold for the masks"""
        self.confidence_threshold = threshold
        if state is not None and "boxes" in state:
            # we need to filter the boxes again
            # In principle we could do this more efficiently since we would only need
            # to rerun the heads. But this is simpler and not too inefficient
            return self._forward_grounding(state)
        return state

    @torch.inference_mode()
    def _forward_grounding(self, state: Dict):
        outputs = self.model.forward_grounding(
            backbone_out=state["backbone_out"],
            find_input=self.find_stage,
            geometric_prompt=state["geometric_prompt"],
            find_target=None,
        )

        out_bbox = outputs["pred_boxes"]
        out_logits = outputs["pred_logits"]
        out_masks = outputs["pred_masks"]
        out_probs = out_logits.sigmoid()
        presence_score = outputs["presence_logit_dec"].sigmoid().unsqueeze(1)
        out_probs = (out_probs * presence_score).squeeze(-1)

        keep = out_probs > self.confidence_threshold
        out_probs = out_probs[keep]
        out_masks = out_masks[keep]
        out_bbox = out_bbox[keep]

        # convert to [x0, y0, x1, y1] format
        boxes = box_ops.box_cxcywh_to_xyxy(out_bbox)

        img_h = state["original_height"]
        img_w = state["original_width"]
        scale_fct = torch.tensor([img_w, img_h, img_w, img_h]).to(self.device)
        boxes = boxes * scale_fct[None, :]

        out_masks = interpolate(
            out_masks.unsqueeze(1),
            (img_h, img_w),
            mode="bilinear",
            align_corners=False,
        ).sigmoid()

        state["masks_logits"] = out_masks
        state["masks"] = out_masks > 0.5
        state["boxes"] = boxes
        state["scores"] = out_probs
        return state
