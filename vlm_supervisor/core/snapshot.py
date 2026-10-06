"""SupervisorInput の保存/読み込み (Phase 3).

<dir>/
  snapshot.json            SupervisorInput (画像は summary のみ)
  image.jpg                current image (あれば)
  state_entry_image.jpg    active state 進入時の image (あれば)
  metadata.json            保存理由・時刻・各入力の age 等 (人間が一目で見る用)
  prompt.txt / vlm_*.json  Phase 4/5 で評価した場合に追記される

rosbag 再生 → 保存 → tools/evaluate_snapshot.py で offline VLM 評価、という流れで再現性を確保する.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from .models import (
    BehaviorStatus,
    FlexBEContext,
    ImageFrame,
    InputMeta,
    JointObservation,
    ObjectObservation,
    Observation,
    OdometryObservation,
    StateNode,
    SupervisorInput,
    TransformObservation,
    TransitionRecord,
    UserdataEntry,
)
from .observation import summarize_observation

_EXT = {"image/jpeg": "jpg", "image/png": "png"}


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)[:60]


def snapshot_dir_name(seq: int, stamp: float, trigger: str) -> str:
    return f"{seq:05d}_{stamp:.3f}_{_safe(trigger)}"


def _write_image(path_wo_ext: str, frame: ImageFrame) -> str:
    path = f"{path_wo_ext}.{_EXT.get(frame.mime_type, 'bin')}"
    with open(path, "wb") as f:
        f.write(frame.data)
    return os.path.basename(path)


def save_snapshot(sup_input: SupervisorInput, out_dir: str, extra_metadata: Optional[Dict[str, Any]] = None) -> str:
    os.makedirs(out_dir, exist_ok=True)
    d = sup_input.to_dict()
    files = {}
    if sup_input.observation.image is not None:
        files["image"] = _write_image(os.path.join(out_dir, "image"), sup_input.observation.image)
    if sup_input.state_entry_image is not None:
        files["state_entry_image"] = _write_image(os.path.join(out_dir, "state_entry_image"),
                                                  sup_input.state_entry_image)
    d["files"] = files
    with open(os.path.join(out_dir, "snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2, default=str)

    ctx = sup_input.flexbe_context
    meta = {
        "timestamp": sup_input.timestamp,
        "trigger": sup_input.trigger,
        "task_instruction": sup_input.task_instruction,
        "files": files,
        "inputs": summarize_observation(sup_input.observation),
        "flexbe": None if ctx is None else {
            "status": ctx.status.value,
            "behavior_name": ctx.behavior_name,
            "behavior_id": ctx.behavior_id,
            "active_state_path": ctx.active_state_path,
            "active_state_source": ctx.active_state_source,
            "last_outcome": None if ctx.last_outcome is None else {
                "state_path": ctx.last_outcome.state_path,
                "outcome": ctx.last_outcome.outcome,
                "target": ctx.last_outcome.target,
            },
            "num_graph_states": len(ctx.graph),
            "num_userdata": len(ctx.userdata),
        },
    }
    if extra_metadata:
        meta.update(extra_metadata)
    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
    return out_dir


# --------------------------------------------------------------------------- load

def _tuple(v):
    return tuple(v) if v is not None else None


def _read_image(snap_dir: str, fname: Optional[str], summary: Optional[Dict[str, Any]]) -> Optional[ImageFrame]:
    if not fname or summary is None:
        return None
    path = os.path.join(snap_dir, fname)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        data = f.read()
    return ImageFrame(timestamp=summary.get("timestamp"), frame_id=summary.get("frame_id", ""),
                      width=summary.get("width", 0), height=summary.get("height", 0),
                      mime_type=summary.get("mime_type", "image/jpeg"), data=data,
                      source_encoding=summary.get("source_encoding", ""))


def observation_from_dict(d: Dict[str, Any], image: Optional[ImageFrame]) -> Observation:
    js = d.get("joint_state")
    od = d.get("odom")
    return Observation(
        timestamp=d["timestamp"],
        image=image,
        joint_state=JointObservation(**js) if js else None,
        odom=OdometryObservation(
            timestamp=od["timestamp"], frame_id=od["frame_id"], child_frame_id=od["child_frame_id"],
            position=_tuple(od["position"]), orientation=_tuple(od["orientation"]),
            linear_velocity=_tuple(od["linear_velocity"]), angular_velocity=_tuple(od["angular_velocity"]),
        ) if od else None,
        objects=[ObjectObservation(**{**o, "position": _tuple(o.get("position")),
                                      "orientation": _tuple(o.get("orientation"))})
                 for o in d.get("objects", [])],
        transforms=[TransformObservation(**{**t, "translation": _tuple(t["translation"]),
                                            "rotation": _tuple(t["rotation"])})
                    for t in d.get("transforms", [])],
        meta={k: InputMeta(**v) for k, v in d.get("meta", {}).items()},
    )


def flexbe_context_from_dict(d: Dict[str, Any]) -> FlexBEContext:
    def rec(r):
        return TransitionRecord(**r) if r else None

    return FlexBEContext(
        timestamp=d["timestamp"],
        status=BehaviorStatus(d.get("status", "UNKNOWN")),
        behavior_id=d.get("behavior_id"),
        behavior_name=d.get("behavior_name"),
        active_state=d.get("active_state"),
        active_state_path=d.get("active_state_path"),
        active_states=list(d.get("active_states", [])),
        active_state_source=d.get("active_state_source"),
        available_outcomes=list(d.get("available_outcomes", [])),
        transitions=dict(d.get("transitions", {})),
        userdata=[UserdataEntry(**u) for u in d.get("userdata", [])],
        userdata_time=d.get("userdata_time"),
        behavior_inputs=dict(d.get("behavior_inputs", {})),
        graph={k: StateNode(**v) for k, v in d.get("graph", {}).items()},
        graph_behavior_id=d.get("graph_behavior_id"),
        elapsed_time=d.get("elapsed_time"),
        state_elapsed_time=d.get("state_elapsed_time"),
        last_outcome=rec(d.get("last_outcome")),
        recent_transitions=[TransitionRecord(**r) for r in d.get("recent_transitions", [])],
        heartbeat_age=d.get("heartbeat_age"),
        unresolved_checksum=d.get("unresolved_checksum"),
    )


def load_snapshot(snap_dir: str) -> SupervisorInput:
    with open(os.path.join(snap_dir, "snapshot.json"), encoding="utf-8") as f:
        d = json.load(f)
    files = d.get("files", {})
    obs_d = d["observation"]
    image = _read_image(snap_dir, files.get("image"), obs_d.get("image"))
    entry = _read_image(snap_dir, files.get("state_entry_image"), d.get("state_entry_image"))
    ctx = d.get("flexbe_context")
    return SupervisorInput(
        timestamp=d["timestamp"],
        task_instruction=d.get("task_instruction", ""),
        observation=observation_from_dict(obs_d, image),
        flexbe_context=flexbe_context_from_dict(ctx) if ctx else None,
        trigger=d.get("trigger", "manual"),
        state_entry_image=entry,
        state_descriptions=dict(d.get("state_descriptions", {})),
        history=list(d.get("history", [])),
    )
