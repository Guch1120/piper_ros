#!/usr/bin/env python3
import queue
import threading

import cv2
import grpc
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

import segment_overlay_pb2 as segment_pb2
import segment_overlay_pb2_grpc as segment_pb2_grpc


class ROSToGRPCBridge(Node):
    def __init__(self):
        super().__init__("grpc_bridge")
        defaults = {
            "grpc_host": "localhost",
            "grpc_port": 50051,
            "grpc_timeout": 2.0,
            "jpeg_quality": 75,
            "max_width": 640,
            "max_height": 480,
            "prompt": "person",
            "topic_name": "/hsrb/head_rgbd_sensor/rgb/image_rect_color",
            "mask_topic": "/sam/mask",
            "overlay_topic": "/sam/overlay",
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)

        value = lambda name: self.get_parameter(name).value
        host = str(value("grpc_host"))
        port = int(value("grpc_port"))
        self.timeout = float(value("grpc_timeout"))
        self.quality = int(value("jpeg_quality"))
        self.max_w = int(value("max_width"))
        self.max_h = int(value("max_height"))
        self.prompt = str(value("prompt"))
        topic = str(value("topic_name"))
        mask_topic = str(value("mask_topic"))
        overlay_topic = str(value("overlay_topic"))

        addr = f"{host}:{port}"
        self.channel = grpc.insecure_channel(addr)
        self.stub = segment_pb2_grpc.SegmentServiceStub(self.channel)
        self.bridge = CvBridge()
        self.mask_pub = self.create_publisher(Image, mask_topic, 1)
        self.overlay_pub = self.create_publisher(Image, overlay_topic, 1)
        self.image_sub = self.create_subscription(
            Image, topic, self.image_callback, qos_profile_sensor_data
        )

        self.frame_queue = queue.Queue(maxsize=1)
        self.stats = {"received": 0, "dropped": 0, "sent": 0, "failed": 0}
        self.stats_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        self.worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="grpc_worker"
        )
        self.worker_thread.start()
        self.stats_timer = self.create_timer(10.0, self._log_stats)

        self.get_logger().info(f"[Bridge] gRPC接続先: {addr}")
        self.get_logger().info(f"[Bridge] 入力: {topic}")
        self.get_logger().info(f"[Bridge] 出力: {mask_topic}, {overlay_topic}")

    def image_callback(self, msg):
        with self.stats_lock:
            self.stats["received"] += 1
        try:
            self.frame_queue.get_nowait()
            with self.stats_lock:
                self.stats["dropped"] += 1
        except queue.Empty:
            pass
        try:
            self.frame_queue.put_nowait(msg)
        except queue.Full:
            with self.stats_lock:
                self.stats["dropped"] += 1

    def _worker_loop(self):
        while rclpy.ok() and not self.shutdown_event.is_set():
            try:
                msg = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._process_frame(msg)
                with self.stats_lock:
                    self.stats["sent"] += 1
            except grpc.RpcError as exc:
                with self.stats_lock:
                    self.stats["failed"] += 1
                self.get_logger().warning(
                    f"[Bridge] gRPC失敗: code={exc.code()} details={exc.details()}"
                )
            except Exception as exc:
                with self.stats_lock:
                    self.stats["failed"] += 1
                self.get_logger().error(f"[Bridge] 予期せぬエラー: {exc!r}")

    def _process_frame(self, msg):
        image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        image = np.ascontiguousarray(image, dtype=np.uint8)
        h, w = image.shape[:2]
        if w > self.max_w or h > self.max_h:
            image = cv2.resize(image, (self.max_w, self.max_h))
            h, w = self.max_h, self.max_w
        ok, jpeg = cv2.imencode(
            ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
        )
        if not ok:
            raise RuntimeError("JPEG encode failed")

        response = self.stub.SegmentImage(
            segment_pb2.ImageRequest(
                image=jpeg.tobytes(), width=w, height=h, prompt=self.prompt
            ),
            timeout=self.timeout,
        )
        if response.mask_encoding == "16UC1":
            mask = np.frombuffer(response.mask, dtype=np.uint16).reshape(
                response.height, response.width
            )
            mask_msg = self.bridge.cv2_to_imgmsg(mask, encoding="16UC1")
        else:
            mask = np.frombuffer(response.mask, dtype=np.uint8).reshape(
                response.height, response.width
            )
            mask_msg = self.bridge.cv2_to_imgmsg(
                (mask > 0).astype(np.uint8) * 255, encoding="mono8"
            )
        mask_msg.header = msg.header
        self.mask_pub.publish(mask_msg)

        if response.overlay_image:
            overlay = cv2.imdecode(
                np.frombuffer(response.overlay_image, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            if overlay is not None:
                overlay_msg = self.bridge.cv2_to_imgmsg(overlay, encoding="bgr8")
                overlay_msg.header = msg.header
                self.overlay_pub.publish(overlay_msg)

        self.get_logger().info(
            f"[Bridge] mask publish {response.width}x{response.height} "
            f"objects={response.num_objects} inference={response.inference_ms:.1f}ms"
        )

    def _log_stats(self):
        with self.stats_lock:
            stats = self.stats.copy()
        self.get_logger().info(
            f"[Bridge] 統計 | 受信:{stats['received']} 破棄:{stats['dropped']} "
            f"送信成功:{stats['sent']} 失敗:{stats['failed']}"
        )

    def destroy_node(self):
        self.shutdown_event.set()
        self.worker_thread.join(timeout=max(1.0, self.timeout + 0.5))
        self.channel.close()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ROSToGRPCBridge()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
