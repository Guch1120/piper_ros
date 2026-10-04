#!/usr/bin/env python3
import json
import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "drag_segment"))

import cv2
import grpc
import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Polygon
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

import drag_segment_pb2
import drag_segment_pb2_grpc


class DragSegmentBridge(Node):
    def __init__(self):
        super().__init__("drag_segment_bridge")
        defaults = {
            "grpc_host": "localhost",
            "grpc_port": 50052,
            "grpc_timeout": 10.0,
            "jpeg_quality": 75,
            "max_width": 640,
            "max_height": 480,
            "topic_name": "/hsrb/head_rgbd_sensor/rgb/image_rect_color",
            "drag_box_topic": "/drag_box",
            "mask_topic": "/sam/mask",
            "overlay_topic": "/sam/overlay",
            "save_outputs": False,
            "save_dir": "drag_segment_data",
            "save_mask": True,
            "save_overlay": True,
            "save_metadata": True,
            "save_input_image": False,
            "save_prefix": "drag_segment",
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
        self.save_outputs = bool(value("save_outputs"))
        save_dir = os.path.expanduser(str(value("save_dir")))
        if not os.path.isabs(save_dir):
            save_dir = os.path.join(
                os.path.expanduser("~"), ".ros", "sam3_bridge", save_dir
            )
        self.save_dir = save_dir
        self.save_mask = bool(value("save_mask"))
        self.save_overlay = bool(value("save_overlay"))
        self.save_metadata = bool(value("save_metadata"))
        self.save_input_image = bool(value("save_input_image"))
        self.save_prefix = str(value("save_prefix"))

        if self.save_outputs:
            os.makedirs(self.save_dir, exist_ok=True)
            self.get_logger().info(f"[DragBridge] 保存有効: {self.save_dir}")

        addr = f"{host}:{port}"
        self.channel = grpc.insecure_channel(addr)
        self.stub = drag_segment_pb2_grpc.DragSegmentServiceStub(self.channel)
        self.bridge = CvBridge()
        self.pending_box = None
        self.pending_lock = threading.Lock()
        self.save_lock = threading.Lock()
        self.save_count = 0
        self.frame_queue = queue.Queue(maxsize=1)
        self.stats = {"received": 0, "dropped": 0, "sent": 0, "failed": 0}
        self.stats_lock = threading.Lock()
        self.shutdown_event = threading.Event()

        self.mask_pub = self.create_publisher(Image, str(value("mask_topic")), 1)
        self.overlay_pub = self.create_publisher(
            Image, str(value("overlay_topic")), 1
        )
        self.box_sub = self.create_subscription(
            Polygon, str(value("drag_box_topic")), self._drag_box_callback, 1
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
        self.get_logger().info(f"[DragBridge] gRPC接続先: {addr}")
        self.get_logger().info("[DragBridge] 起動完了 - drag boxを待機中")

    def _drag_box_callback(self, msg):
        if len(msg.points) < 2:
            self.get_logger().warning(
                "[DragBridge] drag boxには2点以上が必要です"
            )
            return
        x1, y1 = msg.points[0].x, msg.points[0].y
        x2, y2 = msg.points[1].x, msg.points[1].y
        x_min, x_max = min(x1, x2), max(x1, x2)
        y_min, y_max = min(y1, y2), max(y1, y2)
        if x_max <= x_min or y_max <= y_min:
            self.get_logger().warning("[DragBridge] 空のbboxを無視しました")
            return
        with self.pending_lock:
            self.pending_box = (x_min, y_min, x_max - x_min, y_max - y_min)
        self.get_logger().info(
            f"[DragBridge] bbox受信: ({x_min:.0f},{y_min:.0f}) -> "
            f"({x_max:.0f},{y_max:.0f})"
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
                box = self.pending_box
                self.pending_box = None
            if box is None:
                continue
            try:
                self._process_frame(msg, box)
                with self.stats_lock:
                    self.stats["sent"] += 1
            except grpc.RpcError as exc:
                with self.pending_lock:
                    self.pending_box = box
                with self.stats_lock:
                    self.stats["failed"] += 1
                self.get_logger().warning(
                    f"[DragBridge] gRPC失敗: "
                    f"code={exc.code()} details={exc.details()}"
                )
            except Exception as exc:
                with self.stats_lock:
                    self.stats["failed"] += 1
                self.get_logger().error(f"[DragBridge] 予期せぬエラー: {exc!r}")

    def _process_frame(self, msg, box):
        image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        image = np.ascontiguousarray(image, dtype=np.uint8)
        orig_h, orig_w = image.shape[:2]
        send_w, send_h = min(orig_w, self.max_w), min(orig_h, self.max_h)
        if send_w != orig_w or send_h != orig_h:
            image = cv2.resize(image, (send_w, send_h))

        scale_x, scale_y = send_w / orig_w, send_h / orig_h
        box_x, box_y, box_w, box_h = box
        scaled_box = (
            box_x * scale_x,
            box_y * scale_y,
            box_w * scale_x,
            box_h * scale_y,
        )
        ok, jpeg = cv2.imencode(
            ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
        )
        if not ok:
            raise RuntimeError("JPEG encode failed")
        response = self.stub.SegmentImage(
            drag_segment_pb2.ImageRequest(
                image=jpeg.tobytes(),
                width=send_w,
                height=send_h,
                box_x=scaled_box[0],
                box_y=scaled_box[1],
                box_w=scaled_box[2],
                box_h=scaled_box[3],
            ),
            timeout=self.timeout,
        )
        mask = np.frombuffer(response.mask, dtype=np.uint8).reshape(
            response.height, response.width
        )
        mask_vis = (mask > 0).astype(np.uint8) * 255
        mask_msg = self.bridge.cv2_to_imgmsg(mask_vis, encoding="mono8")
        mask_msg.header = msg.header
        self.mask_pub.publish(mask_msg)

        overlay = None
        if response.overlay_image:
            overlay = cv2.imdecode(
                np.frombuffer(response.overlay_image, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            if overlay is not None:
                overlay_msg = self.bridge.cv2_to_imgmsg(overlay, encoding="bgr8")
                overlay_msg.header = msg.header
                self.overlay_pub.publish(overlay_msg)

        self._save_result(
            mask_vis,
            overlay,
            image,
            msg,
            response,
            scaled_box,
            (orig_w, orig_h),
            (send_w, send_h),
        )
        self.get_logger().info(
            f"[DragBridge] mask publish {response.width}x{response.height} "
            f"objects={response.num_objects} inference={response.inference_ms:.1f}ms"
        )

    def _save_result(
        self, mask, overlay, image, msg, response, box, original_size, sent_size
    ):
        if not self.save_outputs:
            return
        with self.save_lock:
            self.save_count += 1
            index = self.save_count
        stamp = float(msg.header.stamp.sec) + msg.header.stamp.nanosec * 1.0e-9
        if stamp <= 0.0:
            stamp = self.get_clock().now().nanoseconds * 1.0e-9
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(stamp))
        millis = int((stamp - int(stamp)) * 1000.0)
        base = f"{self.save_prefix}_{timestamp}_{millis:03d}_{index:04d}"
        try:
            if self.save_mask:
                cv2.imwrite(os.path.join(self.save_dir, base + "_mask.png"), mask)
            if self.save_overlay and overlay is not None:
                cv2.imwrite(
                    os.path.join(self.save_dir, base + "_overlay.jpg"), overlay
                )
            if self.save_input_image:
                cv2.imwrite(
                    os.path.join(self.save_dir, base + "_input.jpg"), image
                )
            if self.save_metadata:
                metadata = {
                    "stamp": stamp,
                    "bbox_xywh": dict(zip(("x", "y", "w", "h"), map(float, box))),
                    "original_size": {
                        "width": original_size[0],
                        "height": original_size[1],
                    },
                    "sent_size": {"width": sent_size[0], "height": sent_size[1]},
                    "mask_size": {
                        "width": int(response.width),
                        "height": int(response.height),
                    },
                    "num_objects": int(response.num_objects),
                    "inference_ms": float(response.inference_ms),
                }
                with open(
                    os.path.join(self.save_dir, base + "_meta.json"),
                    "w",
                    encoding="utf-8",
                ) as output:
                    json.dump(metadata, output, indent=2, sort_keys=True)
            self.get_logger().info(f"[DragBridge] 保存完了: {base}")
        except Exception as exc:
            self.get_logger().warning(f"[DragBridge] 保存失敗: {exc}")

    def _log_stats(self):
        with self.stats_lock:
            stats = self.stats.copy()
        self.get_logger().info(
            f"[DragBridge] 統計 | 受信:{stats['received']} "
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
    node = DragSegmentBridge()
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
