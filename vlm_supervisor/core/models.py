"""ROS非依存のデータ型.

core/ 以下では ROS message を一切扱わない. ROS Adapter がここで定義した型へ変換してから
ObservationStore / FlexBEContextTracker に渡す.

時刻はすべて float 秒 (ROS time を想定. rosbag 再生時は /clock 由来の sim time) で扱う.
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

Vector3 = Tuple[float, float, float]
Quaternion = Tuple[float, float, float, float]  # (x, y, z, w)


# --------------------------------------------------------------------------- #
# Phase 1: Observation
# --------------------------------------------------------------------------- #

@dataclass
class InputMeta:
    """各入力の鮮度情報.

    source_stamp: message header の時刻 (header が無い型では None)
    received_time: Adapter が受信した時刻
    age_source / age_received: snapshot 時点での経過秒
    stale: stale_threshold が設定されている場合のみ判定. 未設定なら None
    """

    source_stamp: Optional[float]
    received_time: float
    age_source: Optional[float] = None
    age_received: Optional[float] = None
    valid: bool = True
    stale: Optional[bool] = None
    count: int = 0  # 起動からの受信回数 (欠落/周期の確認用)
    error: Optional[str] = None


@dataclass
class ImageFrame:
    timestamp: Optional[float]
    frame_id: str
    width: int
    height: int
    mime_type: str  # "image/jpeg" を推奨
    data: bytes = field(repr=False)
    source_encoding: str = ""

    def summary(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "frame_id": self.frame_id,
            "width": self.width,
            "height": self.height,
            "mime_type": self.mime_type,
            "bytes": len(self.data),
            "source_encoding": self.source_encoding,
        }


@dataclass
class JointObservation:
    timestamp: Optional[float]
    names: List[str]
    positions: List[float]
    velocities: List[float] = field(default_factory=list)
    efforts: List[float] = field(default_factory=list)


@dataclass
class OdometryObservation:
    timestamp: Optional[float]
    frame_id: str
    child_frame_id: str
    position: Vector3
    orientation: Quaternion
    linear_velocity: Vector3 = (0.0, 0.0, 0.0)
    angular_velocity: Vector3 = (0.0, 0.0, 0.0)


@dataclass
class TransformObservation:
    timestamp: Optional[float]
    parent_frame: str
    child_frame: str
    translation: Vector3
    rotation: Quaternion


@dataclass
class ObjectObservation:
    """物体認識結果 (SAM3 等). 型ごとに入る値が異なるため全項目 optional."""

    source: str  # topics.yaml の name
    timestamp: Optional[float]
    label: Optional[str] = None
    frame_id: Optional[str] = None
    position: Optional[Vector3] = None
    orientation: Optional[Quaternion] = None
    bbox: Optional[List[int]] = None  # [x1, y1, x2, y2] 等. 発行側の定義に従う
    score: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Observation:
    timestamp: float
    image: Optional[ImageFrame] = None
    joint_state: Optional[JointObservation] = None
    odom: Optional[OdometryObservation] = None
    objects: List[ObjectObservation] = field(default_factory=list)
    transforms: List[TransformObservation] = field(default_factory=list)
    # key: "image" / "joint_state" / "odom" / "objects/<source>" / "tf/<parent>-><child>"
    meta: Dict[str, InputMeta] = field(default_factory=dict)

    def to_dict(self, include_image_bytes: bool = False) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "timestamp": self.timestamp,
            "image": None,
            "joint_state": asdict(self.joint_state) if self.joint_state else None,
            "odom": asdict(self.odom) if self.odom else None,
            "objects": [asdict(o) for o in self.objects],
            "transforms": [asdict(t) for t in self.transforms],
            "meta": {k: asdict(v) for k, v in self.meta.items()},
        }
        if self.image is not None:
            d["image"] = self.image.summary()
            if include_image_bytes:
                d["image"]["data"] = self.image.data
        return d


# --------------------------------------------------------------------------- #
# Phase 2: FlexBEContext
# --------------------------------------------------------------------------- #

class BehaviorStatus(str, enum.Enum):
    """flexbe_msgs/BEStatus の code を文字列化したもの."""

    STARTED = "STARTED"
    FINISHED = "FINISHED"
    FAILED = "FAILED"
    LOCKED = "LOCKED"
    WAITING = "WAITING"
    SWITCHING = "SWITCHING"
    WARNING = "WARNING"
    ERROR = "ERROR"
    READY = "READY"
    RUNNING = "RUNNING"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_code(cls, code: int) -> "BehaviorStatus":
        return _BESTATUS_CODES.get(int(code), cls.UNKNOWN)


_BESTATUS_CODES = {
    0: BehaviorStatus.STARTED,
    1: BehaviorStatus.FINISHED,
    2: BehaviorStatus.FAILED,
    4: BehaviorStatus.LOCKED,
    5: BehaviorStatus.WAITING,
    6: BehaviorStatus.SWITCHING,
    10: BehaviorStatus.WARNING,
    11: BehaviorStatus.ERROR,
    20: BehaviorStatus.READY,
    30: BehaviorStatus.RUNNING,
}


@dataclass
class StateNode:
    """flexbe_msgs/Container 1個分. transitions[i] は outcomes[i] の遷移先 (兄弟State名 or 親outcome)."""

    path: str
    name: str
    children: List[str] = field(default_factory=list)
    outcomes: List[str] = field(default_factory=list)
    transitions: List[str] = field(default_factory=list)
    autonomy: List[int] = field(default_factory=list)

    @property
    def is_container(self) -> bool:
        return len(self.children) > 0

    def transition_map(self) -> Dict[str, str]:
        return dict(zip(self.outcomes, self.transitions))


@dataclass
class UserdataEntry:
    state: str
    key: str
    type: str
    data: str  # onboard 側で str() 済みの値


@dataclass
class TransitionRecord:
    time: float
    state_path: str
    outcome: str
    target: Optional[str]  # graph から解決できた場合のみ


@dataclass
class FlexBEContext:
    timestamp: float
    status: BehaviorStatus = BehaviorStatus.UNKNOWN
    behavior_id: Optional[int] = None
    behavior_name: Optional[str] = None
    active_state: Optional[str] = None
    active_state_path: Optional[str] = None
    active_states: List[str] = field(default_factory=list)  # root側から見た nested container の path 列
    active_state_source: Optional[str] = None  # "behavior_update" / "heartbeat" / "outcome"
    available_outcomes: List[str] = field(default_factory=list)
    transitions: Dict[str, str] = field(default_factory=dict)  # active state の outcome -> target
    userdata: List[UserdataEntry] = field(default_factory=list)
    userdata_time: Optional[float] = None
    behavior_inputs: Dict[str, str] = field(default_factory=dict)  # start_behavior の input_keys/values
    graph: Dict[str, StateNode] = field(default_factory=dict)  # path -> node
    graph_behavior_id: Optional[int] = None
    elapsed_time: Optional[float] = None  # Behavior 開始からの経過
    state_elapsed_time: Optional[float] = None  # active state 進入からの経過
    last_outcome: Optional[TransitionRecord] = None
    recent_transitions: List[TransitionRecord] = field(default_factory=list)
    heartbeat_age: Optional[float] = None
    unresolved_checksum: Optional[int] = None

    def to_dict(self, include_graph: bool = True) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        if not include_graph:
            d.pop("graph")
        return d


class FlexBEEventType(str, enum.Enum):
    BEHAVIOR_STARTED = "BEHAVIOR_STARTED"
    BEHAVIOR_FINISHED = "BEHAVIOR_FINISHED"
    BEHAVIOR_FAILED = "BEHAVIOR_FAILED"
    BEHAVIOR_CHANGED = "BEHAVIOR_CHANGED"  # behavior_id が変わった
    STATUS = "STATUS"
    STRUCTURE_RECEIVED = "STRUCTURE_RECEIVED"
    STATE_ENTERED = "STATE_ENTERED"
    STATE_OUTCOME = "STATE_OUTCOME"
    USERDATA_UPDATED = "USERDATA_UPDATED"


@dataclass
class FlexBEEvent:
    type: FlexBEEventType
    time: float
    behavior_id: Optional[int] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type.value, "time": self.time, "behavior_id": self.behavior_id, "data": self.data}


# --------------------------------------------------------------------------- #
# Phase 3: SupervisorInput
# --------------------------------------------------------------------------- #

@dataclass
class SupervisorInput:
    timestamp: float
    task_instruction: str
    observation: Observation
    flexbe_context: Optional[FlexBEContext] = None
    trigger: str = "manual"  # periodic / manual / STATE_OUTCOME 等
    state_entry_image: Optional[ImageFrame] = None
    state_descriptions: Dict[str, str] = field(default_factory=dict)  # state name/path -> 目的の短い説明
    history: List[Dict[str, Any]] = field(default_factory=list)  # 直近のSkill/VLM判断等 (Phase 5以降)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "task_instruction": self.task_instruction,
            "trigger": self.trigger,
            "observation": self.observation.to_dict(),
            "flexbe_context": self.flexbe_context.to_dict() if self.flexbe_context else None,
            "state_entry_image": self.state_entry_image.summary() if self.state_entry_image else None,
            "state_descriptions": self.state_descriptions,
            "history": self.history,
        }


# --------------------------------------------------------------------------- #
# Phase 4/5: VLM response
# --------------------------------------------------------------------------- #

class Assessment(str, enum.Enum):
    SEMANTIC_SUCCESS = "semantic_success"
    SEMANTIC_FAILURE = "semantic_failure"
    IN_PROGRESS = "in_progress"
    UNCERTAIN = "uncertain"


class Intervention(str, enum.Enum):
    """Phase 6A で使用. Phase 5 では記録のみ."""

    FOLLOW_GRAPH = "FOLLOW_GRAPH"
    RECOVER = "RECOVER"
    OVERRIDE = "OVERRIDE"
    ABORT = "ABORT"


@dataclass
class VLMResponse:
    """iPhone (or mock) からの生応答."""

    ok: bool
    text: str = ""
    latency_sec: Optional[float] = None
    model: Optional[str] = None
    error: Optional[str] = None  # timeout / connection / http_<code> / ...
    raw: Optional[Dict[str, Any]] = None


@dataclass
class SupervisorDecision:
    """VLM応答を parse した結果."""

    valid: bool
    assessment: Optional[Assessment] = None
    reason: str = ""
    confidence: Optional[float] = None
    intervention: Optional[Intervention] = None
    next_skill: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    parse_error: Optional[str] = None
    raw_json: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["assessment"] = self.assessment.value if self.assessment else None
        d["intervention"] = self.intervention.value if self.intervention else None
        return d
