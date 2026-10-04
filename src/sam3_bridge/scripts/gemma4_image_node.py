#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import requests
import rclpy
from cv_bridge import CvBridge
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, CompressedImage
from std_msgs.msg import String


DEFAULT_IMAGE_TOPIC = "/hsrb/head_rgbd_sensor/rgb/image_rect_color"
DEFAULT_REQUEST_TOPIC = "/gemma4_vlm/request"
DEFAULT_RESPONSE_TOPIC = "/gemma4_vlm/response"
DEFAULT_CONTENT_TOPIC = "/gemma4_vlm/content"
DEFAULT_BASE_URL = "http://localhost:8080/v1"
DEFAULT_MODEL = "gemma4-e2b"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.2
DEFAULT_JPEG_QUALITY = 85
DEFAULT_MAX_WIDTH = 768
DEFAULT_TIMEOUT = 120.0
DEFAULT_DATA_DIR = os.path.join(os.path.expanduser("~"), ".ros", "sam3_bridge")
DEFAULT_PROMPT_FILE = os.path.join(DEFAULT_DATA_DIR, "gemma4_prompt.txt")
DEFAULT_OUTPUT_FILE = os.path.join(DEFAULT_DATA_DIR, "gemma4_response.txt")
DEFAULT_OUTPUT_JSON_FILE = os.path.join(DEFAULT_DATA_DIR, "gemma4_response.json")
DEFAULT_DEBUG_IMAGE_PATH = os.path.join(DEFAULT_DATA_DIR, "gemma4_request.jpg")


