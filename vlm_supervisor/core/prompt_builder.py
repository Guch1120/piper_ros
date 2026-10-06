"""SupervisorInput -> VLM prompt (Phase 4/5).

何を渡せば判断できるかは Phase 3 の snapshot で検証しながら調整する前提. 構成要素ごとに
on/off できるようにしておき, prompt 比較 (tools/evaluate_snapshot.py --prompt-*) をしやすくする.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .flexbe_context import render_graph_text
from .models import SupervisorInput

SHADOW_SYSTEM_PROMPT = """You are a semantic supervisor for a robot executed by a FlexBE state machine.
The state machine reports execution success (the state's code finished). Your job is to judge task success:
whether the real world, as seen in the camera image(s), shows that the purpose of the current or last state was achieved.
Do not output joint angles, velocities or trajectories.
Answer with ONE JSON object and nothing else, using this schema:
{"assessment": "semantic_success" | "semantic_failure" | "in_progress" | "uncertain",
 "reason": "<one short sentence about what you see>",
 "confidence": <number between 0 and 1>,
 "intervention": "FOLLOW_GRAPH" | "RECOVER" | "OVERRIDE" | "ABORT"}"""


@dataclass
class PromptOptions:
    include_graph: bool = True
    include_userdata: bool = True
    include_joint_state: bool = True
    include_odom: bool = True
    include_objects: bool = True
    include_transforms: bool = True
    include_history: bool = True
    include_state_entry_image: bool = True
    max_userdata_chars: int = 300
    max_graph_lines: int = 80


@dataclass
class Prompt:
    system: str
    user_text: str
    images: List[Any]  # ImageFrame. 順番は user_text 内の説明と一致させる
    image_labels: List[str]


def _r(x: Optional[float], n: int = 3) -> Optional[float]:
    return None if x is None else round(float(x), n)


def build_context_dict(si: SupervisorInput, opt: PromptOptions) -> Dict[str, Any]:
    """VLM に渡す context.json 相当 (画像以外). supervisor API の multipart でもそのまま使う."""
    obs = si.observation
    ctx = si.flexbe_context
    d: Dict[str, Any] = {"task_instruction": si.task_instruction, "trigger": si.trigger}

    if ctx is not None:
        fb: Dict[str, Any] = {
            "behavior_name": ctx.behavior_name,
            "status": ctx.status.value,
            "active_state_path": ctx.active_state_path,
            "available_outcomes": ctx.available_outcomes,
            "transitions": ctx.transitions,
            "elapsed_time_sec": _r(ctx.elapsed_time, 1),
            "state_elapsed_time_sec": _r(ctx.state_elapsed_time, 1),
        }
        if ctx.last_outcome is not None:
            fb["last_outcome"] = {"state_path": ctx.last_outcome.state_path,
                                  "outcome": ctx.last_outcome.outcome,
                                  "next": ctx.last_outcome.target}
        if opt.include_history and ctx.recent_transitions:
            fb["recent_transitions"] = [f"{r.state_path} > {r.outcome}" for r in ctx.recent_transitions[-8:]]
        desc = {}
        for key in (ctx.active_state_path, ctx.active_state,
                    ctx.last_outcome.state_path if ctx.last_outcome else None):
            if key and key in si.state_descriptions:
                desc[key] = si.state_descriptions[key]
        if desc:
            fb["state_descriptions"] = desc
        if opt.include_userdata and ctx.userdata:
            fb["userdata"] = {u.key: u.data[: opt.max_userdata_chars] for u in ctx.userdata}
        if ctx.behavior_inputs:
            fb["behavior_inputs"] = ctx.behavior_inputs
        d["flexbe"] = fb

    o: Dict[str, Any] = {}
    if opt.include_joint_state and obs.joint_state is not None:
        js = obs.joint_state
        o["joint_positions"] = {n: _r(p) for n, p in zip(js.names, js.positions)}
    if opt.include_odom and obs.odom is not None:
        o["base_pose"] = {"frame": obs.odom.frame_id,
                          "xyz": [_r(v) for v in obs.odom.position],
                          "quat_xyzw": [_r(v) for v in obs.odom.orientation]}
    if opt.include_transforms and obs.transforms:
        o["transforms"] = [{"parent": t.parent_frame, "child": t.child_frame,
                            "xyz": [_r(v) for v in t.translation]} for t in obs.transforms]
    if opt.include_objects and obs.objects:
        o["objects"] = [{k: v for k, v in {
            "source": ob.source, "label": ob.label, "frame": ob.frame_id,
            "xyz": [_r(v) for v in ob.position] if ob.position else None,
            "bbox": ob.bbox, "score": _r(ob.score),
        }.items() if v is not None} for ob in obs.objects]
    stale = [k for k, m in obs.meta.items() if m.stale]
    if stale:
        o["stale_inputs"] = stale
    if o:
        d["robot_state"] = o
    if opt.include_history and si.history:
        d["history"] = si.history[-5:]
    return d


def build_prompt(si: SupervisorInput, opt: Optional[PromptOptions] = None,
                 system_prompt: str = SHADOW_SYSTEM_PROMPT) -> Prompt:
    opt = opt or PromptOptions()
    images, labels = [], []
    if opt.include_state_entry_image and si.state_entry_image is not None:
        images.append(si.state_entry_image)
        labels.append("image at the moment the current state was entered")
    if si.observation.image is not None:
        images.append(si.observation.image)
        labels.append("current camera image")

    parts: List[str] = []
    if images:
        parts.append("Images (in order): " + "; ".join(f"[{i + 1}] {l}" for i, l in enumerate(labels)) + ".")
    else:
        parts.append("No camera image is available.")
    parts.append("Context:\n" + json.dumps(build_context_dict(si, opt), ensure_ascii=False, indent=1))
    ctx = si.flexbe_context
    if opt.include_graph and ctx is not None and ctx.graph:
        lines = render_graph_text(ctx.graph).splitlines()
        if len(lines) > opt.max_graph_lines:
            lines = lines[: opt.max_graph_lines] + ["  ..."]
        parts.append("Nominal behavior graph (state: outcome -> next):\n" + "\n".join(lines))
    parts.append("Return only the JSON object.")
    return Prompt(system=system_prompt, user_text="\n\n".join(parts), images=images, image_labels=labels)
