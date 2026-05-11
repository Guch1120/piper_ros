#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "drag_segment"))

import rospy
import threading
import queue

import cv2
import numpy as np
import grpc

from sensor_msgs.msg import Image
from geometry_msgs.msg import Polygon
from cv_bridge import CvBridge

import drag_segment_pb2
import drag_segment_pb2_grpc


class DragSegmentBridge:
    def __init__(self):
        rospy.init_node("drag_segment_bridge", anonymous=True)

        # パラメータ
        host         = rospy.get_param("~grpc_host",    "localhost")
        port         = rospy.get_param("~grpc_port",    50052)
        self.timeout = rospy.get_param("~grpc_timeout", 10.0)
        self.quality = rospy.get_param("~jpeg_quality", 75)
        self.max_w   = rospy.get_param("~max_width",    640)
        self.max_h   = rospy.get_param("~max_height",   480)
        topic        = rospy.get_param(
            "~topic_name",
            "/hsrb/head_rgbd_sensor/rgb/image_rect_color",
        )

        # gRPC
        addr = f"{host}:{port}"
        self.channel = grpc.insecure_channel(addr)
        self.stub = drag_segment_pb2_grpc.DragSegmentServiceStub(self.channel)
        rospy.loginfo(f"[DragBridge] gRPC接続先: {addr}")

        # ROS
        self.bridge = CvBridge()

        # ワンショットフラグ
        self.pending_box = None   # (x1, y1, x2, y2) or None
        self.pending_lock = threading.Lock()

        # Publisher
        self.mask_pub    = rospy.Publisher("/sam/mask",    Image, queue_size=1)
        self.overlay_pub = rospy.Publisher("/sam/overlay", Image, queue_size=1)

        # 統計
        self.stats = {"received": 0, "dropped": 0, "sent": 0, "failed": 0}
        self.stats_lock = threading.Lock()

        # フレームキュー（maxsize=1 で常に最新フレームのみ保持）
        self.frame_queue = queue.Queue(maxsize=1)

        # スレッド起動
        threading.Thread(
            target=self._worker_loop, daemon=True, name="grpc_worker"
        ).start()
        threading.Thread(
            target=self._stats_loop, daemon=True, name="stats_logger"
        ).start()

        # Subscriber
        rospy.Subscriber("/drag_box", Polygon, self._drag_box_callback, queue_size=1)
        rospy.Subscriber(topic, Image, self._image_callback, queue_size=1)

        rospy.loginfo("[DragBridge] 起動完了 - /drag_box を待機中...")

    # =========================================================================
    # ドラッグボックス受信 → ワンショットフラグをセット
    # =========================================================================

    def _drag_box_callback(self, msg):
        x1 = msg.points[0].x
        y1 = msg.points[0].y
        x2 = msg.points[1].x
        y2 = msg.points[1].y

        # リサイズ比率で補正
        # GUIはカメラ画像をそのまま表示しているため補正不要だが
        # 画像がリサイズされている場合は比率を合わせる
        rospy.loginfo(
            f"[DragBridge] bbox受信: ({x1:.0f},{y1:.0f}) → ({x2:.0f},{y2:.0f})"
        )

        with self.pending_lock:
            self.pending_box = (x1, y1, x2 - x1, y2 - y1)  # x,y,w,h 形式

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
        rospy.loginfo("[DragBridge] Workerスレッド起動")
        while not rospy.is_shutdown():
            try:
                msg = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # ワンショットフラグ確認
            with self.pending_lock:
                box = self.pending_box
                self.pending_box = None  # 即クリア

            if box is None:
                continue

            box_x, box_y, box_w, box_h = box

            try:
                cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")

                orig_h, orig_w = cv_image.shape[:2]
                send_w = min(orig_w, self.max_w)
                send_h = min(orig_h, self.max_h)

                if orig_w > self.max_w or orig_h > self.max_h:
                    cv_image = cv2.resize(cv_image, (send_w, send_h))

                # bbox をリサイズ比率で補正
                scale_x = send_w / orig_w
                scale_y = send_h / orig_h
                box_x_scaled = box_x * scale_x
                box_y_scaled = box_y * scale_y
                box_w_scaled = box_w * scale_x
                box_h_scaled = box_h * scale_y

                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
                _, jpeg = cv2.imencode(".jpg", cv_image, encode_param)

                # gRPC 送信（ワンショット）
                response = self.stub.SegmentImage(
                    drag_segment_pb2.ImageRequest(
                        image=jpeg.tobytes(),
                        width=send_w,
                        height=send_h,
                        box_x=box_x_scaled,
                        box_y=box_y_scaled,
                        box_w=box_w_scaled,
                        box_h=box_h_scaled,
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
                    overlay_array = np.frombuffer(
                        response.overlay_image, dtype=np.uint8
                    )
                    overlay_bgr = cv2.imdecode(overlay_array, cv2.IMREAD_COLOR)
                    overlay_msg = self.bridge.cv2_to_imgmsg(
                        overlay_bgr, encoding="bgr8"
                    )
                    overlay_msg.header = msg.header
                    self.overlay_pub.publish(overlay_msg)

                with self.stats_lock:
                    self.stats["sent"] += 1

                rospy.loginfo(
                    f"[DragBridge] /sam/mask publish "
                    f"{response.width}x{response.height} "
                    f"/ {response.num_objects}個検出 "
                    f"/ 推論{response.inference_ms:.1f}ms"
                )

            except grpc.RpcError as e:
                with self.stats_lock:
                    self.stats["failed"] += 1
                rospy.logwarn(f"[DragBridge] gRPC失敗（スキップ）: {e.code()}")
            except Exception as e:
                rospy.logerr(f"[DragBridge] 予期せぬエラー: {e}")

        rospy.loginfo("[DragBridge] Workerスレッド終了")

    # =========================================================================
    # 統計ログ
    # =========================================================================

    def _stats_loop(self):
        while not rospy.is_shutdown():
            rospy.sleep(10.0)
            with self.stats_lock:
                s = self.stats.copy()
            rospy.loginfo(
                f"[DragBridge] 統計 | "
                f"受信:{s['received']} 破棄:{s['dropped']} "
                f"送信成功:{s['sent']} 失敗:{s['failed']}"
            )

    def spin(self):
        rospy.spin()

    def __del__(self):
        self.channel.close()


if __name__ == "__main__":
    bridge = DragSegmentBridge()
    bridge.spin()
