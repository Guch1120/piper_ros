#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading
import queue

import cv2
import grpc
import numpy as np

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

from sensor_msgs.msg import Image
from cv_bridge import CvBridge

import segment_overlay_pb2 as segment_pb2
import segment_overlay_pb2_grpc as segment_pb2_grpc


class ROSToGRPCBridge(Node):
    """
    ROS2 Humble用 gRPC Bridge ノード。

    入力:
        sensor_msgs/Image

    出力:
        /sam/mask    sensor_msgs/Image mono8
        /sam/overlay sensor_msgs/Image bgr8

    処理:
        画像トピックを購読
        OpenCV画像に変換
        JPEG圧縮
        gRPCサーバへ送信
        返ってきたmask/overlayをROS2 topicへpublish
    """

    def __init__(self):
        super().__init__("grpc_bridge")

        # -----------------------------
        # ROS2 parameters
        # -----------------------------
        self.declare_parameter("grpc_host", "localhost")
        self.declare_parameter("grpc_port", 50051)
        self.declare_parameter("grpc_timeout", 2.0)
        self.declare_parameter("jpeg_quality", 75)
        self.declare_parameter("max_width", 640)
        self.declare_parameter("max_height", 480)
        self.declare_parameter("prompt", "person")
        self.declare_parameter(
            "topic_name",
            "/hsrb/head_rgbd_sensor/rgb/image_rect_color"
        )
        self.declare_parameter("mask_topic", "/sam/mask")
        self.declare_parameter("overlay_topic", "/sam/overlay")

        host = self.get_parameter("grpc_host").value
        port = self.get_parameter("grpc_port").value
        self.timeout = float(self.get_parameter("grpc_timeout").value)
        self.quality = int(self.get_parameter("jpeg_quality").value)
        self.max_w = int(self.get_parameter("max_width").value)
        self.max_h = int(self.get_parameter("max_height").value)
        self.prompt = str(self.get_parameter("prompt").value)

        topic_name = self.get_parameter("topic_name").value
        mask_topic = self.get_parameter("mask_topic").value
        overlay_topic = self.get_parameter("overlay_topic").value

        # -----------------------------
        # gRPC client
        # -----------------------------
        addr = f"{host}:{port}"
        self.channel = grpc.insecure_channel(addr)
        self.stub = segment_pb2_grpc.SegmentServiceStub(self.channel)

        self.get_logger().info(f"[Bridge] gRPC接続先: {addr}")

        # -----------------------------
        # ROS2 publishers/subscriber
        # -----------------------------
        self.bridge = CvBridge()

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )

        self.mask_pub = self.create_publisher(Image, mask_topic, qos)
        self.overlay_pub = self.create_publisher(Image, overlay_topic, qos)

        self.image_sub = self.create_subscription(
            Image,
            topic_name,
            self.callback,
            qos
        )

        # -----------------------------
        # Queue / stats
        # -----------------------------
        self.frame_queue = queue.Queue(maxsize=1)

        self.stats = {
            "received": 0,
            "dropped": 0,
            "sent": 0,
            "failed": 0,
        }
        self.stats_lock = threading.Lock()

        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="grpc_worker"
        )
        self.worker_thread.start()

        self.stats_thread = threading.Thread(
            target=self._stats_loop,
            daemon=True,
            name="stats_logger"
        )
        self.stats_thread.start()

        self.get_logger().info(f"[Bridge] 起動完了 - {topic_name} を待機中...")
        self.get_logger().info(f"[Bridge] マスクpublish先: {mask_topic}")
        self.get_logger().info(f"[Bridge] オーバーレイpublish先: {overlay_topic}")

    def callback(self, msg: Image):
        """
        画像購読コールバック。

        最新フレームだけを処理するため、キューに古い画像が残っていれば破棄する。
        """
        with self.stats_lock:
            self.stats["received"] += 1

        try:
            self.frame_queue.get_nowait()
            with self.stats_lock:
                self.stats["dropped"] += 1
        except queue.Empty:
            pass

        self.frame_queue.put(msg)

    def _worker_loop(self):
        """
        gRPC送信用ワーカースレッド。

        ROSコールバック側では重い処理をせず、ここで画像変換・JPEG圧縮・gRPC通信を行う。
        """
        self.get_logger().info("[Bridge] Workerスレッド起動")

        while rclpy.ok():
            try:
                msg = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                cv_image = self.bridge.imgmsg_to_cv2(
                    msg,
                    desired_encoding="bgr8"
                )

                h, w = cv_image.shape[:2]

                # 最大サイズを超える場合は縮小
                if w > self.max_w or h > self.max_h:
                    cv_image = cv2.resize(cv_image, (self.max_w, self.max_h))
                    h, w = self.max_h, self.max_w

                encode_param = [
                    int(cv2.IMWRITE_JPEG_QUALITY),
                    self.quality
                ]

                success, jpeg = cv2.imencode(".jpg", cv_image, encode_param)
                if not success:
                    raise RuntimeError("JPEG encode failed")

                response = self.stub.SegmentImage(
                    segment_pb2.ImageRequest(
                        image=jpeg.tobytes(),
                        width=w,
                        height=h,
                        prompt=self.prompt,
                    ),
                    timeout=self.timeout
                )

                # -----------------------------
                # mask publish
                # -----------------------------
                mask = np.frombuffer(
                    response.mask,
                    dtype=np.uint8
                ).reshape(response.height, response.width)

                mask_vis = (mask * 255).astype(np.uint8)

                mask_msg = self.bridge.cv2_to_imgmsg(
                    mask_vis,
                    encoding="mono8"
                )
                mask_msg.header = msg.header
                self.mask_pub.publish(mask_msg)

                # -----------------------------
                # overlay publish
                # -----------------------------
                if response.overlay_image:
                    overlay_array = np.frombuffer(
                        response.overlay_image,
                        dtype=np.uint8
                    )

                    overlay_bgr = cv2.imdecode(
                        overlay_array,
                        cv2.IMREAD_COLOR
                    )

                    if overlay_bgr is not None:
                        overlay_msg = self.bridge.cv2_to_imgmsg(
                            overlay_bgr,
                            encoding="bgr8"
                        )
                        overlay_msg.header = msg.header
                        self.overlay_pub.publish(overlay_msg)

                with self.stats_lock:
                    self.stats["sent"] += 1

                self.get_logger().info(
                    "[Bridge] /sam/mask publish "
                    f"{response.width}x{response.height} "
                    f"/ {response.num_objects}個検出 "
                    f"/ 推論{response.inference_ms:.1f}ms"
                )

            except grpc.RpcError as e:
                with self.stats_lock:
                    self.stats["failed"] += 1

                self.get_logger().warn(
                    f"[Bridge] gRPC失敗（スキップ）: {e.code()}"
                )

            except Exception as e:
                with self.stats_lock:
                    self.stats["failed"] += 1

                self.get_logger().error(
                    f"[Bridge] 予期せぬエラー: {repr(e)}"
                )

        self.get_logger().info("[Bridge] Workerスレッド終了")

    def _stats_loop(self):
        """
        10秒ごとに統計情報を表示する。
        """
        while rclpy.ok():
            # rospy.sleep の代わり
            for _ in range(100):
                if not rclpy.ok():
                    return
                threading.Event().wait(0.1)

            with self.stats_lock:
                s = self.stats.copy()

            self.get_logger().info(
                "[Bridge] 統計 | "
                f"受信:{s['received']} "
                f"破棄:{s['dropped']} "
                f"送信成功:{s['sent']} "
                f"失敗:{s['failed']}"
            )

    def destroy_node(self):
        """
        ノード終了時にgRPC channelを閉じる。
        """
        try:
            self.channel.close()
        except Exception:
            pass

        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)

    node = ROSToGRPCBridge()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()