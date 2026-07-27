#!/usr/bin/env python3

import math
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import cv2
import message_filters
import numpy as np
import rclpy
import tf2_geometry_msgs  # noqa: F401: PointStamped transform registration
import tf2_ros
from cv_bridge import CvBridge, CvBridgeError
from geometry_msgs.msg import PointStamped
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import Bool, Empty
from visualization_msgs.msg import Marker, MarkerArray

from sam3_bridge.msg import Sam3Object, Sam3ObjectArray


"""
SAM3のフレーム単位検出結果を、registered depthとTFを用いて3次元追跡するROS2ノード。

入力:
  - 16UC1 label mask（値はbridge/serverが付けた一時ID）
  - Sam3ObjectArray
  - registered depth
  - RGB image（追跡ID付きoverlay生成用）
  - CameraInfo

出力:
  - 16UC1 label mask（値は本ノードが付けた永続track ID）
  - Sam3ObjectArray（id/age/missedを永続track情報へ置換）
  - overlay, centroid, MarkerArray

完全遮蔽中はtrackを一定時間保持し、再検出時の3次元位置と予測位置を照合する。
"""

@dataclass
class Detection3D:
    raw_id: int
    source_object: Sam3Object
    mask: np.ndarray
    centroid_2d: Tuple[float, float]
    area: int
    position: Optional[np.ndarray]

@dataclass
class Track3D:
    track_id: int
    position: Optional[np.ndarray]
    velocity: np.ndarray
    centroid_2d: Tuple[float, float]
    area: int
    score: float
    raw_id: int
    age: int
    missed: int
    last_stamp: Time
    last_seen_stamp: Time


