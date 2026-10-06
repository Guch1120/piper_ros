"""Phase 1: ROS 2 topic -> ROS非依存型 -> ObservationStore.

ROS message はここで変換し, core へは渡さない.
"""

from __future__ import annotations

import io
import json
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

import rclpy
from PIL import Image
from rclpy.node import Node
from rclpy.qos import QoSProfile, qos_profile_sensor_data

from vlm_supervisor.core.models import (
    ImageFrame,
    JointObservation,
    ObjectObservation,
    OdometryObservation,
    TransformObservation,
)
from vlm_supervisor.core.observation import ObservationStore, objects_key

def stamp_to_sec(stamp) -> Optional[float]:
    """header.stamp -> float sec. 0 (未設定) は None."""
    t = stamp.sec + stamp.nanosec * 1e-9
    return t if t > 0.0 else None


def _qos(name: str):
    return qos_profile_sensor_data if name == "sensor_data" else QoSProfile(depth=10)


def _import_type(type_str: str):
    """'geometry_msgs/msg/Point' -> class."""
    pkg, _, name = type_str.split("/")
    module = __import__(f"{pkg}.msg", fromlist=[name])
    return getattr(module, name)


# --------------------------------------------------------------------------- converters

# sensor_msgs/Image encoding -> (PIL mode, raw mode, bytes per pixel)
_PIL_RAW = {
    "rgb8": ("RGB", "RGB", 3),
    "bgr8": ("RGB", "BGR", 3),
    "rgba8": ("RGBA", "RGBA", 4),
    "bgra8": ("RGBA", "BGRA", 4),
    "mono8": ("L", "L", 1),
    "8uc1": ("L", "L", 1),
}


def _encode_jpeg(img, quality: int, max_width: int):
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max_width and img.width > max_width:
        img = img.resize((max_width, int(round(img.height * max_width / float(img.width)))), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=int(quality))
    return img.width, img.height, buf.getvalue()


def image_msg_to_frame(msg, jpeg_quality: int = 85, max_width: int = 0) -> ImageFrame:
    """sensor_msgs/Image -> JPEG ImageFrame.

    コンテナの system cv2 (4.5.4) は pip の numpy 2.x と非互換で cvtColor 等が失敗するため Pillow を使う.
    """
    enc = msg.encoding.lower()
    if enc not in _PIL_RAW:
        raise ValueError(f"unsupported image encoding: {msg.encoding} (supported: {sorted(_PIL_RAW)})")
    mode, raw, _ = _PIL_RAW[enc]
    img = Image.frombuffer(mode, (msg.width, msg.height), bytes(msg.data), "raw", raw, msg.step, 1)
    w, h, data = _encode_jpeg(img, jpeg_quality, max_width)
    return ImageFrame(timestamp=stamp_to_sec(msg.header.stamp), frame_id=msg.header.frame_id,
                      width=w, height=h, mime_type="image/jpeg", data=data, source_encoding=msg.encoding)


def compressed_msg_to_frame(msg, max_width: int = 0, jpeg_quality: int = 85) -> ImageFrame:
    data = bytes(msg.data)
    img = Image.open(io.BytesIO(data))  # header だけ読む (lazy)
    if img.format == "JPEG" and (not max_width or img.width <= max_width):
        # JPEG payload をそのまま再利用
        return ImageFrame(timestamp=stamp_to_sec(msg.header.stamp), frame_id=msg.header.frame_id,
                          width=img.width, height=img.height, mime_type="image/jpeg", data=data,
                          source_encoding=msg.format)
    w, h, jpg = _encode_jpeg(img, jpeg_quality, max_width)
    return ImageFrame(timestamp=stamp_to_sec(msg.header.stamp), frame_id=msg.header.frame_id,
                      width=w, height=h, mime_type="image/jpeg", data=jpg, source_encoding=msg.format)


def joint_msg_to_obs(msg) -> JointObservation:
    return JointObservation(timestamp=stamp_to_sec(msg.header.stamp), names=list(msg.name),
                            positions=[float(x) for x in msg.position],
                            velocities=[float(x) for x in msg.velocity],
                            efforts=[float(x) for x in msg.effort])


