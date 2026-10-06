"""ObservationStore: ROS callback と Supervisor の間で最新値を保持する.

ROS callback 側 (Adapter) は ROS非依存型へ変換してから update_*() を呼ぶ.
Supervisor 側は snapshot(now) で Observation を取り出す.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from .models import (
    ImageFrame,
    InputMeta,
    JointObservation,
    ObjectObservation,
    Observation,
    OdometryObservation,
    TransformObservation,
)


def tf_key(parent: str, child: str) -> str:
    return f"tf/{parent}->{child}"


def objects_key(source: str) -> str:
    return f"objects/{source}"


class ObservationStore:
    """latest-value store (thread-safe).

    stale_thresholds: {"image": 0.5, "tf/*": 1.0, ...} の形式. 未指定の key は stale 判定しない (None).
    Phase 1 では閾値を決めず age の計測を優先する.
    """

    def __init__(self, stale_thresholds: Optional[Dict[str, float]] = None):
        self._lock = threading.Lock()
        self._stale_thresholds = dict(stale_thresholds or {})
        self._image: Optional[ImageFrame] = None
        self._joint_state: Optional[JointObservation] = None
        self._odom: Optional[OdometryObservation] = None
        self._objects: Dict[str, List[ObjectObservation]] = {}
        self._transforms: Dict[str, Optional[TransformObservation]] = {}
        self._meta: Dict[str, InputMeta] = {}

    # ------------------------------------------------------------------ update

    def _touch(self, key: str, source_stamp: Optional[float], received_time: float,
               valid: bool = True, error: Optional[str] = None) -> None:
        prev = self._meta.get(key)
        count = prev.count + 1 if prev else 1
        self._meta[key] = InputMeta(source_stamp=source_stamp, received_time=received_time,
                                    valid=valid, count=count, error=error)

    def update_image(self, frame: ImageFrame, received_time: float) -> None:
        with self._lock:
            self._image = frame
            self._touch("image", frame.timestamp, received_time)

    def update_joint_state(self, joint: JointObservation, received_time: float) -> None:
        with self._lock:
            self._joint_state = joint
            self._touch("joint_state", joint.timestamp, received_time)

    def update_odom(self, odom: OdometryObservation, received_time: float) -> None:
        with self._lock:
            self._odom = odom
            self._touch("odom", odom.timestamp, received_time)

    def update_objects(self, source: str, objects: List[ObjectObservation], received_time: float,
                       source_stamp: Optional[float] = None) -> None:
        with self._lock:
            self._objects[source] = list(objects)
            self._touch(objects_key(source), source_stamp, received_time)

    def update_transform(self, parent: str, child: str, tf: Optional[TransformObservation],
                         received_time: float, error: Optional[str] = None) -> None:
        """tf=None は lookup 失敗. 直前の成功値は保持し valid=False / error を記録する."""
        key = tf_key(parent, child)
        with self._lock:
            if tf is not None:
                self._transforms[key] = tf
                self._touch(key, tf.timestamp, received_time)
            else:
                self._transforms.setdefault(key, None)
                prev = self._meta.get(key)
                if prev is None:
                    self._meta[key] = InputMeta(source_stamp=None, received_time=received_time,
                                                valid=False, count=0, error=error)
                else:
                    self._meta[key] = replace(prev, valid=False, error=error)

    def report_error(self, key: str, error: str, received_time: float) -> None:
        """変換失敗等. 値は更新せず meta だけ記録."""
        with self._lock:
            prev = self._meta.get(key)
            if prev is None:
                self._meta[key] = InputMeta(source_stamp=None, received_time=received_time,
                                            valid=False, count=0, error=error)
            else:
                self._meta[key] = replace(prev, error=error)

    # ---------------------------------------------------------------- snapshot

    def _threshold(self, key: str) -> Optional[float]:
        if key in self._stale_thresholds:
            return self._stale_thresholds[key]
        prefix = key.split("/", 1)[0] + "/*"
        return self._stale_thresholds.get(prefix)

    def snapshot(self, now: float) -> Observation:
        with self._lock:
            meta: Dict[str, InputMeta] = {}
            for key, m in self._meta.items():
                age_src = (now - m.source_stamp) if m.source_stamp is not None else None
                age_recv = now - m.received_time if m.count > 0 else None
                th = self._threshold(key)
                stale = None
                if th is not None:
                    ref = age_src if age_src is not None else age_recv
                    stale = True if ref is None else ref > th
                meta[key] = replace(m, age_source=age_src, age_received=age_recv, stale=stale)

            objects: List[ObjectObservation] = []
            for src in sorted(self._objects):
                objects.extend(copy.deepcopy(self._objects[src]))
            transforms = [copy.deepcopy(t) for _, t in sorted(self._transforms.items()) if t is not None]

            # ImageFrame は immutable 扱い (bytes) なので参照共有で良い
            return Observation(
                timestamp=now,
                image=self._image,
                joint_state=copy.deepcopy(self._joint_state),
                odom=copy.deepcopy(self._odom),
                objects=objects,
                transforms=transforms,
                meta=meta,
            )

    def latest_image(self) -> Tuple[Optional[ImageFrame], Optional[InputMeta]]:
        with self._lock:
            return self._image, self._meta.get("image")


def summarize_observation(obs: Observation) -> Dict[str, Dict[str, object]]:
    """ログ用の軽量サマリ (各入力の有無と age)."""
    out: Dict[str, Dict[str, object]] = {}
    for key, m in sorted(obs.meta.items()):
        out[key] = {
            "count": m.count,
            "valid": m.valid,
            "age_source": None if m.age_source is None else round(m.age_source, 3),
            "age_received": None if m.age_received is None else round(m.age_received, 3),
            "stale": m.stale,
            "error": m.error,
        }
    return out
