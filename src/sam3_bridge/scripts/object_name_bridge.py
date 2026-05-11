#!/usr/bin/env python3
import rospy
from geometry_msgs.msg import PointStamped
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, String
from cv_bridge import CvBridge
import cv2
import numpy as np
import grpc
import threading
import queue
import segment_overlay_pb2 as segment_pb2
import segment_overlay_pb2_grpc as segment_pb2_grpc


class ObjectNameBridge:
    def __init__(self):
        rospy.init_node("object_name_bridge", anonymous=True)

        # launchパラメータ
        host         = rospy.get_param("~grpc_host",      "localhost")
        port         = rospy.get_param("~grpc_port",      50051)
        self.timeout = rospy.get_param("~grpc_timeout",   2.0)
        self.quality = rospy.get_param("~jpeg_quality",   75)
        self.max_w   = rospy.get_param("~max_width",      640)
        self.max_h   = rospy.get_param("~max_height",     480)
        default_head_topic = rospy.get_param(
            "~topic_name", "/hsrb/head_rgbd_sensor/rgb/image_rect_color"
        )
        self.head_topic = rospy.get_param("~head_topic", default_head_topic)
        self.hand_topic = rospy.get_param(
            "~hand_topic", "/hsrb/hand_camera/image_raw"
        )
        self.switch_topic = rospy.get_param("~switch_topic", "/sam3/switch")
        self.head_mask_topic = rospy.get_param("~head_mask_topic", "/sam/mask")
        self.head_overlay_topic = rospy.get_param(
            "~head_overlay_topic", "/sam/overlay"
        )
        self.head_centroid_topic = rospy.get_param(
            "~head_centroid_topic", "/sam3/mask/centroid"
        )
        self.hand_mask_topic = rospy.get_param(
            "~hand_mask_topic", "/sam3/hand/mask"
        )
        self.hand_overlay_topic = rospy.get_param(
            "~hand_overlay_topic", "/sam3/hand/overlay"
        )
        self.hand_centroid_topic = rospy.get_param(
            "~hand_centroid_topic", "/sam3/hand/mask/centroid"
        )
        self.active_source = "head"
        self.source_lock = threading.Lock()

        # promptの初期値
        self.prompt      = rospy.get_param("~default_prompt", "object")
        self.prompt_lock = threading.Lock()
        rospy.loginfo(f"[ObjectNameBridge] 初期prompt: '{self.prompt}'")

        # gRPC初期化
        addr = f"{host}:{port}"
        self.channel = grpc.insecure_channel(addr)
        self.stub = segment_pb2_grpc.SegmentServiceStub(self.channel)
        rospy.loginfo(f"[ObjectNameBridge] gRPC接続先: {addr}")

        self.bridge = CvBridge()

        # Publisher
        self.publishers = {
            "head": {
                "mask": rospy.Publisher(
                    self.head_mask_topic, Image, queue_size=1
                ),
                "overlay": rospy.Publisher(
                    self.head_overlay_topic, Image, queue_size=1
                ),
                "centroid": rospy.Publisher(
                    self.head_centroid_topic, PointStamped, queue_size=1
                ),
            },
            "hand": {
                "mask": rospy.Publisher(
                    self.hand_mask_topic, Image, queue_size=1
                ),
                "overlay": rospy.Publisher(
                    self.hand_overlay_topic, Image, queue_size=1
                ),
                "centroid": rospy.Publisher(
                    self.hand_centroid_topic, PointStamped, queue_size=1
                ),
            },
        }

        # Queue（サイズ1：常に最新フレームのみ保持）
        self.frame_queue = queue.Queue(maxsize=1)

        # 統計情報
        self.stats = {"received": 0, "dropped": 0, "sent": 0, "failed": 0}
        self.stats_lock = threading.Lock()

        # スレッド起動
        threading.Thread(
            target=self._worker_loop, daemon=True, name="grpc_worker"
        ).start()
        threading.Thread(
            target=self._stats_loop, daemon=True, name="stats_logger"
        ).start()

        # /object_name をsubscribe（prompt動的更新）
        rospy.Subscriber(
            "/object_name", String, self.object_name_callback, queue_size=1
        )

        # カメラと入力切り替えをsubscribe
        rospy.Subscriber(
            self.head_topic, Image, self.camera_callback, callback_args="head",
            queue_size=1
        )
        rospy.Subscriber(
            self.hand_topic, Image, self.camera_callback, callback_args="hand",
            queue_size=1
        )
        rospy.Subscriber(
            self.switch_topic, Bool, self.switch_callback, queue_size=1
        )

        rospy.loginfo(f"[ObjectNameBridge] 起動完了")
        rospy.loginfo(f"[ObjectNameBridge] headカメラ: {self.head_topic}")
        rospy.loginfo(f"[ObjectNameBridge] handカメラ: {self.hand_topic}")
        rospy.loginfo(
            f"[ObjectNameBridge] head出力: "
            f"{self.head_mask_topic}, {self.head_overlay_topic}, "
            f"{self.head_centroid_topic}"
        )
        rospy.loginfo(
            f"[ObjectNameBridge] hand出力: "
            f"{self.hand_mask_topic}, {self.hand_overlay_topic}, "
            f"{self.hand_centroid_topic}"
        )
        rospy.loginfo(
            f"[ObjectNameBridge] 入力切替: {self.switch_topic} "
            f"(False=head, True=hand, default=head)"
        )
        rospy.loginfo(f"[ObjectNameBridge] object_name: /object_name を待機中...")

    # =========================================================
    # object_name callback：promptを動的に更新
    # =========================================================
    def object_name_callback(self, msg):
        new_prompt = msg.data.strip()
        if not new_prompt:
            rospy.logwarn("[ObjectNameBridge] 空のobject_nameを受信 → 無視")
            return

        with self.prompt_lock:
            old_prompt = self.prompt
            self.prompt = new_prompt

        if old_prompt != new_prompt:
            rospy.loginfo(
                f"[ObjectNameBridge] prompt更新: '{old_prompt}' → '{new_prompt}'"
            )
            # Queueをリセットして即反映
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass

    # =========================================================
    # switch callback：推論に使うカメラを切り替え
    # =========================================================
    def switch_callback(self, msg):
        new_source = "hand" if msg.data else "head"
        with self.source_lock:
            old_source = self.active_source
            self.active_source = new_source

        if old_source != new_source:
            self._clear_frame_queue()
            rospy.loginfo(
                f"[ObjectNameBridge] 入力切替: {old_source} → {new_source}"
            )

    # =========================================================
    # カメラcallback：フレームをQueueに投入するだけ
    # =========================================================
    def camera_callback(self, msg, source):
        with self.source_lock:
            if source != self.active_source:
                return

        with self.stats_lock:
            self.stats["received"] += 1
        try:
            self.frame_queue.get_nowait()
            with self.stats_lock:
                self.stats["dropped"] += 1
        except queue.Empty:
            pass
        self.frame_queue.put((source, msg))

    def _clear_frame_queue(self):
        while True:
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break

    # =========================================================
    # Workerスレッド：gRPC通信・推論処理
    # =========================================================
    def _worker_loop(self):
        rospy.loginfo("[ObjectNameBridge] Workerスレッド起動")

        while not rospy.is_shutdown():
            try:
                source, msg = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                # ROS Image → OpenCV
                cv_image = self.bridge.imgmsg_to_cv2(
                    msg, desired_encoding="bgr8"
                )

                # リサイズ
                h, w = cv_image.shape[:2]
                if w > self.max_w or h > self.max_h:
                    cv_image = cv2.resize(cv_image, (self.max_w, self.max_h))
                    h, w = self.max_h, self.max_w

                # JPEG圧縮
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
                _, jpeg = cv2.imencode(".jpg", cv_image, encode_param)

                # 現在のpromptを取得（スレッドセーフ）
                with self.prompt_lock:
                    current_prompt = self.prompt

                # gRPC送信
                response = self.stub.SegmentImage(
                    segment_pb2.ImageRequest(
                        image=jpeg.tobytes(),
                        width=w,
                        height=h,
                        prompt=current_prompt,
                    ),
                    timeout=self.timeout
                )

                # マスク復元・publish
                mask = np.frombuffer(
                    response.mask, dtype=np.uint8
                ).reshape(response.height, response.width)

                mask_vis = (mask * 255).astype(np.uint8)
                mask_msg = self.bridge.cv2_to_imgmsg(
                    mask_vis, encoding="mono8"
                )
                mask_msg.header = msg.header
                self.publishers[source]["mask"].publish(mask_msg)

                centroid_msg = self._create_centroid_msg(mask, msg.header)
                if centroid_msg is not None:
                    self.publishers[source]["centroid"].publish(centroid_msg)

                # オーバーレイpublish
                if response.overlay_image:
                    overlay_array = np.frombuffer(
                        response.overlay_image, dtype=np.uint8
                    )
                    overlay_bgr = cv2.imdecode(
                        overlay_array, cv2.IMREAD_COLOR
                    )
                    overlay_msg = self.bridge.cv2_to_imgmsg(
                        overlay_bgr, encoding="bgr8"
                    )
                    overlay_msg.header = msg.header
                    self.publishers[source]["overlay"].publish(overlay_msg)

                with self.stats_lock:
                    self.stats["sent"] += 1

                rospy.loginfo(
                    f"[ObjectNameBridge] publish "
                    f"source='{source}' "
                    f"prompt='{current_prompt}' "
                    f"/ {response.num_objects}個検出 "
                    f"/ {response.inference_ms:.1f}ms"
                )

            except grpc.RpcError as e:
                with self.stats_lock:
                    self.stats["failed"] += 1
                rospy.logwarn(
                    f"[ObjectNameBridge] gRPC失敗（スキップ）: {e.code()}"
                )
            except Exception as e:
                rospy.logerr(f"[ObjectNameBridge] 予期せぬエラー: {e}")

        rospy.loginfo("[ObjectNameBridge] Workerスレッド終了")

    def _create_centroid_msg(self, mask, header):
        ys, xs = np.nonzero(mask > 0)
        if xs.size == 0:
            return None

        centroid_msg = PointStamped()
        centroid_msg.header = header
        centroid_msg.point.x = float(xs.mean())
        centroid_msg.point.y = float(ys.mean())
        centroid_msg.point.z = 0.0
        return centroid_msg

    # =========================================================
    # 統計ログ
    # =========================================================
    def _stats_loop(self):
        while not rospy.is_shutdown():
            rospy.sleep(10.0)
            with self.stats_lock:
                s = self.stats.copy()
            rospy.loginfo(
                f"[ObjectNameBridge] 統計 | "
                f"受信:{s['received']} 破棄:{s['dropped']} "
                f"送信成功:{s['sent']} 失敗:{s['failed']}"
            )

    def spin(self):
        rospy.spin()

    def __del__(self):
        self.channel.close()


if __name__ == "__main__":
    bridge = ObjectNameBridge()
    bridge.spin()
