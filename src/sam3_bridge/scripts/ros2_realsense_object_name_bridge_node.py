#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import cv2
import grpc
import queue
import threading
import numpy as np

import rclpy
from rclpy.node import Node

from std_msgs.msg import String
from sensor_msgs.msg import Image
from geometry_msgs.msg import PointStamped
from cv_bridge import CvBridge

from ament_index_python.packages import get_package_share_directory


# ============================================================
# gRPC protobuf import
#
# install(PROGRAMS ...) でこのノードだけ lib/sam3_bridge に入れる場合、
# segment_overlay_pb2.py などは share/sam3_bridge/scripts に残ることが多い。
# そのため、パッケージshare配下の scripts を import path に追加する。
# ============================================================
try:
    package_share_dir = get_package_share_directory("sam3_bridge")
    scripts_dir = os.path.join(package_share_dir, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
except Exception:
    # 開発中にソース直下から直接実行する場合の保険
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

import segment_overlay_pb2 as segment_pb2
import segment_overlay_pb2_grpc as segment_pb2_grpc


class Ros2RealSenseObjectNameBridge(Node):
    def __init__(self):
        super().__init__("ros2_realsense_object_name_bridge")

        # ====================================================
        # Parameters
        # ====================================================
        self.declare_parameter("grpc_host", "localhost")
        self.declare_parameter("grpc_port", 50051)
        self.declare_parameter("grpc_timeout", 2.0)
        self.declare_parameter("jpeg_quality", 75)
        self.declare_parameter("max_width", 640)
        self.declare_parameter("max_height", 480)

        # 元launchに合わせて topic_name を採用
        self.declare_parameter("topic_name", "/camera/camera/color/image_raw")

        self.declare_parameter("mask_topic", "/sam/mask")
        self.declare_parameter("overlay_topic", "/sam/overlay")
        self.declare_parameter("centroid_topic", "/sam3/mask/centroid")

        # 元launchに合わせて prompt を採用
        self.declare_parameter("prompt", "object")

        # 出力mask/overlayを入力画像サイズへ戻すか
        # TrueならRealSense画像とmask画像の解像度が揃いやすい
        self.declare_parameter("publish_original_size", True)

        host = self.get_parameter("grpc_host").value
        port = int(self.get_parameter("grpc_port").value)

        self.timeout = float(self.get_parameter("grpc_timeout").value)
        self.quality = int(self.get_parameter("jpeg_quality").value)
        self.max_w = int(self.get_parameter("max_width").value)
        self.max_h = int(self.get_parameter("max_height").value)

        self.image_topic = self.get_parameter("topic_name").value
        self.mask_topic = self.get_parameter("mask_topic").value
        self.overlay_topic = self.get_parameter("overlay_topic").value
        self.centroid_topic = self.get_parameter("centroid_topic").value
        self.publish_original_size = bool(
            self.get_parameter("publish_original_size").value
        )

        self.prompt = self.get_parameter("prompt").value
        self.prompt_lock = threading.Lock()

        # ====================================================
        # gRPC
        # ====================================================
        addr = f"{host}:{port}"
        self.channel = grpc.insecure_channel(addr)
        self.stub = segment_pb2_grpc.SegmentServiceStub(self.channel)

        # ====================================================
        # ROS interfaces
        # ====================================================
        self.bridge = CvBridge()

        self.mask_pub = self.create_publisher(Image, self.mask_topic, 10)
        self.overlay_pub = self.create_publisher(Image, self.overlay_topic, 10)
        self.centroid_pub = self.create_publisher(
            PointStamped,
            self.centroid_topic,
            10
        )

        self.image_sub = self.create_subscription(
            Image,
            self.image_topic,
            self.image_callback,
            10
        )

        self.object_name_sub = self.create_subscription(
            String,
            "/object_name",
            self.object_name_callback,
            10
        )

        # Queue: 常に最新フレームだけ保持
        self.frame_queue = queue.Queue(maxsize=1)

        self.stats = {
            "received": 0,
            "dropped": 0,
            "sent": 0,
            "failed": 0,
        }
        self.stats_lock = threading.Lock()

        self.shutdown_event = threading.Event()

        self.worker_thread = threading.Thread(
            target=self.worker_loop,
            daemon=True,
            name="grpc_worker"
        )
        self.worker_thread.start()

        self.stats_timer = self.create_timer(10.0, self.stats_callback)

        self.get_logger().info("[ROS2 RealSense ObjectNameBridge] 起動完了")
        self.get_logger().info(f"gRPC接続先: {addr}")
        self.get_logger().info(f"入力画像topic: {self.image_topic}")
        self.get_logger().info(f"mask出力topic: {self.mask_topic}")
        self.get_logger().info(f"overlay出力topic: {self.overlay_topic}")
        self.get_logger().info(f"centroid出力topic: {self.centroid_topic}")
        self.get_logger().info(f"初期prompt: '{self.prompt}'")
        self.get_logger().info("prompt更新: /object_name std_msgs/String を購読")

    # ========================================================
    # /object_name callback
    # ========================================================
    def object_name_callback(self, msg: String):
        new_prompt = msg.data.strip()

        if not new_prompt:
            self.get_logger().warn("空の /object_name を受信したため無視")
            return

        with self.prompt_lock:
            old_prompt = self.prompt
            self.prompt = new_prompt

        if old_prompt != new_prompt:
            self.clear_frame_queue()
            self.get_logger().info(
                f"prompt更新: '{old_prompt}' -> '{new_prompt}'"
            )

    # ========================================================
    # Image callback
    # ========================================================
    def image_callback(self, msg: Image):
        with self.stats_lock:
            self.stats["received"] += 1

        # 古いフレームを捨てて最新だけ保持
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

    def clear_frame_queue(self):
        while True:
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break

    # ========================================================
    # Worker thread
    # ========================================================
    def worker_loop(self):
        self.get_logger().info("gRPC worker thread started")

        while rclpy.ok() and not self.shutdown_event.is_set():
            try:
                msg = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                self.process_frame(msg)

            except grpc.RpcError as e:
                with self.stats_lock:
                    self.stats["failed"] += 1

                self.get_logger().warn(
                    f"gRPC失敗: code={e.code()} details={e.details()}"
                )

            except Exception as e:
                with self.stats_lock:
                    self.stats["failed"] += 1

                self.get_logger().error(f"予期せぬエラー: {repr(e)}")

        self.get_logger().info("gRPC worker thread stopped")

    def process_frame(self, msg: Image):
        # ROS Image -> OpenCV BGR
        cv_image = self.bridge.imgmsg_to_cv2(
            msg,
            desired_encoding="bgr8"
        )

        # OpenCVが確実に扱える ndarray に正規化
        cv_image = np.asarray(cv_image)

        if cv_image.dtype != np.uint8:
            cv_image = cv_image.astype(np.uint8)

        cv_image = np.ascontiguousarray(cv_image)

        if cv_image.ndim != 3 or cv_image.shape[2] != 3:
            raise RuntimeError(
                f"cv_image must be HxWx3 uint8 image, "
                f"shape={cv_image.shape}, dtype={cv_image.dtype}"
            )

        orig_h, orig_w = cv_image.shape[:2]

        # SAM3/gRPCへ送る画像を必要に応じて縮小
        send_image, scale_x, scale_y = self.resize_for_inference(cv_image)

        # OpenCV imencode が確実に扱える配列に整形
        send_image = np.asarray(send_image)

        if send_image.dtype != np.uint8:
            send_image = send_image.astype(np.uint8)

        send_image = np.ascontiguousarray(send_image)

        if send_image.ndim != 3 or send_image.shape[2] != 3:
            raise RuntimeError(
                f"send_image must be HxWx3 uint8 image, "
                f"shape={send_image.shape}, dtype={send_image.dtype}"
            )

        send_h, send_w = send_image.shape[:2]

        # デバッグ用。動作確認後はコメントアウト推奨。
        # self.get_logger().info(
        #     f"type(send_image)={type(send_image)} "
        #     f"dtype={send_image.dtype} "
        #     f"shape={send_image.shape} "
        #     f"contiguous={send_image.flags['C_CONTIGUOUS']}"
        # )

        # まずは切り分け優先で2引数版
        ok, jpeg = cv2.imencode(".jpg", send_image)

        # 品質指定を使うなら、安定後にこちらへ戻す
        # encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
        # ok, jpeg = cv2.imencode(".jpg", send_image, encode_param)

        if not ok:
            raise RuntimeError("cv2.imencode('.jpg', image) failed")

        with self.prompt_lock:
            current_prompt = self.prompt

        response = self.stub.SegmentImage(
            segment_pb2.ImageRequest(
                image=jpeg.tobytes(),
                width=send_w,
                height=send_h,
                prompt=current_prompt,
            ),
            timeout=self.timeout
        )

        # response.mask は 0/1 想定
        mask = np.frombuffer(response.mask, dtype=np.uint8).reshape(
            response.height,
            response.width
        )

        # 入力画像サイズへ戻す
        if self.publish_original_size and (
            response.width != orig_w or response.height != orig_h
        ):
            mask_for_pub = cv2.resize(
                mask,
                (orig_w, orig_h),
                interpolation=cv2.INTER_NEAREST
            )
        else:
            mask_for_pub = mask

        mask_vis = (mask_for_pub > 0).astype(np.uint8) * 255

        mask_msg = self.bridge.cv2_to_imgmsg(mask_vis, encoding="mono8")
        mask_msg.header = msg.header
        self.mask_pub.publish(mask_msg)

        centroid_msg = self.create_centroid_msg(mask_for_pub, msg.header)
        if centroid_msg is not None:
            self.centroid_pub.publish(centroid_msg)

        if response.overlay_image:
            overlay_array = np.frombuffer(
                response.overlay_image,
                dtype=np.uint8
            )
            overlay_bgr = cv2.imdecode(overlay_array, cv2.IMREAD_COLOR)

            if overlay_bgr is not None:
                if self.publish_original_size and (
                    overlay_bgr.shape[1] != orig_w or overlay_bgr.shape[0] != orig_h
                ):
                    overlay_bgr = cv2.resize(
                        overlay_bgr,
                        (orig_w, orig_h),
                        interpolation=cv2.INTER_LINEAR
                    )

                overlay_msg = self.bridge.cv2_to_imgmsg(
                    overlay_bgr,
                    encoding="bgr8"
                )
                overlay_msg.header = msg.header
                self.overlay_pub.publish(overlay_msg)

        with self.stats_lock:
            self.stats["sent"] += 1

        self.get_logger().info(
            f"publish prompt='{current_prompt}' "
            f"objects={response.num_objects} "
            f"inference={response.inference_ms:.1f}ms "
            # f"image={orig_w}x{orig_h} send={send_w}x{send_h}"
        )
    def resize_for_inference(self, cv_image):
        h, w = cv_image.shape[:2]

        if w <= self.max_w and h <= self.max_h:
            return cv_image, 1.0, 1.0

        scale = min(self.max_w / float(w), self.max_h / float(h))
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))

        resized = cv2.resize(
            cv_image,
            (new_w, new_h),
            interpolation=cv2.INTER_AREA
        )

        scale_x = new_w / float(w)
        scale_y = new_h / float(h)

        return resized, scale_x, scale_y

    def create_centroid_msg(self, mask, header):
        ys, xs = np.nonzero(mask > 0)

        if xs.size == 0:
            return None

        centroid_msg = PointStamped()
        centroid_msg.header = header
        centroid_msg.point.x = float(xs.mean())
        centroid_msg.point.y = float(ys.mean())
        centroid_msg.point.z = 0.0

        return centroid_msg

    # ========================================================
    # Stats
    # ========================================================
    def stats_callback(self):
        with self.stats_lock:
            s = self.stats.copy()

        self.get_logger().info(
            f"統計 | 受信:{s['received']} "
            f"破棄:{s['dropped']} "
            f"送信成功:{s['sent']} "
            f"失敗:{s['failed']}"
        )

    def destroy_node(self):
        self.shutdown_event.set()

        try:
            self.channel.close()
        except Exception:
            pass

        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)

    node = Ros2RealSenseObjectNameBridge()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()