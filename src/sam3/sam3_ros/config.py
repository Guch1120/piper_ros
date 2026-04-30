"""Configuration objects for the SAM3 ROS wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Sam3ModelConfig:
    """Model-side settings."""

    checkpoint_path: str | None = None
    device: str = "cuda"
    load_from_hf: bool = True
    enable_segmentation: bool = True
    enable_inst_interactivity: bool = False
    compile: bool = False
    resolution: int = 854
    use_autocast: bool | None = None
    use_channels_last: bool | None = None
    text_prompt: str = ""
    cache_text_features: bool = True
    query_limit: int = 0
    decoder_layers: int = 0
    image_encoder_onnx_path: str | None = None
    onnx_provider: str = "tensorrt"
    onnx_trt_fp16: bool = True


@dataclass(slots=True)
class RosTopicConfig:
    """Topic and frame settings shared by the ROS1/ROS2 nodes."""

    image_topic: str = "/camera/image_raw"
    prompt_topic: str = "/sam3/text_prompt"
    annotated_topic: str = "/sam3/annotated_image"
    masks_topic: str = "/sam3/masks"
    boxes_topic: str = "/sam3/boxes"
    scores_topic: str = "/sam3/scores"
    frame_id: str = "camera"
    input_encoding: str = "bgr8"
    queue_size: int = 1


@dataclass(slots=True)
class Sam3RosConfig:
    """Full runtime configuration for a dual-stack SAM3 node."""

    model: Sam3ModelConfig = field(default_factory=Sam3ModelConfig)
    topics: RosTopicConfig = field(default_factory=RosTopicConfig)
    backend: str = "auto"
    node_name: str = "sam3_ros"
    drop_frames_when_busy: bool = True
