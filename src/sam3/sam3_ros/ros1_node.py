"""ROS1 node for SAM3 segmentation."""

from __future__ import annotations

import threading

import numpy as np

from .bridge import bgr_to_image_msg, flatten_boxes, image_msg_to_bgr, mask_to_image_msg
from .config import Sam3RosConfig
from .segmenter import Sam3ImageSegmenter


def build_ros1_node(bindings, config: Sam3RosConfig):
    """Create a ROS1 node instance."""

    import rospy
    from sensor_msgs.msg import Image
    from std_msgs.msg import Float32MultiArray, String

    class Sam3Ros1Node:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self._busy = False
            self._latest_prompt = config.model.text_prompt
            self._segmenter = Sam3ImageSegmenter(config.model)
            self._bridge = bindings.bridge

            self._image_topic = rospy.get_param("~image_topic", config.topics.image_topic)
            self._prompt_topic = rospy.get_param("~prompt_topic", config.topics.prompt_topic)
            self._annotated_topic = rospy.get_param(
                "~annotated_topic", config.topics.annotated_topic
            )
            self._masks_topic = rospy.get_param("~masks_topic", config.topics.masks_topic)
            self._boxes_topic = rospy.get_param("~boxes_topic", config.topics.boxes_topic)
            self._scores_topic = rospy.get_param("~scores_topic", config.topics.scores_topic)
            self._frame_id = rospy.get_param("~frame_id", config.topics.frame_id)
            self._input_encoding = rospy.get_param(
                "~input_encoding", config.topics.input_encoding
            )
            self._queue_size = int(rospy.get_param("~queue_size", config.topics.queue_size))
            self._drop_when_busy = bool(
                rospy.get_param("~drop_frames_when_busy", config.drop_frames_when_busy)
            )

            self._annotated_pub = rospy.Publisher(self._annotated_topic, Image, queue_size=self._queue_size)
            self._masks_pub = rospy.Publisher(self._masks_topic, Image, queue_size=self._queue_size)
            self._boxes_pub = rospy.Publisher(self._boxes_topic, Float32MultiArray, queue_size=self._queue_size)
            self._scores_pub = rospy.Publisher(self._scores_topic, Float32MultiArray, queue_size=self._queue_size)
            self._prompt_sub = rospy.Subscriber(self._prompt_topic, String, self._on_prompt, queue_size=self._queue_size)
            self._image_sub = rospy.Subscriber(self._image_topic, Image, self._on_image, queue_size=self._queue_size)

        def _on_prompt(self, msg: String) -> None:
            self._latest_prompt = msg.data.strip()

        def _on_image(self, msg: Image) -> None:
            if self._drop_when_busy and self._busy:
                return
            with self._lock:
                if self._busy and self._drop_when_busy:
                    return
                self._busy = True
            try:
                image_bgr = image_msg_to_bgr(self._bridge, msg, encoding=self._input_encoding)
                result = self._segmenter.segment(image_bgr, prompt=self._latest_prompt)

                annotated_msg = bgr_to_image_msg(self._bridge, result.annotated_bgr, encoding="bgr8")
                annotated_msg.header = msg.header
                annotated_msg.header.frame_id = self._frame_id
                self._annotated_pub.publish(annotated_msg)

                if result.masks:
                    union_mask = np.any(np.stack(result.masks, axis=0), axis=0)
                    masks_msg = mask_to_image_msg(self._bridge, union_mask)
                    masks_msg.header = msg.header
                    masks_msg.header.frame_id = self._frame_id
                    self._masks_pub.publish(masks_msg)

                boxes_msg = Float32MultiArray()
                boxes_msg.data = flatten_boxes(result.boxes)
                self._boxes_pub.publish(boxes_msg)

                scores_msg = Float32MultiArray()
                scores_msg.data = result.scores
                self._scores_pub.publish(scores_msg)
            finally:
                with self._lock:
                    self._busy = False

    return Sam3Ros1Node()
