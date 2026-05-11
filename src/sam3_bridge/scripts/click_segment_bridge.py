#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "click_segment"))

import rospy
import threading
import queue

import cv2
import numpy as np
import grpc

from sensor_msgs.msg import Image, CameraInfo
from geometry_msgs.msg import PointStamped
from cv_bridge import CvBridge
from image_geometry import PinholeCameraModel

import tf2_ros
import tf2_geometry_msgs

import click_segment_pb2
import click_segment_pb2_grpc


class ClickSegmentBridge:
    def __init__(self):
        rospy.init_node("click_segment_bridge", anonymous=True)

        # パラメータ
        host         = rospy.get_param("~grpc_host",    "localhost")
        port         = rospy.get_param("~grpc_port",    50051)
        self.timeout = rospy.get_param("~grpc_timeout", 10.0)  # SAM3推論は重いので余裕を持たせる
        self.quality = rospy.get_param("~jpeg_quality", 75)
        self.max_w   = rospy.get_param("~max_width",    640)
        self.max_h   = rospy.get_param("~max_height",   480)
        topic        = rospy.get_param("~topic_name",
                           "/hsrb/head_rgbd_sensor/rgb/image_rect_color")

        # gRPC
        addr = f"{host}:{port}"
        self.channel = grpc.insecure_channel(addr)
        self.stub = click_segment_pb2_grpc.ClickSegmentServiceStub(self.channel)
        rospy.loginfo(f"[ClickBridge] gRPC接続先: {addr}")

        # ROS
        self.bridge = CvBridge()

        # tf2
        self.tf_buffer   = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)

        # カメラモデル（camera_infoから一度だけ構築）
        self.cam_model = PinholeCameraModel()
        self.cam_model_ready = False

        # ワンショットフラグ
        self.pending_click = None   # (point_x, point_y) or None
        self.pending_lock  = threading.Lock()

        # Publisher
        self.mask_pub    = rospy.Publisher("/sam/mask",    Image, queue_size=1)
        self.overlay_pub = rospy.Publisher("/sam/overlay", Image, queue_size=1)

        # 統計
        self.stats = {"received": 0, "dropped": 0, "sent": 0, "failed": 0}
        self.stats_lock = threading.Lock()

        # フレームキュー（既存と同じ maxsize=1 設計）
        self.frame_queue = queue.Queue(maxsize=1)

        # スレッド起動
        threading.Thread(target=self._worker_loop, daemon=True, name="grpc_worker").start()
        threading.Thread(target=self._stats_loop,  daemon=True, name="stats_logger").start()

        # Subscriber
        rospy.Subscriber(
            "/hsrb/head_rgbd_sensor/rgb/camera_info",
            CameraInfo,
            self._camera_info_callback,
            queue_size=1,
        )
        rospy.Subscriber(
            "/clicked_point",
            PointStamped,
            self._clicked_point_callback,
            queue_size=1,
        )
        rospy.Subscriber(topic, Image, self._image_callback, queue_size=1)

        rospy.loginfo("[ClickBridge] 起動完了 - /clicked_point を待機中...")

    # =========================================================================
    # カメラ情報（一度だけ取得）
    # =========================================================================

    def _camera_info_callback(self, msg):
        if not self.cam_model_ready:
            self.cam_model.fromCameraInfo(msg)
            self.cam_model_ready = True
            rospy.loginfo(
                f"[ClickBridge] カメラモデル取得完了 "
                f"{self.cam_model.width}x{self.cam_model.height} "
                f"fx={self.cam_model.fx():.1f} fy={self.cam_model.fy():.1f}"
            )

    # =========================================================================
    # クリック座標受信 → ワンショットフラグをセット
    # =========================================================================

    def _clicked_point_callback(self, msg):
        if not self.cam_model_ready:
            rospy.logwarn("[ClickBridge] camera_info 未取得のためスキップ")
            return

        # ① tf2: クリック点のフレーム → カメラ光学フレームへ変換
        try:
            point_cam = self.tf_buffer.transform(
                msg,
                "head_rgbd_sensor_rgb_frame",
                rospy.Duration(0.5),
            )
        except Exception as e:
            rospy.logwarn(f"[ClickBridge] tf2変換失敗: {e}")
            return

        X = point_cam.point.x
        Y = point_cam.point.y
        Z = point_cam.point.z

        if Z <= 0:
            rospy.logwarn("[ClickBridge] Z <= 0（カメラ後方）のためスキップ")
            return

        # ② ピンホール投影: 3D(X,Y,Z) → 元画像ピクセル(u,v)
        u = self.cam_model.cx() + (X / Z) * self.cam_model.fx()
        v = self.cam_model.cy() + (Y / Z) * self.cam_model.fy()

        # ③ リサイズ補正: 元解像度 → 送信解像度（640×480）
        orig_w = self.cam_model.width
        orig_h = self.cam_model.height
        send_w = min(orig_w, self.max_w)
        send_h = min(orig_h, self.max_h)
        scale_x = send_w / orig_w
        scale_y = send_h / orig_h
        point_x = u * scale_x
        point_y = v * scale_y

        # 画像範囲チェック
        if not (0 <= point_x < send_w and 0 <= point_y < send_h):
            rospy.logwarn(
                f"[ClickBridge] クリック点が画像外: "
                f"({point_x:.1f}, {point_y:.1f}) / {send_w}x{send_h}"
            )
            return

        rospy.loginfo(
            f"[ClickBridge] クリック受信 → "
            f"3D({X:.2f},{Y:.2f},{Z:.2f}) → "
            f"pixel({point_x:.1f},{point_y:.1f})"
        )

        # ワンショットフラグをセット
        with self.pending_lock:
            self.pending_click = (float(point_x), float(point_y))

    # =========================================================================
    # 画像受信（既存と同じ Queue 設計）
    # =========================================================================

    def _image_callback(self, msg):
        with self.stats_lock:
            self.stats["received"] += 1
        try:
            self.frame_queue.get_nowait()
            with self.stats_lock:
                self.stats["dropped"] += 1
        except queue.Empty:
            pass
        self.frame_queue.put(msg)

    # =========================================================================
    # Worker スレッド
    # =========================================================================

    def _worker_loop(self):
        rospy.loginfo("[ClickBridge] Workerスレッド起動")
        while not rospy.is_shutdown():
            try:
                msg = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # ワンショットフラグ確認（クリックがなければ推論しない）
            with self.pending_lock:
                click = self.pending_click
                self.pending_click = None  # 即クリア

            if click is None:
                continue

            point_x, point_y = click

            try:
                cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")

                h, w = cv_image.shape[:2]
                if w > self.max_w or h > self.max_h:
                    cv_image = cv2.resize(cv_image, (self.max_w, self.max_h))
                    h, w = self.max_h, self.max_w

                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
                _, jpeg = cv2.imencode(".jpg", cv_image, encode_param)

                # gRPC 送信（ワンショット）
                response = self.stub.SegmentImage(
                    click_segment_pb2.ImageRequest(
                        image=jpeg.tobytes(),
                        width=w,
                        height=h,
                        point_x=point_x,
                        point_y=point_y,
                    ),
                    timeout=self.timeout,
                )

                # マスク publish
                mask = np.frombuffer(
                    response.mask, dtype=np.uint8
                ).reshape(response.height, response.width)
                mask_vis = (mask * 255).astype(np.uint8)
                mask_msg = self.bridge.cv2_to_imgmsg(mask_vis, encoding="mono8")
                mask_msg.header = msg.header
                self.mask_pub.publish(mask_msg)

                # オーバーレイ publish
                if response.overlay_image:
                    overlay_array = np.frombuffer(response.overlay_image, dtype=np.uint8)
                    overlay_bgr = cv2.imdecode(overlay_array, cv2.IMREAD_COLOR)
                    overlay_msg = self.bridge.cv2_to_imgmsg(overlay_bgr, encoding="bgr8")
                    overlay_msg.header = msg.header
                    self.overlay_pub.publish(overlay_msg)

                with self.stats_lock:
                    self.stats["sent"] += 1

                rospy.loginfo(
                    f"[ClickBridge] /sam/mask publish "
                    f"{response.width}x{response.height} "
                    f"/ {response.num_objects}個検出 "
                    f"/ 推論{response.inference_ms:.1f}ms"
                )

            except grpc.RpcError as e:
                with self.pending_lock:
                    self.pending_click = (point_x, point_y)  # 失敗時はフラグを戻す
                with self.stats_lock:
                    self.stats["failed"] += 1
                rospy.logwarn(f"[ClickBridge] gRPC失敗（スキップ）: {e.code()}")
            except Exception as e:
                rospy.logerr(f"[ClickBridge] 予期せぬエラー: {e}")

        rospy.loginfo("[ClickBridge] Workerスレッド終了")

    # =========================================================================
    # 統計ログ
    # =========================================================================

    def _stats_loop(self):
        while not rospy.is_shutdown():
            rospy.sleep(10.0)
            with self.stats_lock:
                s = self.stats.copy()
            rospy.loginfo(
                f"[ClickBridge] 統計 | "
                f"受信:{s['received']} 破棄:{s['dropped']} "
                f"送信成功:{s['sent']} 失敗:{s['failed']}"
            )

    def spin(self):
        rospy.spin()

    def __del__(self):
        self.channel.close()


if __name__ == "__main__":
    bridge = ClickSegmentBridge()
    bridge.spin()