class ObjectTrackingByUsingDepth(Node):
    def __init__(self):
        super().__init__("object_tracking_by_using_depth")

        # ---------- 入力 ----------
        self.mask_topic = self._declare_and_get("mask_topic", "/sam3/raw/mask")
        self.object_list_topic = self._declare_and_get(
            "object_list_topic", "/sam3/raw/object_list"
        )
        self.rgb_topic = self._declare_and_get(
            "rgb_topic", "/hsrb/head_rgbd_sensor/rgb/image_rect_color"
        )
        self.depth_topic = self._declare_and_get(
            "depth_topic",
            "/hsrb/head_rgbd_sensor/depth_registered/image_rect_raw",
        )
        self.camera_info_topic = self._declare_and_get(
            "camera_info_topic", "/hsrb/head_rgbd_sensor/rgb/camera_info"
        )
        self.switch_topic = self._declare_and_get("switch_topic", "/sam3/switch")
        self.reset_topic = self._declare_and_get(
            "reset_topic", "/sam3/depth_tracking/reset"
        )

        # ---------- 出力 ----------
        self.tracked_mask_topic = self._declare_and_get(
            "tracked_mask_topic", "/sam/mask"
        )
        self.tracked_object_list_topic = self._declare_and_get(
            "tracked_object_list_topic", "/sam3/object_list"
        )
        self.tracked_overlay_topic = self._declare_and_get(
            "tracked_overlay_topic", "/sam/overlay"
        )
        self.tracked_centroid_topic = self._declare_and_get(
            "tracked_centroid_topic", "/sam3/mask/centroid"
        )
        self.marker_topic = self._declare_and_get(
            "marker_topic", "/sam3/depth_tracking/markers"
        )

        # ---------- 追跡・深度 ----------
        self.fixed_frame = self._declare_and_get("fixed_frame", "odom")
        self.depth_scale = float(self._declare_and_get("depth_scale", 0.001))
        self.min_depth = float(self._declare_and_get("min_depth", 0.15))
        self.max_depth = float(self._declare_and_get("max_depth", 5.0))
        self.mask_erode_px = int(self._declare_and_get("mask_erode_px", 2))
        self.min_depth_pixels = int(
            self._declare_and_get("min_depth_pixels", 20)
        )
        self.max_depth_samples = int(
            self._declare_and_get("max_depth_samples", 2500)
        )
        self.depth_mad_scale = float(
            self._declare_and_get("depth_mad_scale", 3.5)
        )
        self.min_depth_band = float(
            self._declare_and_get("min_depth_band", 0.03)
        )
        self.max_match_distance = float(
            self._declare_and_get("max_match_distance", 0.35)
        )
        self.max_object_speed = float(
            self._declare_and_get("max_object_speed", 0.30)
        )
        self.max_prediction_time = float(
            self._declare_and_get("max_prediction_time", 2.0)
        )
        self.area_ratio_min = float(
            self._declare_and_get("area_ratio_min", 0.10)
        )
        self.area_ratio_max = float(
            self._declare_and_get("area_ratio_max", 10.0)
        )
        self.area_cost_weight = float(
            self._declare_and_get("area_cost_weight", 0.08)
        )
        self.raw_id_bonus = float(
            self._declare_and_get("raw_id_bonus", 0.12)
        )
        self.velocity_alpha = float(
            self._declare_and_get("velocity_alpha", 0.45)
        )
        self.max_missed_frames = int(
            self._declare_and_get("max_missed_frames", 30)
        )
        self.max_missed_seconds = float(
            self._declare_and_get("max_missed_seconds", 3.0)
        )

        # 深度が得られない検出に対する限定的な2D fallback。
        self.enable_2d_fallback = bool(
            self._declare_and_get("enable_2d_fallback", True)
        )
        self.fallback_centroid_threshold_px = float(
            self._declare_and_get("fallback_centroid_threshold_px", 70.0)
        )
        self.sync_queue_size = int(
            self._declare_and_get("sync_queue_size", 10)
        )
        self.sync_slop = float(self._declare_and_get("sync_slop", 0.12))
        self.tf_timeout = float(self._declare_and_get("tf_timeout", 0.10))
        self.allow_latest_tf = bool(
            self._declare_and_get("allow_latest_tf", True)
        )
        self.reset_on_source_switch = bool(
            self._declare_and_get("reset_on_source_switch", True)
        )
        self.publish_occluded_markers = bool(
            self._declare_and_get("publish_occluded_markers", True)
        )
        self.bridge = CvBridge()
        self.tf_buffer = tf2_ros.Buffer(cache_time=Duration(seconds=20.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)
        self.camera_info: Optional[CameraInfo] = None
        self.camera_info_lock = threading.Lock()
        self.track_lock = threading.RLock()
        self.tracks: Dict[int, Track3D] = {}
        self.next_track_id = 1
        self.current_prompt: Optional[str] = None
        self.active_source = "head"
        self.mask_pub = self.create_publisher(Image, self.tracked_mask_topic, 1)
        self.object_list_pub = self.create_publisher(
            Sam3ObjectArray, self.tracked_object_list_topic, 1
        )
        self.overlay_pub = self.create_publisher(
            Image, self.tracked_overlay_topic, 1
        )
        self.centroid_pub = self.create_publisher(
            PointStamped, self.tracked_centroid_topic, 1
        )
        self.marker_pub = self.create_publisher(MarkerArray, self.marker_topic, 1)

        self.camera_info_sub = self.create_subscription(
            CameraInfo, self.camera_info_topic, self._camera_info_callback, 1
        )
        self.switch_sub = self.create_subscription(
            Bool, self.switch_topic, self._switch_callback, 1
        )
        self.reset_sub = self.create_subscription(
            Empty, self.reset_topic, self._reset_callback, 1
        )
        self.mask_sub = message_filters.Subscriber(
            self, Image, self.mask_topic
        )
        self.objects_sub = message_filters.Subscriber(
            self, Sam3ObjectArray, self.object_list_topic
        )
        self.depth_sub = message_filters.Subscriber(
            self, Image, self.depth_topic
        )
        self.rgb_sub = message_filters.Subscriber(self, Image, self.rgb_topic)

        self.sync = message_filters.ApproximateTimeSynchronizer(
            [self.mask_sub, self.objects_sub, self.depth_sub, self.rgb_sub],
            queue_size=self.sync_queue_size,
            slop=self.sync_slop,
            allow_headerless=False,
        )
        self.sync.registerCallback(self._synchronized_callback)

        logger = self.get_logger()
        logger.info("[DepthTracker] 起動完了")
        logger.info(
            f"[DepthTracker] input mask={self.mask_topic} "
            f"objects={self.object_list_topic} depth={self.depth_topic} "
            f"rgb={self.rgb_topic}"
        )
        logger.info(
            f"[DepthTracker] fixed_frame={self.fixed_frame} "
            f"max_match_distance={self.max_match_distance:.3f}m "
            f"max_missed={self.max_missed_seconds:.2f}s/"
            f"{self.max_missed_frames}frames"
        )

    def _declare_and_get(self, name, default):
        self.declare_parameter(name, default)
        return self.get_parameter(name).value

    # ------------------------------------------------------------------
    # callbacks / reset
    # ------------------------------------------------------------------
    def _camera_info_callback(self, msg: CameraInfo):
        with self.camera_info_lock:
            self.camera_info = msg

    def _switch_callback(self, msg: Bool):
        new_source = "hand" if msg.data else "head"
        if new_source == self.active_source:
            return
        self.active_source = new_source
        if self.reset_on_source_switch:
            self._reset_tracks("camera source changed")

    def _reset_callback(self, _msg: Empty):
        self._reset_tracks("manual reset")

    def _reset_tracks(self, reason: str):
        with self.track_lock:
            self.tracks.clear()
            self.next_track_id = 1
            self.current_prompt = None
        self._publish_delete_all_markers()
        self.get_logger().info(f"[DepthTracker] tracking reset: {reason}")

    def _allocate_track_id(self) -> int:
        track_id = self.next_track_id
        self.next_track_id += 1
        if self.next_track_id > 65535:
            self.get_logger().warning(
                "[DepthTracker] 16-bit IDを使い切ったため全trackをreset"
            )
            self.tracks.clear()
            self.next_track_id = 1
        return track_id

    # ------------------------------------------------------------------
    # main callback
    # ------------------------------------------------------------------
    def _synchronized_callback(
        self,
        mask_msg: Image,
        objects_msg: Sam3ObjectArray,
        depth_msg: Image,
        rgb_msg: Image,
    ):
        # このノードはregistered depthを持つheadカメラだけを処理する。
        if objects_msg.source and objects_msg.source != "head":
            return
        if self.active_source != "head":
            return

        with self.camera_info_lock:
            camera_info = self.camera_info
        if camera_info is None:
            self.get_logger().warning(
                "[DepthTracker] CameraInfo待機中",
                throttle_duration_sec=5.0,
            )
            return

        prompt = objects_msg.prompt
        if self.current_prompt is None:
            self.current_prompt = prompt
        elif prompt != self.current_prompt:
            self._reset_tracks("prompt changed: {!r} -> {!r}".format(self.current_prompt, prompt))
            self.current_prompt = prompt

        try:
            raw_label_mask = self.bridge.imgmsg_to_cv2(mask_msg, desired_encoding="passthrough")
            raw_label_mask = np.asarray(raw_label_mask, dtype=np.uint16)
            depth_m = self._depth_to_meters(depth_msg)
            rgb = self.bridge.imgmsg_to_cv2(rgb_msg, desired_encoding="bgr8")
        except (CvBridgeError, ValueError) as exc:
            self.get_logger().error(
                f"[DepthTracker] image変換失敗: {exc}",
                throttle_duration_sec=2.0,
            )
            return

        depth_h, depth_w = depth_m.shape[:2]
        if raw_label_mask.shape[:2] != (depth_h, depth_w):
            raw_label_mask_depth = cv2.resize(
                raw_label_mask,
                (depth_w, depth_h),
                interpolation=cv2.INTER_NEAREST,
            ).astype(np.uint16)
        else:
            raw_label_mask_depth = raw_label_mask

        zero_stamp = Time().to_msg()
        stamp_msg = mask_msg.header.stamp
        if stamp_msg == zero_stamp:
            stamp_msg = depth_msg.header.stamp
        if stamp_msg == zero_stamp:
            stamp = self.get_clock().now()
        else:
            stamp = Time.from_msg(stamp_msg)

        detections: List[Detection3D] = []
        for obj in objects_msg.objects:
            raw_id = int(obj.id)
            binary_depth = raw_label_mask_depth == raw_id
            if not np.any(binary_depth):
                self.get_logger().warning(
                    f"[DepthTracker] object_list ID={raw_id}に対応する"
                    "mask画素がありません",
                    throttle_duration_sec=2.0,
                )
                continue

            position = self._estimate_world_position(
                binary_depth,
                depth_m,
                camera_info,
                stamp,
                depth_w,
                depth_h,
            )

            detections.append(
                Detection3D(
                    raw_id=raw_id,
                    source_object=obj,
                    mask=binary_depth,
                    centroid_2d=(float(obj.centroid_x), float(obj.centroid_y)),
                    area=int(obj.area),
                    position=position,
                )
            )

        with self.track_lock:
            assignments = self._update_tracks(detections, stamp)
            tracks_snapshot = dict(self.tracks)

        stable_mask_depth = np.zeros((depth_h, depth_w), dtype=np.uint16)
        stable_objects = Sam3ObjectArray()
        stable_objects.header = mask_msg.header
        stable_objects.source = objects_msg.source
        stable_objects.prompt = objects_msg.prompt
        stable_objects.width = int(objects_msg.width)
        stable_objects.height = int(objects_msg.height)

        visible_track_ids = set()
        for det_idx, track_id in assignments.items():
            det = detections[det_idx]
            track = tracks_snapshot[track_id]
            stable_mask_depth[det.mask] = np.uint16(track_id)
            stable_objects.objects.append(
                self._copy_object_with_track_id(det.source_object, track)
            )
            visible_track_ids.add(track_id)

        stable_objects.num_objects = len(stable_objects.objects)

        # downstream互換のため、maskは元SAM maskの解像度で出す。
        if stable_mask_depth.shape[:2] != raw_label_mask.shape[:2]:
            stable_mask_out = cv2.resize(stable_mask_depth,(raw_label_mask.shape[1], raw_label_mask.shape[0]),interpolation=cv2.INTER_NEAREST,
).astype(np.uint16)
        else:
            stable_mask_out = stable_mask_depth
        self._publish_outputs(stable_mask_out,stable_objects,rgb,tracks_snapshot,visible_track_ids,mask_msg.header,)

    # ------------------------------------------------------------------
    # depth / TF
    # ------------------------------------------------------------------
    def _depth_to_meters(self, msg: Image) -> np.ndarray:
        depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        depth = np.asarray(depth)

        encoding = (msg.encoding or "").upper()
        if encoding in ("16UC1", "MONO16") or depth.dtype == np.uint16:
            return depth.astype(np.float32) * self.depth_scale
        if encoding == "32FC1" or depth.dtype in (np.float32, np.float64):
            return depth.astype(np.float32)
        raise ValueError("未対応のdepth encoding/dtype: {}/{}".format(msg.encoding, depth.dtype))

    def _scaled_intrinsics(self, info: CameraInfo, image_w: int, image_h: int) -> Tuple[float, float, float, float]:
        info_w = int(info.width) if info.width else image_w
        info_h = int(info.height) if info.height else image_h
        sx = float(image_w) / float(max(info_w, 1))
        sy = float(image_h) / float(max(info_h, 1))
        fx = float(info.K[0]) * sx
        fy = float(info.K[4]) * sy
        cx = float(info.K[2]) * sx
        cy = float(info.K[5]) * sy
        return fx, fy, cx, cy

    def _estimate_world_position(self,binary_mask: np.ndarray,depth_m: np.ndarray,camera_info: CameraInfo,stamp: Time,image_w: int,
image_h: int,) -> Optional[np.ndarray]:
        mask = binary_mask.astype(np.uint8)
        if self.mask_erode_px > 0:
            kernel_size = 2 * self.mask_erode_px + 1
            kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
            eroded = cv2.erode(mask, kernel, iterations=1)
            if int(eroded.sum()) >= self.min_depth_pixels:
                mask = eroded

        valid = ((mask > 0)& np.isfinite(depth_m)& (depth_m >= self.min_depth)& (depth_m <= self.max_depth))
        ys, xs = np.nonzero(valid)
        if xs.size < self.min_depth_pixels:
            return None

        # 画素数が多い場合は等間隔sampling。乱数を使わず再現性を保つ。
        if xs.size > self.max_depth_samples:
            indices = np.linspace(0, xs.size - 1, self.max_depth_samples, dtype=np.int64)
            xs = xs[indices]
            ys = ys[indices]

        zs = depth_m[ys, xs].astype(np.float64)
        median_z = float(np.median(zs))
        mad = float(np.median(np.abs(zs - median_z)))
        robust_sigma = 1.4826 * mad
        depth_band = max(self.min_depth_band, self.depth_mad_scale * robust_sigma)
        keep = np.abs(zs - median_z) <= depth_band
        if int(np.count_nonzero(keep)) < self.min_depth_pixels:
            return None

        xs = xs[keep].astype(np.float64)
        ys = ys[keep].astype(np.float64)
        zs = zs[keep]
        fx, fy, cx, cy = self._scaled_intrinsics(camera_info, image_w, image_h)
        if fx <= 0.0 or fy <= 0.0:
            self.get_logger().error(
                "[DepthTracker] CameraInfoのfx/fyが不正",
                throttle_duration_sec=5.0,
            )
            return None

        points_x = (xs - cx) * zs / fx
        points_y = (ys - cy) * zs / fy
        point_cam = np.array([
float(np.median(points_x)),float(np.median(points_y)),float(np.median(zs)),],dtype=np.float64,)

        camera_frame = camera_info.header.frame_id
        if not camera_frame:
            self.get_logger().error(
                "[DepthTracker] CameraInfo.frame_idが空",
                throttle_duration_sec=5.0,
            )
            return None

        point_msg = PointStamped()
        point_msg.header.frame_id = camera_frame
        point_msg.header.stamp = stamp.to_msg()
        point_msg.point.x = float(point_cam[0])
        point_msg.point.y = float(point_cam[1])
        point_msg.point.z = float(point_cam[2])

        try:
            transformed = self.tf_buffer.transform(
                point_msg,
                self.fixed_frame,
                timeout=Duration(seconds=self.tf_timeout),
            )
        except Exception as first_exc:
            if not self.allow_latest_tf:
                self.get_logger().warning(
                    f"[DepthTracker] TF変換失敗: {first_exc}",
                    throttle_duration_sec=2.0,
                )
                return None
            try:
                point_msg.header.stamp = Time().to_msg()
                transformed = self.tf_buffer.transform(
                    point_msg,
                    self.fixed_frame,
                    timeout=Duration(seconds=self.tf_timeout),
                )
            except Exception as second_exc:
                self.get_logger().warning(
                    f"[DepthTracker] TF変換失敗 {camera_frame} -> "
                    f"{self.fixed_frame}: {second_exc}",
                    throttle_duration_sec=2.0,
                )
                return None

        return np.array([transformed.point.x,transformed.point.y,transformed.point.z,],dtype=np.float64,)

    # ------------------------------------------------------------------
    # association / tracking
    # ------------------------------------------------------------------
    @staticmethod
    def _area_ratio_ok(area_a: int, area_b: int, minimum: float, maximum: float):
        if area_a <= 0 or area_b <= 0:
            return False
        ratio = float(area_a) / float(area_b)
        return minimum <= ratio <= maximum

    @staticmethod
    def _centroid_distance(a: Tuple[float, float], b: Tuple[float, float]):
        return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))

    def _predict_position(self, track: Track3D, stamp: Time):
        if track.position is None:
            return None
        dt = max(0.0, (stamp - track.last_stamp).nanoseconds * 1.0e-9)
        dt = min(dt, self.max_prediction_time)
        return track.position + track.velocity * dt

    def _update_tracks(self, detections: List[Detection3D], stamp: Time) -> Dict[int, int]:
        assignments: Dict[int, int] = {}
        used_tracks = set()
        candidates = []

        # 3D位置が取れた検出を、trackの予測位置へ対応付ける。
        for det_idx, det in enumerate(detections):
            if det.position is None:
                continue
            for track_id, track in self.tracks.items():
                predicted = self._predict_position(track, stamp)
                if predicted is None:
                    continue
                if not self._area_ratio_ok(det.area,track.area,self.area_ratio_min,self.area_ratio_max,):
                    continue

                unseen_dt = max(
                    0.0,
                    (stamp - track.last_seen_stamp).nanoseconds * 1.0e-9,
                )
                gate = self.max_match_distance + self.max_object_speed * min(unseen_dt, self.max_prediction_time)
                distance = float(np.linalg.norm(det.position - predicted))
                if distance > gate:
                    continue
                area_penalty = abs(math.log(max(float(det.area), 1.0) / max(float(track.area), 1.0)))
                cost = distance / max(gate, 1.0e-6)
                cost += self.area_cost_weight * area_penalty
                if det.raw_id == track.raw_id:
                    cost -= self.raw_id_bonus
                candidates.append((cost, det_idx, track_id, distance))

        candidates.sort(key=lambda item: item[0])
        for _cost, det_idx, track_id, _distance in candidates:
            if det_idx in assignments or track_id in used_tracks:
                continue
            assignments[det_idx] = track_id
            used_tracks.add(track_id)

        # depthが無い場合、または3D候補が無かった場合の限定的fallback。
        if self.enable_2d_fallback:
            fallback_candidates = []
            for det_idx, det in enumerate(detections):
                if det_idx in assignments:
                    continue
                for track_id, track in self.tracks.items():
                    if track_id in used_tracks:
                        continue
                    if not self._area_ratio_ok(det.area,track.area,self.area_ratio_min,self.area_ratio_max,):
                        continue
                    pixel_distance = self._centroid_distance(
                        det.centroid_2d, track.centroid_2d
                    )
                    # raw IDが継続している場合を優先。raw IDが変わった場合は
                    # 小さな画素移動のみ許す。
                    threshold = self.fallback_centroid_threshold_px
                    if det.raw_id == track.raw_id:
                        threshold *= 1.5
                    if pixel_distance > threshold:
                        continue
                    cost = pixel_distance / max(threshold, 1.0)
                    if det.raw_id == track.raw_id:
                        cost -= self.raw_id_bonus
                    fallback_candidates.append((cost, det_idx, track_id))

            fallback_candidates.sort(key=lambda item: item[0])
            for _cost, det_idx, track_id in fallback_candidates:
                if det_idx in assignments or track_id in used_tracks:
                    continue
                assignments[det_idx] = track_id
                used_tracks.add(track_id)

        # 未対応検出へ新規ID。
        for det_idx in range(len(detections)):
            if det_idx in assignments:
                continue
            track_id = self._allocate_track_id()
            assignments[det_idx] = track_id
            used_tracks.add(track_id)

        new_tracks: Dict[int, Track3D] = {}
        for det_idx, track_id in assignments.items():
            det = detections[det_idx]
            old = self.tracks.get(track_id)
            if old is None:
                velocity = np.zeros(3, dtype=np.float64)
                age = 1
            else:
                age = old.age + 1
                velocity = old.velocity.copy()
                if det.position is not None and old.position is not None:
                    dt = max(
                        1.0e-3,
                        (stamp - old.last_stamp).nanoseconds * 1.0e-9,
                    )
                    measured_velocity = (det.position - old.position) / dt
                    velocity = (
                        self.velocity_alpha * measured_velocity
                        + (1.0 - self.velocity_alpha) * old.velocity
                    )

            position = det.position
            if position is None and old is not None:
                position = self._predict_position(old, stamp)

            new_tracks[track_id] = Track3D(
                track_id=track_id,
                position=position,
                velocity=velocity,
                centroid_2d=det.centroid_2d,
                area=det.area,
                score=float(det.source_object.score),
                raw_id=det.raw_id,
                age=age,
                missed=0,
                last_stamp=stamp,
                last_seen_stamp=stamp,
            )

        # 完全遮蔽中のtrackを保持し、速度モデルで位置を予測する。
        for track_id, old in self.tracks.items():
            if track_id in new_tracks:
                continue
            missed = old.missed + 1
            unseen_seconds = max(
                0.0,
                (stamp - old.last_seen_stamp).nanoseconds * 1.0e-9,
            )
            if (
                missed > self.max_missed_frames
                or unseen_seconds > self.max_missed_seconds
            ):
                continue

            predicted = self._predict_position(old, stamp)
            new_tracks[track_id] = Track3D(
                track_id=old.track_id,
                position=predicted,
                velocity=old.velocity,
                centroid_2d=old.centroid_2d,
                area=old.area,
                score=old.score,
                raw_id=old.raw_id,
                age=old.age,
                missed=missed,
                last_stamp=stamp,
                last_seen_stamp=old.last_seen_stamp,
            )

        self.tracks = new_tracks
        return assignments

    # ------------------------------------------------------------------
    # publish
    # ------------------------------------------------------------------
    @staticmethod
    def _copy_object_with_track_id(src: Sam3Object, track: Track3D) -> Sam3Object:
        dst = Sam3Object()
        dst.id = int(track.track_id)
        dst.score = float(src.score)
        dst.bbox_x = int(src.bbox_x)
        dst.bbox_y = int(src.bbox_y)
        dst.bbox_w = int(src.bbox_w)
        dst.bbox_h = int(src.bbox_h)
        dst.centroid_x = float(src.centroid_x)
        dst.centroid_y = float(src.centroid_y)
        dst.area = int(src.area)
        dst.age = int(track.age)
        dst.missed = int(track.missed)
        return dst

    @staticmethod
    def _color_for_id(track_id: int) -> Tuple[int, int, int]:
        rng = np.random.default_rng(int(track_id) * 12345)
        color = rng.integers(40, 255, size=3, dtype=np.uint8)
        return tuple(int(value) for value in color.tolist())

    def _publish_outputs(self,stable_mask: np.ndarray,stable_objects: Sam3ObjectArray,rgb: np.ndarray,tracks: Dict[int, Track3D],visible_track_ids: set,header,):
        mask_msg = self.bridge.cv2_to_imgmsg(stable_mask, encoding="16UC1")
        mask_msg.header = header
        self.mask_pub.publish(mask_msg)
        self.object_list_pub.publish(stable_objects)

        centroid = self._create_global_centroid(stable_mask, header)
        if centroid is not None:
            self.centroid_pub.publish(centroid)

        overlay = self._create_overlay(rgb, stable_mask, stable_objects)
        overlay_msg = self.bridge.cv2_to_imgmsg(overlay, encoding="bgr8")
        overlay_msg.header = header
        self.overlay_pub.publish(overlay_msg)
        marker_array = self._create_markers(tracks, visible_track_ids, header.stamp)
        self.marker_pub.publish(marker_array)

        self.get_logger().info(
            f"[DepthTracker] visible={len(stable_objects.objects)} "
            f"active_tracks={len(tracks)} "
            f"ids={[int(obj.id) for obj in stable_objects.objects]}",
            throttle_duration_sec=1.0,
        )

    @staticmethod
    def _create_global_centroid(mask: np.ndarray, header) -> Optional[PointStamped]:
        ys, xs = np.nonzero(mask > 0)
        if xs.size == 0:
            return None
        msg = PointStamped()
        msg.header = header
        msg.point.x = float(xs.mean())
        msg.point.y = float(ys.mean())
        msg.point.z = 0.0
        return msg

    def _create_overlay(
        self, rgb: np.ndarray, stable_mask: np.ndarray, objects: Sam3ObjectArray
    ) -> np.ndarray:
        h, w = stable_mask.shape[:2]
        if rgb.shape[:2] != (h, w):
            overlay = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_LINEAR)
        else:
            overlay = rgb.copy()

        for obj in objects.objects:
            track_id = int(obj.id)
            binary = stable_mask == track_id
            if not np.any(binary):
                continue
            color = np.array(self._color_for_id(track_id), dtype=np.uint8)
            color_tuple = tuple(int(value) for value in color.tolist())
            overlay[binary] = (0.5 * overlay[binary] + 0.5 * color).astype(np.uint8)
            contours, _ = cv2.findContours(binary.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE,)
            cv2.drawContours(overlay, contours, -1, color_tuple, 2)
            label = "ID:{}".format(track_id)
            x = max(0, int(obj.bbox_x))
            y = max(20, int(obj.bbox_y) - 5)
            cv2.putText(overlay,label,(x, y),cv2.FONT_HERSHEY_SIMPLEX,0.7,(0, 0, 0),4,cv2.LINE_AA,)
            cv2.putText(overlay,label,(x, y),cv2.FONT_HERSHEY_SIMPLEX,0.7,color_tuple,2,cv2.LINE_AA,)
        return overlay

    def _create_markers(
        self,
        tracks: Dict[int, Track3D],
        visible_track_ids: set,
        stamp,
    ) -> MarkerArray:
        marker_array = MarkerArray()
        for track_id, track in tracks.items():
            if track.position is None:
                continue
            if track_id not in visible_track_ids and not self.publish_occluded_markers:
                continue

            visible = track_id in visible_track_ids
            color_bgr = self._color_for_id(track_id)
            color_rgb = (color_bgr[2] / 255.0,color_bgr[1] / 255.0,color_bgr[0] / 255.0,)
            sphere = Marker()
            sphere.header.frame_id = self.fixed_frame
            sphere.header.stamp = stamp
            sphere.ns = "sam3_depth_tracks"
            sphere.id = int(track_id * 2)
            sphere.type = Marker.SPHERE
            sphere.action = Marker.ADD
            sphere.pose.position.x = float(track.position[0])
            sphere.pose.position.y = float(track.position[1])
            sphere.pose.position.z = float(track.position[2])
            sphere.pose.orientation.w = 1.0
            sphere.scale.x = 0.08
            sphere.scale.y = 0.08
            sphere.scale.z = 0.08
            sphere.color.r = color_rgb[0]
            sphere.color.g = color_rgb[1]
            sphere.color.b = color_rgb[2]
            sphere.color.a = 1.0 if visible else 0.30
            sphere.lifetime = Duration(seconds=0.5).to_msg()
            marker_array.markers.append(sphere)

            text = Marker()
            text.header = sphere.header
            text.ns = "sam3_depth_track_labels"
            text.id = int(track_id * 2 + 1)
            text.type = Marker.TEXT_VIEW_FACING
            text.action = Marker.ADD
            text.pose.position.x = float(track.position[0])
            text.pose.position.y = float(track.position[1])
            text.pose.position.z = float(track.position[2] + 0.12)
            text.pose.orientation.w = 1.0
            text.scale.z = 0.10
            text.color.r = color_rgb[0]
            text.color.g = color_rgb[1]
            text.color.b = color_rgb[2]
            text.color.a = 1.0 if visible else 0.45
            text.text = "ID:{}{}".format(
                track_id, "" if visible else " (occluded)"
            )
            text.lifetime = Duration(seconds=0.5).to_msg()
            marker_array.markers.append(text)

        return marker_array

    def _publish_delete_all_markers(self):
        marker = Marker()
        marker.header.frame_id = self.fixed_frame
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.action = Marker.DELETEALL
        marker_array = MarkerArray()
        marker_array.markers.append(marker)
        self.marker_pub.publish(marker_array)

    def destroy_node(self):
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ObjectTrackingByUsingDepth()
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
