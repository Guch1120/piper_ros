import base64
import json
import threading
import urllib.request

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String


class VisionBridge(Node):
    def __init__(self):
        super().__init__("piper_websim_vision_bridge")
        self.declare_parameter("endpoint", "")
        self.declare_parameter("image_topic", "/camera/camera/color/image_raw/compressed")
        self.declare_parameter("depth_topic", "/camera/camera/aligned_depth_to_color/image_raw")
        self.declare_parameter("result_topic", "/vision/inference_result")
        self.declare_parameter("period", 0.5)
        self._endpoint = str(self.get_parameter("endpoint").value).strip()
        self._image = None
        self._depth = None
        self._lock = threading.Lock()
        self.create_subscription(CompressedImage, str(self.get_parameter("image_topic").value), self._on_image, 10)
        self.create_subscription(Image, str(self.get_parameter("depth_topic").value), self._on_depth, 10)
        self._result = self.create_publisher(String, str(self.get_parameter("result_topic").value), 10)
        self.create_timer(float(self.get_parameter("period").value), self._infer)
        if self._endpoint:
            self.get_logger().info("vision endpoint enabled")
        else:
            self.get_logger().info("vision endpoint is empty; forwarding disabled")

    def _on_image(self, message):
        with self._lock:
            self._image = message

    def _on_depth(self, message):
        with self._lock:
            self._depth = message

    def _payload(self):
        with self._lock:
            image, depth = self._image, self._depth
        if image is None:
            return None
        image_bytes = bytes(image.data)
        payload = {"image": {"data_url": "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii"), "format": "jpeg"}}
        if depth is not None:
            payload["depth"] = {"encoding": depth.encoding, "width": int(depth.width), "height": int(depth.height), "data": base64.b64encode(bytes(depth.data)).decode("ascii")}
        return payload

    def _infer(self):
        if not self._endpoint:
            return
        payload = self._payload()
        if payload is None:
            return
        request = urllib.request.Request(self._endpoint, data=json.dumps(payload).encode("utf-8"), headers={"content-type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                result = response.read().decode("utf-8")
            message = String()
            message.data = result
            self._result.publish(message)
        except Exception as error:
            self.get_logger().warning(f"vision request failed: {error}")


def main(args=None):
    rclpy.init(args=args)
    node = VisionBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
