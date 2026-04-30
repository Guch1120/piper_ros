"""ROS2 node for SAM3 segmentation."""

from __future__ import annotations

import threading
import time

import numpy as np

from .bridge import bgr_to_image_msg, flatten_boxes, image_msg_to_bgr, mask_to_image_msg
from .config import Sam3RosConfig
from .segmenter import Sam3ImageSegmenter


def build_ros2_node(bindings, config: Sam3RosConfig):
    """Create a ROS2 node instance."""

    from rclpy.node import Node
    from sensor_msgs.msg import Image
    from std_msgs.msg import Float32MultiArray, String

    class Sam3Ros2Node(Node):
        def __init__(self) -> None:
            super().__init__(config.node_name)
            self._lock = threading.Lock()
            self._busy = False
            self._latest_prompt = config.model.text_prompt
            self._segmenter = Sam3ImageSegmenter(config.model)
            self._bridge = bindings.bridge
            self._declare_parameters()

            self._image_topic = self.get_parameter("image_topic").value
            self._prompt_topic = self.get_parameter("prompt_topic").value
            self._annotated_topic = self.get_parameter("annotated_topic").value
            self._masks_topic = self.get_parameter("masks_topic").value
            self._boxes_topic = self.get_parameter("boxes_topic").value
            self._scores_topic = self.get_parameter("scores_topic").value
            self._frame_id = self.get_parameter("frame_id").value
            self._input_encoding = self.get_parameter("input_encoding").value
            self._queue_size = int(self.get_parameter("queue_size").value)
            self._drop_when_busy = bool(self.get_parameter("drop_frames_when_busy").value)
            self._profile_every_n = int(self.get_parameter("profile_every_n").value)
            self._profile_frame_count = 0
            self._profile_totals = {
                "convert": 0.0,
                "segment": 0.0,
                "segment_set_image": 0.0,
                "segment_set_text": 0.0,
                "segment_forward_image": 0.0,
                "segment_forward_text": 0.0,
                "segment_forward_grounding": 0.0,
                "segment_overlay": 0.0,
                "annotated": 0.0,
                "mask": 0.0,
                "boxes": 0.0,
                "scores": 0.0,
                "total": 0.0,
            }

            self._annotated_pub = self.create_publisher(Image, self._annotated_topic, self._queue_size)
            self._masks_pub = self.create_publisher(Image, self._masks_topic, self._queue_size)
            self._boxes_pub = self.create_publisher(Float32MultiArray, self._boxes_topic, self._queue_size)
            self._scores_pub = self.create_publisher(Float32MultiArray, self._scores_topic, self._queue_size)
            self._prompt_sub = self.create_subscription(
                String, self._prompt_topic, self._on_prompt, self._queue_size
            )
            self._image_sub = self.create_subscription(
                Image, self._image_topic, self._on_image, self._queue_size
            )
            self.get_logger().info(
                "SAM3 runtime config: device=%s resolution=%d autocast=%s channels_last=%s backend=%s text_cache=%s queries=%s decoder_layers=%s"
                % (
                    self._segmenter.device,
                    config.model.resolution,
                    self._segmenter.autocast_dtype_name,
                    self._segmenter.channels_last_enabled,
                    self._segmenter.image_encoder_backend,
                    config.model.cache_text_features,
                    config.model.query_limit if config.model.query_limit > 0 else "default",
                    config.model.decoder_layers if config.model.decoder_layers > 0 else "default",
                )
            )

        def _declare_parameters(self) -> None:
            self.declare_parameter("image_topic", config.topics.image_topic)
            self.declare_parameter("prompt_topic", config.topics.prompt_topic)
            self.declare_parameter("annotated_topic", config.topics.annotated_topic)
            self.declare_parameter("masks_topic", config.topics.masks_topic)
            self.declare_parameter("boxes_topic", config.topics.boxes_topic)
            self.declare_parameter("scores_topic", config.topics.scores_topic)
            self.declare_parameter("frame_id", config.topics.frame_id)
            self.declare_parameter("input_encoding", config.topics.input_encoding)
            self.declare_parameter("queue_size", config.topics.queue_size)
            self.declare_parameter("drop_frames_when_busy", config.drop_frames_when_busy)
            self.declare_parameter("profile_every_n", 30)
            self.declare_parameter("text_prompt", config.model.text_prompt)

        def _on_prompt(self, msg: String) -> None:
            self._latest_prompt = msg.data.strip()

        def _record_profile(self, timings: dict[str, float]) -> None:
            if self._profile_every_n <= 0:
                return
            self._profile_frame_count += 1
            for key, value in timings.items():
                self._profile_totals[key] += value
            if self._profile_frame_count % self._profile_every_n != 0:
                return
            averages = {
                key: self._profile_totals[key] / self._profile_frame_count
                for key in self._profile_totals
            }
            fps = 1.0 / max(averages["total"], 1e-9)
            self.get_logger().info(
                "SAM3 profile avg over %d frames: total=%.4fs (%.2f FPS) convert=%.4fs segment=%.4fs set_image=%.4fs set_text=%.4fs fwd_image=%.4fs fwd_text=%.4fs fwd_grounding=%.4fs overlay=%.4fs annotated=%.4fs mask=%.4fs boxes=%.4fs scores=%.4fs"
                % (
                    self._profile_frame_count,
                    averages["total"],
                    fps,
                    averages["convert"],
                    averages["segment"],
                    averages["segment_set_image"],
                    averages["segment_set_text"],
                    averages["segment_forward_image"],
                    averages["segment_forward_text"],
                    averages["segment_forward_grounding"],
                    averages["segment_overlay"],
                    averages["annotated"],
                    averages["mask"],
                    averages["boxes"],
                    averages["scores"],
                )
            )

        def _on_image(self, msg: Image) -> None:
            if self._drop_when_busy and self._busy:
                return
            with self._lock:
                if self._busy and self._drop_when_busy:
                    return
                self._busy = True
            timings = {
                "convert": 0.0,
                "segment": 0.0,
                "annotated": 0.0,
                "mask": 0.0,
                "boxes": 0.0,
                "scores": 0.0,
                "total": 0.0,
            }
            total_start = time.perf_counter()
            try:
                wants_annotated = self._annotated_pub.get_subscription_count() > 0
                wants_masks = self._masks_pub.get_subscription_count() > 0
                wants_boxes = self._boxes_pub.get_subscription_count() > 0
                wants_scores = self._scores_pub.get_subscription_count() > 0

                start = time.perf_counter()
                image_bgr = image_msg_to_bgr(self._bridge, msg, encoding=self._input_encoding)
                timings["convert"] = time.perf_counter() - start

                start = time.perf_counter()
                result = self._segmenter.segment(
                    image_bgr,
                    prompt=self._latest_prompt,
                    render_annotated=wants_annotated,
                )
                timings["segment"] = time.perf_counter() - start
                timings["segment_set_image"] = result.timings.get("set_image_total", 0.0)
                timings["segment_set_text"] = result.timings.get("set_text_prompt_total", 0.0)
                timings["segment_forward_image"] = result.timings.get("set_image_forward_image", 0.0)
                timings["segment_forward_text"] = result.timings.get("set_text_prompt_forward_text", 0.0)
                timings["segment_forward_grounding"] = result.timings.get("set_text_prompt_forward_grounding", 0.0)
                timings["segment_overlay"] = result.timings.get("render_overlay", 0.0)

                if wants_annotated and result.annotated_bgr is not None:
                    start = time.perf_counter()
                    annotated_msg = bgr_to_image_msg(self._bridge, result.annotated_bgr, encoding="bgr8")
                    annotated_msg.header = msg.header
                    annotated_msg.header.frame_id = self._frame_id
                    self._annotated_pub.publish(annotated_msg)
                    timings["annotated"] = time.perf_counter() - start

                if wants_masks and result.masks:
                    start = time.perf_counter()
                    union_mask = np.any(np.stack(result.masks, axis=0), axis=0)
                    masks_msg = mask_to_image_msg(self._bridge, union_mask)
                    masks_msg.header = msg.header
                    masks_msg.header.frame_id = self._frame_id
                    self._masks_pub.publish(masks_msg)
                    timings["mask"] = time.perf_counter() - start

                if wants_boxes:
                    start = time.perf_counter()
                    boxes_msg = Float32MultiArray()
                    boxes_msg.data = flatten_boxes(result.boxes)
                    self._boxes_pub.publish(boxes_msg)
                    timings["boxes"] = time.perf_counter() - start

                if wants_scores:
                    start = time.perf_counter()
                    scores_msg = Float32MultiArray()
                    scores_msg.data = result.scores
                    self._scores_pub.publish(scores_msg)
                    timings["scores"] = time.perf_counter() - start
            finally:
                timings["total"] = time.perf_counter() - total_start
                self._record_profile(timings)
                with self._lock:
                    self._busy = False

    return Sam3Ros2Node()
