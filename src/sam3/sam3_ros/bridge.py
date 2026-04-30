"""Runtime helpers for ROS1 and ROS2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(slots=True)
class RosBindings:
    """Resolved ROS client bindings."""

    version: int
    api: Any
    bridge: Any


def resolve_backend(preferred: str = "auto") -> RosBindings:
    """Resolve ROS1 or ROS2 client bindings at runtime."""

    preferred = preferred.lower()
    if preferred not in {"auto", "ros1", "ros2"}:
        raise ValueError("preferred must be one of auto, ros1, ros2")

    ros_version = _env_ros_version()
    candidates: list[str] = []
    if preferred != "auto":
        candidates.append(preferred)
    elif ros_version in {"1", "2"}:
        candidates.append(f"ros{ros_version}")
    else:
        candidates.extend(["ros2", "ros1"])

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return _load_bindings(candidate)
        except Exception as exc:  # pragma: no cover - backend detection fallback
            last_error = exc
    if last_error is None:
        raise RuntimeError("No ROS backend could be resolved")
    raise RuntimeError(f"No ROS backend could be resolved: {last_error}") from last_error


def _env_ros_version() -> str | None:
    import os

    value = os.environ.get("ROS_VERSION")
    if value in {"1", "2"}:
        return value
    return None


def _load_bindings(candidate: str) -> RosBindings:
    if candidate == "ros2":
        import rclpy
        from cv_bridge import CvBridge

        return RosBindings(version=2, api=rclpy, bridge=CvBridge())

    import rospy
    from cv_bridge import CvBridge

    return RosBindings(version=1, api=rospy, bridge=CvBridge())


def image_msg_to_bgr(bridge: Any, msg: Any, encoding: str = "bgr8") -> np.ndarray:
    """Convert a ROS image message to a BGR numpy array."""

    return bridge.imgmsg_to_cv2(msg, desired_encoding=encoding)


def bgr_to_image_msg(bridge: Any, image_bgr: np.ndarray, encoding: str = "bgr8") -> Any:
    """Convert a BGR image to a ROS image message."""

    return bridge.cv2_to_imgmsg(image_bgr, encoding=encoding)


def mask_to_image_msg(bridge: Any, mask: np.ndarray) -> Any:
    """Publish a mask as a mono8 image message."""

    mono = np.asarray(mask)
    mono = np.squeeze(mono)
    if mono.ndim != 2:
        raise ValueError(f"Expected a 2D mask, got shape {mono.shape}")
    mono = np.ascontiguousarray(mono.astype(np.uint8) * 255)
    return bridge.cv2_to_imgmsg(mono, encoding="mono8")


def flatten_boxes(boxes: list[tuple[float, float, float, float]]) -> list[float]:
    flattened: list[float] = []
    for box in boxes:
        flattened.extend(float(value) for value in box)
    return flattened