class Gemma4VLMImageNode(Node):
    def __init__(self):
        super().__init__("gemma4_vlm_image_node")

        defaults = {
            "image_topic": DEFAULT_IMAGE_TOPIC,
            "image_topic_type": "auto",
            "request_topic": DEFAULT_REQUEST_TOPIC,
            "response_topic": DEFAULT_RESPONSE_TOPIC,
            "content_topic": DEFAULT_CONTENT_TOPIC,
            "base_url": DEFAULT_BASE_URL,
            "model": DEFAULT_MODEL,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "temperature": DEFAULT_TEMPERATURE,
            "jpeg_quality": DEFAULT_JPEG_QUALITY,
            "max_width": DEFAULT_MAX_WIDTH,
            "timeout": DEFAULT_TIMEOUT,
            "include_reasoning": False,
            "prompt_file": DEFAULT_PROMPT_FILE,
            "output_file": DEFAULT_OUTPUT_FILE,
            "output_json_file": DEFAULT_OUTPUT_JSON_FILE,
            "write_output_file": True,
            "write_output_json_file": True,
            "default_prompt": "この画像に写っている物体を箇条書きで説明してください。",
            "request_uses_file_commands": ["", "record", "infer", "run", "default"],
            "save_debug_image": True,
            "debug_image_path": DEFAULT_DEBUG_IMAGE_PATH,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)

        value = lambda name: self.get_parameter(name).value
        self.image_topic = str(value("image_topic"))
        self.image_topic_type = str(value("image_topic_type")).lower()
        self.request_topic = str(value("request_topic"))
        self.response_topic = str(value("response_topic"))
        self.content_topic = str(value("content_topic"))
        self.base_url = str(value("base_url"))
        self.model = str(value("model"))
        self.max_tokens = int(value("max_tokens"))
        self.temperature = float(value("temperature"))
        self.jpeg_quality = int(value("jpeg_quality"))
        self.max_width = int(value("max_width"))
        self.timeout = float(value("timeout"))
        self.include_reasoning = bool(value("include_reasoning"))
        self.prompt_file = os.path.expanduser(str(value("prompt_file")))
        self.output_file = os.path.expanduser(str(value("output_file")))
        self.output_json_file = os.path.expanduser(str(value("output_json_file")))
        self.write_output_file = bool(value("write_output_file"))
        self.write_output_json_file = bool(value("write_output_json_file"))
        self.default_prompt = str(value("default_prompt"))
        self.request_uses_file_commands = set(value("request_uses_file_commands"))
        self.save_debug_image = bool(value("save_debug_image"))
        self.debug_image_path = os.path.expanduser(str(value("debug_image_path")))
        self.bridge = CvBridge()
        self.lock = threading.Lock()
        self.request_lock = threading.Lock()
        self.latest_msg = None
        self.latest_is_compressed = False
        self.latest_stamp = None
        self.latest_frame_id = ""
        self.latest_receive_time = None
        self.response_pub = self.create_publisher(String, self.response_topic, 10)
        self.content_pub = self.create_publisher(String, self.content_topic, 10)

        image_type = self._resolve_image_topic_type()
        image_group = MutuallyExclusiveCallbackGroup()
        request_group = MutuallyExclusiveCallbackGroup()
        if image_type == "raw":
            self.image_sub = self.create_subscription(
                Image, self.image_topic, self.image_cb, qos_profile_sensor_data,
                callback_group=image_group)
        elif image_type == "compressed":
            self.image_sub = self.create_subscription(
                CompressedImage, self.image_topic, self.compressed_image_cb,
                qos_profile_sensor_data, callback_group=image_group)
        else:
            raise RuntimeError("image_topic_type must be auto, raw, or compressed")

        self.request_sub = self.create_subscription(
            String, self.request_topic, self.request_cb, 1,
            callback_group=request_group)

        logger = self.get_logger()
        logger.info("Gemma4 VLM image node ready.")
        logger.info("image_topic     : %s" % self.image_topic)
        logger.info("image_topic_type: %s" % image_type)
        logger.info("request_topic   : %s" % self.request_topic)
        logger.info("response_topic  : %s" % self.response_topic)
        logger.info("content_topic   : %s" % self.content_topic)
        logger.info("base_url        : %s" % self.base_url)
        logger.info("model           : %s" % self.model)
        logger.info("prompt_file     : %s" % self.prompt_file)
        logger.info("output_file     : %s" % self.output_file)
        logger.info("output_json_file: %s" % self.output_json_file)

    def _resolve_image_topic_type(self) -> str:
        if self.image_topic_type != "auto":
            return self.image_topic_type

        self.get_logger().info(
            "Waiting for image topic type: %s" % self.image_topic)
        while rclpy.ok():
            types = dict(self.get_topic_names_and_types()).get(self.image_topic, [])
            if "sensor_msgs/msg/Image" in types:
                return "raw"
            if "sensor_msgs/msg/CompressedImage" in types:
                return "compressed"
            rclpy.spin_once(self, timeout_sec=0.2)
        raise RuntimeError("ROS shutdown while waiting for image topic")

    def image_cb(self, msg: Image) -> None:
        with self.lock:
            self.latest_msg = msg
            self.latest_is_compressed = False
            self.latest_stamp = msg.header.stamp
            self.latest_frame_id = msg.header.frame_id
            self.latest_receive_time = time.time()

    def compressed_image_cb(self, msg: CompressedImage) -> None:
        with self.lock:
            self.latest_msg = msg
            self.latest_is_compressed = True
            self.latest_stamp = msg.header.stamp
            self.latest_frame_id = msg.header.frame_id
            self.latest_receive_time = time.time()

    def load_prompt_from_file(self) -> str:
        path = Path(self.prompt_file)
        if not path.exists():
            self.get_logger().warning(
                "prompt_file does not exist: %s. Use default_prompt." % self.prompt_file)
            return self.default_prompt

        text = path.read_text(encoding="utf-8").strip()
        if not text:
            self.get_logger().warning(
                "prompt_file is empty: %s. Use default_prompt." % self.prompt_file)
            return self.default_prompt
        return text

    def resolve_prompt(self, request_text: str) -> Tuple[str, str]:
        request_text = (request_text or "").strip()
        if request_text in self.request_uses_file_commands:
            return self.load_prompt_from_file(), "file"
        return request_text, "topic"

    def get_latest_image_snapshot(self):
        with self.lock:
            if self.latest_msg is None:
                return None
            return (
                self.latest_msg,
                self.latest_is_compressed,
                self.latest_stamp,
                self.latest_frame_id,
                self.latest_receive_time,
            )

    def msg_to_cv_bgr(self, msg, is_compressed: bool):
        if is_compressed:
            arr = np.frombuffer(msg.data, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                raise RuntimeError("CompressedImage decode failed")
            return img
        return self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")

    def resize_if_needed(self, img):
        h, w = img.shape[:2]
        if self.max_width <= 0 or w <= self.max_width:
            return img
        scale = float(self.max_width) / float(w)
        new_w = self.max_width
        new_h = int(h * scale)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    def encode_jpeg(self, img):
        img = self.resize_if_needed(img)
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        if not ok:
            raise RuntimeError("JPEG encode failed")
        return img, buf.tobytes()

    def request_cb(self, msg: String) -> None:
        if not self.request_lock.acquire(blocking=False):
            self.get_logger().warning("VLM request is already running; request ignored.")
            return
        try:
            self._handle_request(msg)
        finally:
            self.request_lock.release()

    def _handle_request(self, msg: String) -> None:
        prompt, prompt_source = self.resolve_prompt(msg.data)

        snapshot = self.get_latest_image_snapshot()
        if snapshot is None:
            self.get_logger().warning("まだ画像を受信していません。")
            self.publish_error(prompt, prompt_source, "no image received yet")
            return

        image_msg, is_compressed, stamp, frame_id, receive_time = snapshot
        image_age_sec = time.time() - receive_time if receive_time is not None else None

        self.get_logger().info(
            "VLM request. prompt_source=%s, prompt='%s', image_age=%.3f sec, frame_id=%s"
            % (prompt_source, prompt.replace("\n", " ")[:120],
               image_age_sec if image_age_sec is not None else -1.0, frame_id))

        start_time = time.time()
        try:
            cv_img = self.msg_to_cv_bgr(image_msg, is_compressed)
            encoded_img, jpeg_bytes = self.encode_jpeg(cv_img)

            if self.save_debug_image:
                self.ensure_parent_dir(self.debug_image_path)
                cv2.imwrite(self.debug_image_path, encoded_img)

            result = self.call_llamacpp(prompt, jpeg_bytes)
            elapsed = time.time() - start_time

            response = {
                "ok": True,
                "prompt": prompt,
                "prompt_source": prompt_source,
                "stamp": self.stamp_to_sec(stamp),
                "frame_id": frame_id,
                "image_age_sec": image_age_sec,
                "image_shape": {
                    "height": int(encoded_img.shape[0]),
                    "width": int(encoded_img.shape[1]),
                },
                "jpeg_size_bytes": len(jpeg_bytes),
                "elapsed_sec": elapsed,
                "finish_reason": result.get("finish_reason", ""),
                "content": result.get("content", ""),
                "usage": result.get("usage", {}),
                "timings": result.get("timings", {}),
            }

            if self.include_reasoning:
                response["reasoning_content"] = result.get("reasoning_content", "")

            self.response_pub.publish(String(data=json.dumps(response, ensure_ascii=False)))
            self.content_pub.publish(String(data=response["content"]))

            if self.write_output_file:
                self.write_text_output(response)
            if self.write_output_json_file:
                self.write_json_output(response)

            self.get_logger().info(
                "VLM response. elapsed=%.3f sec, finish_reason=%s, content_len=%d"
                % (elapsed, response["finish_reason"], len(response["content"])))

        except Exception as e:
            self.get_logger().error("VLM request failed: %s" % e)
            self.publish_error(prompt, prompt_source, str(e))

    @staticmethod
    def stamp_to_sec(stamp) -> Optional[float]:
        if stamp is None:
            return None
        return float(stamp.sec) + float(stamp.nanosec) * 1.0e-9

    def call_llamacpp(self, prompt: str, jpeg_bytes: bytes) -> dict:
        img_b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/jpeg;base64," + img_b64
                            },
                        },
                    ],
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        url = self.base_url.rstrip("/") + "/chat/completions"
        r = requests.post(url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        choice = data["choices"][0]
        msg = choice.get("message", {})

        return {
            "finish_reason": choice.get("finish_reason", ""),
            "content": msg.get("content", ""),
            "reasoning_content": msg.get("reasoning_content", ""),
            "usage": data.get("usage", {}),
            "timings": data.get("timings", {}),
        }

    def publish_error(self, prompt: str, prompt_source: str, error: str) -> None:
        response = {
            "ok": False,
            "prompt": prompt,
            "prompt_source": prompt_source,
            "error": error,
        }
        self.response_pub.publish(String(data=json.dumps(response, ensure_ascii=False)))
        self.content_pub.publish(String(data=""))
        if self.write_output_json_file:
            self.write_json_output(response)
        if self.write_output_file:
            self.ensure_parent_dir(self.output_file)
            Path(self.output_file).write_text("ERROR: {}\n".format(error), encoding="utf-8")

    @staticmethod
    def ensure_parent_dir(path: str) -> None:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def write_text_output(self, response: dict) -> None:
        self.ensure_parent_dir(self.output_file)
        lines = []
        lines.append("ok: {}".format(response.get("ok")))
        lines.append("finish_reason: {}".format(response.get("finish_reason", "")))
        lines.append("prompt_source: {}".format(response.get("prompt_source", "")))
        lines.append("stamp: {}".format(response.get("stamp", "")))
        lines.append("frame_id: {}".format(response.get("frame_id", "")))
        lines.append("image_age_sec: {}".format(response.get("image_age_sec", "")))
        lines.append("elapsed_sec: {}".format(response.get("elapsed_sec", "")))
        lines.append("")
        lines.append("=== prompt ===")
        lines.append(response.get("prompt", ""))
        lines.append("")
        lines.append("=== content ===")
        lines.append(response.get("content", ""))
        if self.include_reasoning and response.get("reasoning_content"):
            lines.append("")
            lines.append("=== reasoning_content ===")
            lines.append(response.get("reasoning_content", ""))
        Path(self.output_file).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_json_output(self, response: dict) -> None:
        self.ensure_parent_dir(self.output_json_file)
        Path(self.output_json_file).write_text(
            json.dumps(response, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main(args=None):
    rclpy.init(args=args)
    node = Gemma4VLMImageNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
