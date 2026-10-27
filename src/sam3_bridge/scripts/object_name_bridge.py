#!/usr/bin/env python3
import csv
import datetime
import os
import queue
import threading
import time

import cv2
import grpc
import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import PointStamped
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.exceptions import ParameterUninitializedException
from rclpy.executors import ExternalShutdownException
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, String

import segment_overlay_pb2 as segment_pb2
import segment_overlay_pb2_grpc as segment_pb2_grpc
from sam3_bridge.msg import Sam3Object, Sam3ObjectArray, StringArray


class ObjectNameBridge(Node):
    def __init__(self):
        super().__init__("object_name_bridge")
        self._declare_parameters()

        host = str(self._param("grpc_host"))
        port = int(self._param("grpc_port"))
        self.timeout = float(self._param("grpc_timeout"))
        self.quality = int(self._param("jpeg_quality"))
        self.max_w = int(self._param("max_width"))
        self.max_h = int(self._param("max_height"))
        self.max_in_flight = max(1, int(self._param("max_in_flight")))
        self.publish_original_size = bool(self._param("publish_original_size"))
        self._open_timing_log(
            bool(self._param("timing_log")), str(self._param("timing_log_dir"))
        )

        legacy_head_topic = str(self._param("topic_name"))
        self.head_topic = str(self._param("head_topic")) or legacy_head_topic
        self.hand_topic = str(self._param("hand_topic"))
        self.switch_topic = str(self._param("switch_topic"))
        self.object_name_topic = str(self._param("object_name_topic"))
        self.prompts_topic = str(self._param("prompts_topic"))

        self.head_mask_topic = str(self._param("head_mask_topic"))
        self.head_overlay_topic = str(self._param("head_overlay_topic"))
        self.head_centroid_topic = str(self._param("head_centroid_topic"))
        self.head_object_list_topic = str(self._param("head_object_list_topic"))
        self.hand_mask_topic = str(self._param("hand_mask_topic"))
        self.hand_overlay_topic = str(self._param("hand_overlay_topic"))
        self.hand_centroid_topic = str(self._param("hand_centroid_topic"))
        self.hand_object_list_topic = str(self._param("hand_object_list_topic"))

        self.active_source = "head"
        self.source_lock = threading.Lock()

        default_prompt = str(self._param("default_prompt"))
        self.prompts = self._normalize_prompts(self._param("default_prompts"))
        if not self.prompts:
            self.prompts = self._normalize_prompts([default_prompt]) or ["object"]
        self.prompt_lock = threading.Lock()

        self.reset_tracking_next = True
        self.reset_lock = threading.Lock()

        addr = f"{host}:{port}"
        self.channel = grpc.insecure_channel(addr)
        self.stub = segment_pb2_grpc.SegmentServiceStub(self.channel)
        self.bridge = CvBridge()

        self.publishers_by_source = {
            "head": self._create_source_publishers(
                self.head_mask_topic,
                self.head_overlay_topic,
                self.head_centroid_topic,
                self.head_object_list_topic,
            ),
            "hand": self._create_source_publishers(
                self.hand_mask_topic,
                self.hand_overlay_topic,
                self.hand_centroid_topic,
                self.hand_object_list_topic,
            ),
        }

        self.frame_queue = queue.Queue(maxsize=1)
        self.stats = {
            "received": 0, "dropped": 0, "sent": 0, "failed": 0, "stale": 0
        }
        self.stats_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        # 複数リクエストを並行させると応答順が入れ替わり得るため、
        # sourceごとに最後にpublishしたフレームより古い結果は捨てる。
        self.publish_lock = threading.Lock()
        self.last_published_stamp = {}

        self.object_name_sub = self.create_subscription(
            String, self.object_name_topic, self.object_name_callback, 1
        )
        self.prompts_sub = self.create_subscription(
            StringArray, self.prompts_topic, self.prompts_callback, 1
        )
        self.head_sub = self.create_subscription(
            Image,
            self.head_topic,
            lambda msg: self.camera_callback(msg, "head"),
            qos_profile_sensor_data,
        )
        self.hand_sub = self.create_subscription(
            Image,
            self.hand_topic,
            lambda msg: self.camera_callback(msg, "hand"),
            qos_profile_sensor_data,
        )
        self.switch_sub = self.create_subscription(
            Bool, self.switch_topic, self.switch_callback, 1
        )

        # SAM3推論中に次フレームを送れるよう、max_in_flight本のworkerで並行して投げる。
        self.worker_threads = [
            threading.Thread(
                target=self._worker_loop, daemon=True, name=f"grpc_worker_{i}"
            )
            for i in range(self.max_in_flight)
        ]
        for worker_thread in self.worker_threads:
            worker_thread.start()
        self.stats_timer = self.create_timer(10.0, self._log_stats)

        logger = self.get_logger()
        logger.info(f"[ObjectNameBridge] gRPC接続先: {addr}")
        logger.info(f"[ObjectNameBridge] 同時リクエスト数: {self.max_in_flight}")
        logger.info(f"[ObjectNameBridge] 初期prompts: {self.prompts!r}")
        logger.info(
            f"[ObjectNameBridge] head入力/出力: {self.head_topic} -> "
            f"{self.head_mask_topic}, {self.head_overlay_topic}, "
            f"{self.head_centroid_topic}, {self.head_object_list_topic}"
        )
        logger.info(
            f"[ObjectNameBridge] hand入力/出力: {self.hand_topic} -> "
            f"{self.hand_mask_topic}, {self.hand_overlay_topic}, "
            f"{self.hand_centroid_topic}, {self.hand_object_list_topic}"
        )
        logger.info(
            f"[ObjectNameBridge] 入力切替: {self.switch_topic} "
            "(False=head, True=hand, default=head)"
        )
        logger.info(
            f"[ObjectNameBridge] prompt入力: {self.object_name_topic}, "
            f"{self.prompts_topic}"
        )
        logger.info("[ObjectNameBridge] mask出力: 16UC1 track-ID label mask")

    TIMING_COLUMNS = [
        "t_wall", "source", "prompts", "src_size", "send_size", "n_objects", "inflight", "stamp_age_ms", "queue_wait_ms",
        "convert_ms", "resize_ms", "jpeg_ms", "jpeg_kb", "rtt_ms", "server_gpu_ms",
        "mask_ms", "msgs_ms", "overlay_ms", "publish_ms", "work_ms", "e2e_ms", "stale",
    ]

    def _open_timing_log(self, enabled, directory):
        self.timing_file = None
        self.timing_lock = threading.Lock()
        self.inflight = 0
        if not enabled:
            return
        try:
            os.makedirs(directory, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(directory, f"bridge_{stamp}.csv")
            self.timing_file = open(path, "w", newline="", buffering=1)
            csv.writer(self.timing_file).writerow(self.TIMING_COLUMNS)
            self.get_logger().info(f"[ObjectNameBridge] 計測ログ: {path}")
        except OSError as exc:
            self.get_logger().warning(
                f"[ObjectNameBridge] 計測ログを作成できません({directory}): {exc}"
            )

    def _write_timing(self, **values):
        if self.timing_file is None:
            return
        row = [values.get(c, "") for c in self.TIMING_COLUMNS]
        row = [f"{v:.2f}" if isinstance(v, float) else v for v in row]
        with self.timing_lock:
            csv.writer(self.timing_file).writerow(row)

    def _declare_parameters(self):
        parameters = {
            "grpc_host": "localhost",
            "grpc_port": 50051,
            "grpc_timeout": 2.0,
            "jpeg_quality": 75,
            "max_width": 640,
            "max_height": 480,
            "max_in_flight": 2,
            # Trueならmask/centroid/object_listを入力画像の解像度に戻してpublishする。
            # aligned depthやCameraInfoと同じpixel座標系で扱えるようにするため。
            "publish_original_size": True,
            # 段階別の処理時間をCSVに記録する(ボトルネック計測用)。
            "timing_log": True,
            "timing_log_dir": "/ros2_ws/logs/sam3_timing",
            "topic_name": "/hsrb/head_rgbd_sensor/rgb/image_rect_color",
            "head_topic": "",
            "hand_topic": "/hsrb/hand_camera/image_raw",
            "switch_topic": "/sam3/switch",
            "object_name_topic": "/object_name",
            "prompts_topic": "/object_name_list",
            "default_prompt": "object",
            "head_mask_topic": "/sam/mask",
            "head_overlay_topic": "/sam/overlay",
            "head_centroid_topic": "/sam3/mask/centroid",
            "head_object_list_topic": "/sam3/object_list",
            "hand_mask_topic": "/sam3/hand/mask",
            "hand_overlay_topic": "/sam3/hand/overlay",
            "hand_centroid_topic": "/sam3/hand/mask/centroid",
            "hand_object_list_topic": "/sam3/hand/object_list",
        }
        for name, default in parameters.items():
            self.declare_parameter(name, default)
        self.declare_parameter("default_prompts", Parameter.Type.STRING_ARRAY)

    def _param(self, name):
        try:
            return self.get_parameter(name).value
        except ParameterUninitializedException:
            if name == "default_prompts":
                return []
            raise

    def _create_source_publishers(
        self, mask_topic, overlay_topic, centroid_topic, object_list_topic
    ):
        return {
            "mask": self.create_publisher(Image, mask_topic, 1),
            "overlay": self.create_publisher(Image, overlay_topic, 1),
            "centroid": self.create_publisher(PointStamped, centroid_topic, 1),
            "object_list": self.create_publisher(
                Sam3ObjectArray, object_list_topic, 1
            ),
        }

    @staticmethod
    def _normalize_prompts(values):
        normalized = []
        seen = set()
        if isinstance(values, str):
            values = [values]
        for value in values:
            prompt = str(value).strip()
            if prompt and prompt not in seen:
                seen.add(prompt)
                normalized.append(prompt)
        return normalized

    def _update_prompts(self, new_prompts):
        new_prompts = self._normalize_prompts(new_prompts)
        if not new_prompts:
            self.get_logger().warning(
                "[ObjectNameBridge] 空のpromptsを受信したため無視"
            )
            return

        with self.prompt_lock:
            old_prompts = self.prompts
            self.prompts = new_prompts
        if old_prompts != new_prompts:
            self._clear_frame_queue()
            self._request_tracking_reset()
            self.get_logger().info(
                f"[ObjectNameBridge] prompts更新: "
                f"{old_prompts!r} -> {new_prompts!r}"
            )

    def object_name_callback(self, msg):
        self._update_prompts([msg.data])

    def prompts_callback(self, msg):
        self._update_prompts(msg.data)

    def switch_callback(self, msg):
        new_source = "hand" if msg.data else "head"
        with self.source_lock:
            old_source = self.active_source
            self.active_source = new_source
        if old_source != new_source:
            self._clear_frame_queue()
            self._request_tracking_reset()
            self.get_logger().info(
                f"[ObjectNameBridge] 入力切替: {old_source} -> {new_source}"
            )

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
        try:
            self.frame_queue.put_nowait((source, msg, time.perf_counter()))
        except queue.Full:
            with self.stats_lock:
                self.stats["dropped"] += 1

    def _clear_frame_queue(self):
        while True:
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                return

    def _request_tracking_reset(self):
        with self.reset_lock:
            self.reset_tracking_next = True

    def _consume_tracking_reset_flag(self):
        with self.reset_lock:
            flag = self.reset_tracking_next
            self.reset_tracking_next = False
            return flag

    def _worker_loop(self):
        self.get_logger().info("[ObjectNameBridge] Workerスレッド起動")
        while rclpy.ok() and not self.shutdown_event.is_set():
            try:
                source, msg, t_recv = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                published = self._process_frame(source, msg, t_recv)
                with self.stats_lock:
                    self.stats["sent" if published else "stale"] += 1
            except grpc.RpcError as exc:
                with self.stats_lock:
                    self.stats["failed"] += 1
                self.get_logger().warning(
                    f"[ObjectNameBridge] gRPC失敗: "
                    f"code={exc.code()} details={exc.details()}"
                )
            except Exception as exc:
                with self.stats_lock:
                    self.stats["failed"] += 1
                self.get_logger().error(
                    f"[ObjectNameBridge] 予期せぬエラー: {exc!r}"
                )
        if rclpy.ok():
            self.get_logger().info("[ObjectNameBridge] Workerスレッド終了")

    def _process_frame(self, source, msg, t_recv):
        t0 = time.perf_counter()
        cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        cv_image = np.ascontiguousarray(cv_image, dtype=np.uint8)
        t_converted = time.perf_counter()
        orig_h, orig_w = cv_image.shape[:2]
        h, w = orig_h, orig_w
        # 縦横比を保ったままmax_width x max_heightに収まるよう縮小する。
        if w > self.max_w or h > self.max_h:
            scale = min(self.max_w / float(w), self.max_h / float(h))
            w = max(1, int(round(w * scale)))
            h = max(1, int(round(h * scale)))
            cv_image = cv2.resize(cv_image, (w, h), interpolation=cv2.INTER_AREA)
        t_resized = time.perf_counter()

        ok, jpeg = cv2.imencode(
            ".jpg", cv_image, [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
        )
        if not ok:
            raise RuntimeError("JPEG encodeに失敗しました")
        t_encoded = time.perf_counter()

        with self.prompt_lock:
            current_prompts = list(self.prompts)
        reset_tracking = self._consume_tracking_reset_flag()

        with self.timing_lock:
            self.inflight += 1
            inflight = self.inflight
        try:
            response = self.stub.SegmentImage(
                segment_pb2.ImageRequest(
                    image=jpeg.tobytes(),
                    width=w,
                    height=h,
                    prompt=current_prompts[0],
                    prompts=current_prompts,
                    source=source,
                    reset_tracking=reset_tracking,
                ),
                timeout=self.timeout,
            )
        except Exception as exc:
            if reset_tracking:
                self._request_tracking_reset()
            raise
        finally:
            with self.timing_lock:
                self.inflight -= 1
        t_rpc = time.perf_counter()

        publishers = self.publishers_by_source[source]
        if self.publish_original_size:
            out_size = (orig_w, orig_h)
        else:
            out_size = (int(response.width), int(response.height))
        id_mask, mask_msg = self._create_mask_message(response, out_size)
        mask_msg.header = msg.header
        centroid_msg = self._create_centroid_msg(id_mask, msg.header)
        t_mask = time.perf_counter()
        object_list_msg = self._create_object_list_msg(
            response, msg.header, source, current_prompts, out_size
        )
        t_msgs = time.perf_counter()
        overlay_msg = None
        if response.overlay_image:
            overlay = cv2.imdecode(
                np.frombuffer(response.overlay_image, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            if overlay is not None:
                overlay_msg = self.bridge.cv2_to_imgmsg(overlay, encoding="bgr8")
                overlay_msg.header = msg.header

        t_overlay = time.perf_counter()
        stamp_ns = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        stale = False
        with self.publish_lock:
            if stamp_ns < self.last_published_stamp.get(source, -1):
                stale = True
            else:
                self.last_published_stamp[source] = stamp_ns
                publishers["mask"].publish(mask_msg)
                if centroid_msg is not None:
                    publishers["centroid"].publish(centroid_msg)
                publishers["object_list"].publish(object_list_msg)
                if overlay_msg is not None:
                    publishers["overlay"].publish(overlay_msg)
        t_pub = time.perf_counter()
        # header.stampが現在時刻と同じ時計のときだけ意味を持つ(カメラ時計だと大きくずれる)。
        stamp_age_ms = self.get_clock().now().nanoseconds / 1e6 - stamp_ns / 1e6
        ms = lambda a, b: (b - a) * 1000.0
        self._write_timing(
            t_wall=time.time(),
            source=source,
            prompts="|".join(current_prompts),
            src_size=f"{orig_w}x{orig_h}",
            send_size=f"{w}x{h}",
            n_objects=int(response.num_objects),
            inflight=inflight,
            stamp_age_ms=stamp_age_ms,
            queue_wait_ms=ms(t_recv, t0),
            convert_ms=ms(t0, t_converted),
            resize_ms=ms(t_converted, t_resized),
            jpeg_ms=ms(t_resized, t_encoded),
            jpeg_kb=len(jpeg) / 1024.0,
            rtt_ms=ms(t_encoded, t_rpc),
            server_gpu_ms=float(response.inference_ms),
            mask_ms=ms(t_rpc, t_mask),
            msgs_ms=ms(t_mask, t_msgs),
            overlay_ms=ms(t_msgs, t_overlay),
            publish_ms=ms(t_overlay, t_pub),
            work_ms=ms(t0, t_pub),
            e2e_ms=ms(t_recv, t_pub),
            stale=int(stale),
        )
        if stale:
            return False

        object_ids = [obj.id for obj in response.objects]
        self.get_logger().info(
            f"[ObjectNameBridge] publish source={source!r} "
            f"prompts={current_prompts!r} reset_tracking={reset_tracking} "
            f"objects={response.num_objects} ids={object_ids} "
            f"inference={response.inference_ms:.1f}ms"
        )
        return True

    def _create_mask_message(self, response, out_size):
        if response.mask_encoding == "16UC1":
            id_mask = np.frombuffer(response.mask, dtype=np.uint16).reshape(
                response.height, response.width
            )
            id_mask = self._resize_label_mask(id_mask, out_size)
            return id_mask, self.bridge.cv2_to_imgmsg(id_mask, encoding="16UC1")

        mask = np.frombuffer(response.mask, dtype=np.uint8).reshape(
            response.height, response.width
        )
        mask = self._resize_label_mask(mask, out_size)
        id_mask = mask.astype(np.uint16)
        mask_vis = (mask > 0).astype(np.uint8) * 255
        return id_mask, self.bridge.cv2_to_imgmsg(mask_vis, encoding="mono8")

    @staticmethod
    def _resize_label_mask(mask, out_size):
        if (mask.shape[1], mask.shape[0]) == tuple(out_size):
            return mask
        # ラベル値(track ID)を混ぜないよう最近傍補間で拡大する。
        return cv2.resize(mask, out_size, interpolation=cv2.INTER_NEAREST)

    @staticmethod
    def _create_centroid_msg(mask, header):
        ys, xs = np.nonzero(mask > 0)
        if xs.size == 0:
            return None
        msg = PointStamped()
        msg.header = header
        msg.point.x = float(xs.mean())
        msg.point.y = float(ys.mean())
        msg.point.z = 0.0
        return msg

    @staticmethod
    def _create_object_list_msg(response, header, source, prompts, out_size):
        out_w, out_h = out_size
        # 推論画像のpixel座標をpublish解像度のpixel座標へ変換する。
        sx = out_w / float(response.width)
        sy = out_h / float(response.height)

        msg = Sam3ObjectArray()
        msg.header = header
        msg.source = source
        msg.prompt = prompts[0] if len(prompts) == 1 else ", ".join(prompts)
        msg.width = int(out_w)
        msg.height = int(out_h)
        msg.num_objects = int(response.num_objects)
        for detected in response.objects:
            obj = Sam3Object()
            obj.id = int(detected.id)
            obj.score = float(detected.score)
            obj.bbox_x = int(round(detected.bbox_x * sx))
            obj.bbox_y = int(round(detected.bbox_y * sy))
            obj.bbox_w = int(round(detected.bbox_w * sx))
            obj.bbox_h = int(round(detected.bbox_h * sy))
            obj.centroid_x = float((detected.centroid_x + 0.5) * sx - 0.5)
            obj.centroid_y = float((detected.centroid_y + 0.5) * sy - 0.5)
            obj.area = int(round(detected.area * sx * sy))
            obj.age = int(detected.age)
            obj.missed = int(detected.missed)
            obj.prompt = detected.prompt
            obj.prompt_index = int(detected.prompt_index)
            msg.objects.append(obj)
        return msg

    def _log_stats(self):
        with self.stats_lock:
            stats = self.stats.copy()
        self.get_logger().info(
            "[ObjectNameBridge] 統計 | "
            f"受信:{stats['received']} 破棄:{stats['dropped']} "
            f"送信成功:{stats['sent']} 失敗:{stats['failed']} "
            f"順序逆転破棄:{stats['stale']}"
        )

    def destroy_node(self):
        self.shutdown_event.set()
        for worker_thread in self.worker_threads:
            if worker_thread.is_alive():
                worker_thread.join(timeout=max(1.0, self.timeout + 0.5))
        self.channel.close()
        if self.timing_file is not None:
            self.timing_file.close()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ObjectNameBridge()
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
