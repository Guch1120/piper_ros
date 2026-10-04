#!/usr/bin/env python3
import queue
import threading

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
        self.stats = {"received": 0, "dropped": 0, "sent": 0, "failed": 0}
        self.stats_lock = threading.Lock()
        self.shutdown_event = threading.Event()

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

        self.worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="grpc_worker"
        )
        self.worker_thread.start()
        self.stats_timer = self.create_timer(10.0, self._log_stats)

        logger = self.get_logger()
        logger.info(f"[ObjectNameBridge] gRPC接続先: {addr}")
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

    def _declare_parameters(self):
        parameters = {
            "grpc_host": "localhost",
            "grpc_port": 50051,
            "grpc_timeout": 2.0,
            "jpeg_quality": 75,
            "max_width": 640,
            "max_height": 480,
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
            self.frame_queue.put_nowait((source, msg))
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
                source, msg = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                self._process_frame(source, msg)
                with self.stats_lock:
                    self.stats["sent"] += 1
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

    def _process_frame(self, source, msg):
        cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        cv_image = np.ascontiguousarray(cv_image, dtype=np.uint8)
        h, w = cv_image.shape[:2]
        if w > self.max_w or h > self.max_h:
            cv_image = cv2.resize(cv_image, (self.max_w, self.max_h))
            h, w = self.max_h, self.max_w

        ok, jpeg = cv2.imencode(
            ".jpg", cv_image, [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
        )
        if not ok:
            raise RuntimeError("JPEG encodeに失敗しました")

        with self.prompt_lock:
            current_prompts = list(self.prompts)
        reset_tracking = self._consume_tracking_reset_flag()

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

        publishers = self.publishers_by_source[source]
        id_mask, mask_msg = self._create_mask_message(response)
        mask_msg.header = msg.header
        publishers["mask"].publish(mask_msg)

        centroid_msg = self._create_centroid_msg(id_mask, msg.header)
        if centroid_msg is not None:
            publishers["centroid"].publish(centroid_msg)

        publishers["object_list"].publish(
            self._create_object_list_msg(
                response, msg.header, source, current_prompts
            )
        )

        if response.overlay_image:
            overlay = cv2.imdecode(
                np.frombuffer(response.overlay_image, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            if overlay is not None:
                overlay_msg = self.bridge.cv2_to_imgmsg(overlay, encoding="bgr8")
                overlay_msg.header = msg.header
                publishers["overlay"].publish(overlay_msg)

        object_ids = [obj.id for obj in response.objects]
        self.get_logger().info(
            f"[ObjectNameBridge] publish source={source!r} "
            f"prompts={current_prompts!r} reset_tracking={reset_tracking} "
            f"objects={response.num_objects} ids={object_ids} "
            f"inference={response.inference_ms:.1f}ms"
        )

    def _create_mask_message(self, response):
        if response.mask_encoding == "16UC1":
            id_mask = np.frombuffer(response.mask, dtype=np.uint16).reshape(
                response.height, response.width
            )
            return id_mask, self.bridge.cv2_to_imgmsg(id_mask, encoding="16UC1")

        mask = np.frombuffer(response.mask, dtype=np.uint8).reshape(
            response.height, response.width
        )
        id_mask = mask.astype(np.uint16)
        mask_vis = (mask > 0).astype(np.uint8) * 255
        return id_mask, self.bridge.cv2_to_imgmsg(mask_vis, encoding="mono8")

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
    def _create_object_list_msg(response, header, source, prompts):
        msg = Sam3ObjectArray()
        msg.header = header
        msg.source = source
        msg.prompt = prompts[0] if len(prompts) == 1 else ", ".join(prompts)
        msg.width = int(response.width)
        msg.height = int(response.height)
        msg.num_objects = int(response.num_objects)
        for detected in response.objects:
            obj = Sam3Object()
            obj.id = int(detected.id)
            obj.score = float(detected.score)
            obj.bbox_x = int(detected.bbox_x)
            obj.bbox_y = int(detected.bbox_y)
            obj.bbox_w = int(detected.bbox_w)
            obj.bbox_h = int(detected.bbox_h)
            obj.centroid_x = float(detected.centroid_x)
            obj.centroid_y = float(detected.centroid_y)
            obj.area = int(detected.area)
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
            f"送信成功:{stats['sent']} 失敗:{stats['failed']}"
        )

    def destroy_node(self):
        self.shutdown_event.set()
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=max(1.0, self.timeout + 0.5))
        self.channel.close()
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
