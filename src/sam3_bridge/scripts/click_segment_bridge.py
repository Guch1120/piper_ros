#!/usr/bin/env python3
import os
import queue
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "click_segment"))

import cv2
import grpc
import numpy as np
import rclpy
import tf2_geometry_msgs  # noqa: F401 - PointStamped transform registration
import tf2_ros
from cv_bridge import CvBridge
from geometry_msgs.msg import PointStamped
from image_geometry import PinholeCameraModel
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image

import click_segment_pb2
import click_segment_pb2_grpc


class ClickSegmentBridge(Node):
    def __init__(self):
        super().__init__("click_segment_bridge")
        defaults = {
            "grpc_host": "localhost",
            "grpc_port": 50051,
            "grpc_timeout": 10.0,
            "jpeg_quality": 75,
            "max_width": 640,
            "max_height": 480,
            "topic_name": "/hsrb/head_rgbd_sensor/rgb/image_rect_color",
            "camera_info_topic": "/hsrb/head_rgbd_sensor/rgb/camera_info",
            "clicked_point_topic": "/clicked_point",
            "target_frame": "head_rgbd_sensor_rgb_frame",
            "mask_topic": "/sam/mask",
            "overlay_topic": "/sam/overlay",
        }
        for name, default in defaults.items():
            self.declare_parameter(name, default)
        value = lambda name: self.get_parameter(name).value

        host = str(value("grpc_host"))
        port = int(value("grpc_port"))
        self.timeout = float(value("grpc_timeout"))
        self.quality = int(value("jpeg_quality"))
        self.max_w = int(value("max_width"))
        self.max_h = int(value("max_height"))
        self.target_frame = str(value("target_frame"))

        addr = f"{host}:{port}"
        self.channel = grpc.insecure_channel(addr)
        self.stub = click_segment_pb2_grpc.ClickSegmentServiceStub(self.channel)
        self.bridge = CvBridge()
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)
        self.cam_model = PinholeCameraModel()
        self.cam_model_ready = False

        self.pending_click = None
        self.pending_lock = threading.Lock()
        self.frame_queue = queue.Queue(maxsize=1)
        self.stats = {"received": 0, "dropped": 0, "sent": 0, "failed": 0}
        self.stats_lock = threading.Lock()
        self.shutdown_event = threading.Event()

        self.mask_pub = self.create_publisher(Image, str(value("mask_topic")), 1)
        self.overlay_pub = self.create_publisher(
            Image, str(value("overlay_topic")), 1
        )
        self.camera_info_sub = self.create_subscription(
            CameraInfo,
            str(value("camera_info_topic")),
            self._camera_info_callback,
            qos_profile_sensor_data,
        )
        self.clicked_point_sub = self.create_subscription(
            PointStamped,
            str(value("clicked_point_topic")),
            self._clicked_point_callback,
            1,
        )
        self.image_sub = self.create_subscription(
            Image,
            str(value("topic_name")),
            self._image_callback,
            qos_profile_sensor_data,
        )

        self.worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="grpc_worker"
        )
        self.worker_thread.start()
        self.stats_timer = self.create_timer(10.0, self._log_stats)
        self.get_logger().info(f"[ClickBridge] gRPC接続先: {addr}")
        self.get_logger().info("[ClickBridge] 起動完了 - clicked pointを待機中")

    def _camera_info_callback(self, msg):
        if self.cam_model_ready:
            return
        self.cam_model.fromCameraInfo(msg)
        self.cam_model_ready = True
        self.get_logger().info(
            f"[ClickBridge] カメラモデル取得完了 "
            f"{self.cam_model.width}x{self.cam_model.height} "
            f"fx={self.cam_model.fx():.1f} fy={self.cam_model.fy():.1f}"
        )

    def _clicked_point_callback(self, msg):
        if not self.cam_model_ready:
            self.get_logger().warning(
                "[ClickBridge] camera_info未取得のためスキップ"
            )
            return
        try:
            point_cam = self.tf_buffer.transform(
                msg, self.target_frame, timeout=Duration(seconds=0.5)
            )
        except Exception as exc:
            self.get_logger().warning(f"[ClickBridge] tf2変換失敗: {exc}")
            return

        x, y, z = point_cam.point.x, point_cam.point.y, point_cam.point.z
        if z <= 0:
            self.get_logger().warning("[ClickBridge] Z <= 0のためスキップ")
            return
        u = self.cam_model.cx() + (x / z) * self.cam_model.fx()
        v = self.cam_model.cy() + (y / z) * self.cam_model.fy()
        orig_w, orig_h = self.cam_model.width, self.cam_model.height
        send_w, send_h = min(orig_w, self.max_w), min(orig_h, self.max_h)
        point_x = u * send_w / orig_w
        point_y = v * send_h / orig_h
        if not (0 <= point_x < send_w and 0 <= point_y < send_h):
            self.get_logger().warning(
                f"[ClickBridge] クリック点が画像外: "
                f"({point_x:.1f}, {point_y:.1f}) / {send_w}x{send_h}"
            )
            return
        with self.pending_lock:
            self.pending_click = (float(point_x), float(point_y))
        self.get_logger().info(
            f"[ClickBridge] クリック: 3D({x:.2f},{y:.2f},{z:.2f}) -> "
            f"pixel({point_x:.1f},{point_y:.1f})"
        )

    def _image_callback(self, msg):
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
            with self.pending_lock:
                click = self.pending_click
                self.pending_click = None
            if click is None:
                continue
            try:
                self._process_frame(msg, click)
                with self.stats_lock:
                    self.stats["sent"] += 1
            except grpc.RpcError as exc:
                with self.pending_lock:
                    self.pending_click = click
                with self.stats_lock:
                    self.stats["failed"] += 1
                self.get_logger().warning(
                    f"[ClickBridge] gRPC失敗: "
                    f"code={exc.code()} details={exc.details()}"
                )
            except Exception as exc:
                with self.stats_lock:
                    self.stats["failed"] += 1
                self.get_logger().error(f"[ClickBridge] 予期せぬエラー: {exc!r}")

    def _process_frame(self, msg, click):
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
            click_segment_pb2.ImageRequest(
                image=jpeg.tobytes(),
                width=w,
                height=h,
                point_x=click[0],
                point_y=click[1],
            ),
            timeout=self.timeout,
        )
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
            f"[ClickBridge] mask publish {response.width}x{response.height} "
            f"objects={response.num_objects} inference={response.inference_ms:.1f}ms"
        )

    def _log_stats(self):
        with self.stats_lock:
            stats = self.stats.copy()
        self.get_logger().info(
            f"[ClickBridge] 統計 | 受信:{stats['received']} "
            f"破棄:{stats['dropped']} 送信成功:{stats['sent']} "
            f"失敗:{stats['failed']}"
        )

    def destroy_node(self):
        self.shutdown_event.set()
        self.worker_thread.join(timeout=max(1.0, self.timeout + 0.5))
        self.channel.close()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ClickSegmentBridge()
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