def odom_msg_to_obs(msg) -> OdometryObservation:
    p, q = msg.pose.pose.position, msg.pose.pose.orientation
    lv, av = msg.twist.twist.linear, msg.twist.twist.angular
    return OdometryObservation(timestamp=stamp_to_sec(msg.header.stamp), frame_id=msg.header.frame_id,
                               child_frame_id=msg.child_frame_id, position=(p.x, p.y, p.z),
                               orientation=(q.x, q.y, q.z, q.w), linear_velocity=(lv.x, lv.y, lv.z),
                               angular_velocity=(av.x, av.y, av.z))


def tf_msg_to_obs(t) -> TransformObservation:
    tr, rot = t.transform.translation, t.transform.rotation
    return TransformObservation(timestamp=stamp_to_sec(t.header.stamp), parent_frame=t.header.frame_id,
                                child_frame=t.child_frame_id, translation=(tr.x, tr.y, tr.z),
                                rotation=(rot.x, rot.y, rot.z, rot.w))


def object_msg_to_obs(msg, type_str: str, source: str,
                      label: Optional[str]) -> Tuple[List[ObjectObservation], Optional[float]]:
    """returns (objects, source_stamp)."""
    name = type_str.rsplit("/", 1)[-1]
    if name == "Point":
        return [ObjectObservation(source=source, timestamp=None, label=label, position=(msg.x, msg.y, msg.z))], None
    if name == "PointStamped":
        st = stamp_to_sec(msg.header.stamp)
        p = msg.point
        return [ObjectObservation(source=source, timestamp=st, label=label, frame_id=msg.header.frame_id,
                                  position=(p.x, p.y, p.z))], st
    if name == "PoseStamped":
        st = stamp_to_sec(msg.header.stamp)
        p, q = msg.pose.position, msg.pose.orientation
        return [ObjectObservation(source=source, timestamp=st, label=label, frame_id=msg.header.frame_id,
                                  position=(p.x, p.y, p.z), orientation=(q.x, q.y, q.z, q.w))], st
    if name == "PoseArray":
        st = stamp_to_sec(msg.header.stamp)
        out = []
        for i, pose in enumerate(msg.poses):
            p, q = pose.position, pose.orientation
            out.append(ObjectObservation(source=source, timestamp=st, label=label, frame_id=msg.header.frame_id,
                                         position=(p.x, p.y, p.z), orientation=(q.x, q.y, q.z, q.w),
                                         extra={"index": i}))
        return out, st
    if name == "Int32MultiArray":
        return [ObjectObservation(source=source, timestamp=None, label=label, bbox=[int(v) for v in msg.data])], None
    if name == "String":
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            return [ObjectObservation(source=source, timestamp=None, label=label, extra={"text": msg.data})], None
        items = data if isinstance(data, list) else [data]
        out = []
        for it in items:
            if not isinstance(it, dict):
                it = {"value": it}
            pos = it.get("position")
            out.append(ObjectObservation(source=source, timestamp=None, label=it.get("label", label),
                                         position=tuple(pos) if isinstance(pos, (list, tuple)) and len(pos) == 3
                                         else None,
                                         bbox=it.get("bbox"), score=it.get("score"),
                                         extra={k: v for k, v in it.items()
                                                if k not in ("label", "position", "bbox", "score")}))
        return out, None
    raise ValueError(f"unsupported object message type: {type_str}")


# --------------------------------------------------------------------------- adapter

class ObservationAdapter:
    """topics.yaml に従って subscribe し ObservationStore を更新する."""

    def __init__(self, node: Node, store: ObservationStore, cfg: Dict[str, Any], now: Callable[[], float],
                 log=None):
        self.node = node
        self.store = store
        self.cfg = cfg
        self.now = now
        self.log = log or node.get_logger()
        self._subs = []
        self._last_image_time: Optional[float] = None
        self._error_counts: Dict[str, int] = {}
        self._tf_buffer = None
        self.subscribed: Dict[str, str] = {}

        self._setup_camera(cfg.get("camera") or {})
        self._setup_simple("joint_state", cfg.get("joint_state") or {}, "sensor_msgs/msg/JointState",
                           lambda m: self.store.update_joint_state(joint_msg_to_obs(m), self.now()))
        self._setup_simple("odom", cfg.get("odom") or {}, "nav_msgs/msg/Odometry",
                           lambda m: self.store.update_odom(odom_msg_to_obs(m), self.now()))
        for ocfg in cfg.get("objects") or []:
            self._setup_object(ocfg)
        self._setup_tf(cfg.get("tf") or {})

    # ---- error handling: callback 内の例外で node を落とさない
    def _guard(self, key: str, fn: Callable[[Any], None]) -> Callable[[Any], None]:
        def cb(msg):
            try:
                fn(msg)
            except Exception as e:  # noqa: BLE001
                n = self._error_counts.get(key, 0) + 1
                self._error_counts[key] = n
                self.store.report_error(key, f"{type(e).__name__}: {e}", self.now())
                if n <= 3 or n % 100 == 0:
                    self.log.error(f"[{key}] conversion failed ({n}x): {e}\n{traceback.format_exc()}")
        return cb

    def _setup_camera(self, c: Dict[str, Any]) -> None:
        if not c.get("enabled", False):
            return
        type_str = c.get("type", "sensor_msgs/msg/Image")
        msg_type = _import_type(type_str)
        period = 1.0 / float(c["max_rate_hz"]) if c.get("max_rate_hz") else 0.0
        quality = int(c.get("jpeg_quality", 85))
        max_width = int(c.get("max_width", 0))
        compressed = type_str.endswith("CompressedImage")

        def on_image(msg):
            now = self.now()
            # rosbag ループ再生等で時刻が戻った場合も throttle を解除する
            if period and self._last_image_time is not None and 0.0 <= now - self._last_image_time < period:
                return
            self._last_image_time = now
            frame = (compressed_msg_to_frame(msg, max_width, quality) if compressed
                     else image_msg_to_frame(msg, quality, max_width))
            self.store.update_image(frame, now)

        self._subs.append(self.node.create_subscription(msg_type, c["topic"], self._guard("image", on_image),
                                                        _qos(c.get("qos", "sensor_data"))))
        self.subscribed["image"] = f"{c['topic']} [{type_str}]"

    def _setup_simple(self, key: str, c: Dict[str, Any], type_str: str, fn) -> None:
        if not c.get("enabled", False):
            return
        type_str = c.get("type", type_str)
        self._subs.append(self.node.create_subscription(_import_type(type_str), c["topic"], self._guard(key, fn),
                                                        _qos(c.get("qos", "reliable"))))
        self.subscribed[key] = f"{c['topic']} [{type_str}]"

    def _setup_object(self, c: Dict[str, Any]) -> None:
        if not c.get("enabled", False):
            return
        source, type_str, label = c["name"], c["type"], c.get("label")

        def on_obj(msg):
            objs, st = object_msg_to_obs(msg, type_str, source, label)
            self.store.update_objects(source, objs, self.now(), st)

        key = objects_key(source)
        self._subs.append(self.node.create_subscription(_import_type(type_str), c["topic"], self._guard(key, on_obj),
                                                        _qos(c.get("qos", "reliable"))))
        self.subscribed[key] = f"{c['topic']} [{type_str}]"

    def _setup_tf(self, c: Dict[str, Any]) -> None:
        if not c.get("enabled", False) or not c.get("pairs"):
            return
        from tf2_ros import Buffer, TransformListener  # noqa: WPS433

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self.node, spin_thread=False)
        self._tf_pairs = [(p["parent"], p["child"]) for p in c["pairs"]]
        self.node.create_timer(1.0 / float(c.get("rate_hz", 5.0)), self._lookup_tf)
        for p, ch in self._tf_pairs:
            self.subscribed[f"tf/{p}->{ch}"] = "tf2 lookup"

    def _lookup_tf(self) -> None:
        for parent, child in self._tf_pairs:
            now = self.now()
            try:
                t = self._tf_buffer.lookup_transform(parent, child, rclpy.time.Time())
                self.store.update_transform(parent, child, tf_msg_to_obs(t), now)
            except Exception as e:  # noqa: BLE001  (LookupException, ExtrapolationException, ...)
                self.store.update_transform(parent, child, None, now, error=f"{type(e).__name__}: {e}"[:200])
