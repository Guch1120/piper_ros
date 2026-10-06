"""FlexBE の実行状態を ROS非依存に追跡し FlexBEContext を生成する.

FlexBE 2.3.x (humble) の外部から観測できる情報源 (実際の購読は ros2/flexbe_adapter.py):

  flexbe/status               BEStatus           STARTED/FINISHED/FAILED/... + behavior_id
  flexbe/heartbeat            BehaviorSync       1Hz. current_state_checksum = adler32(deep state path)
  flexbe/mirror/structure     ContainerStructure 全Container の path/children/outcomes/transitions
  flexbe/debug/current_state  String             "<state path> > <outcome>" (ROS control 有効時のみ)
  flexbe/behavior_update      String             mirror (GUI) が active state path を通知
  flexbe/log                  BehaviorLog        "Onboard Behavior Engine starting [<name> : <id>]"
  flexbe/start_behavior       BehaviorSelection  behavior_id と input_keys/values
  get_user_data (service)     GetUserdata        userdata の key/type/str(data)

Adapter は受信した message をプリミティブ型に分解して on_*() を呼ぶ.
"""

from __future__ import annotations

import re
import threading
import zlib
from collections import deque
from typing import Deque, Dict, Iterable, List, Optional, Sequence

from .models import (
    BehaviorStatus,
    FlexBEContext,
    FlexBEEvent,
    FlexBEEventType,
    StateNode,
    TransitionRecord,
    UserdataEntry,
)

_START_LOG_RE = re.compile(r"Onboard Behavior Engine starting \[(?P<name>.+?)\s*:\s*(?P<id>-?\d+)\]")


def state_checksum(path: str) -> int:
    """flexbe_core PreemptableStateMachine.get_latest_status() と同じ計算."""
    return zlib.adler32(path.encode()) & 0x7FFFFFFF


def parent_path(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def ancestor_paths(path: str) -> List[str]:
    """'/A/B/C' -> ['/A', '/A/B'] (自分自身は含まない)."""
    parts = [p for p in path.split("/") if p]
    return ["/" + "/".join(parts[:i]) for i in range(1, len(parts))]


class FlexBEContextTracker:
    def __init__(self, history_size: int = 20):
        self._lock = threading.Lock()
        self._events: Deque[FlexBEEvent] = deque(maxlen=1000)
        self._history: Deque[TransitionRecord] = deque(maxlen=history_size)

        self._status = BehaviorStatus.UNKNOWN
        self._behavior_id: Optional[int] = None
        self._behavior_name: Optional[str] = None
        self._names_by_id: Dict[int, str] = {}
        self._behavior_inputs: Dict[int, Dict[str, str]] = {}
        self._behavior_start_time: Optional[float] = None

        self._graph: Dict[str, StateNode] = {}
        self._graph_behavior_id: Optional[int] = None
        self._checksums: Dict[int, str] = {}

        self._active_path: Optional[str] = None
        self._active_source: Optional[str] = None
        self._state_enter_time: Optional[float] = None
        self._unresolved_checksum: Optional[int] = None
        self._last_heartbeat_time: Optional[float] = None

        self._userdata: List[UserdataEntry] = []
        self._userdata_time: Optional[float] = None

    # ------------------------------------------------------------------ helpers

    def _emit(self, etype: FlexBEEventType, now: float, **data) -> None:
        self._events.append(FlexBEEvent(type=etype, time=now, behavior_id=self._behavior_id, data=data))

    def drain_events(self) -> List[FlexBEEvent]:
        with self._lock:
            events = list(self._events)
            self._events.clear()
            return events

    def _reset_behavior(self) -> None:
        """Behavior 変更時: 旧 Behavior に紐づく情報を破棄する (graph は id 一致時のみ保持)."""
        self._active_path = None
        self._active_source = None
        self._state_enter_time = None
        self._unresolved_checksum = None
        self._userdata = []
        self._userdata_time = None
        self._history.clear()
        if self._graph_behavior_id is not None and self._graph_behavior_id != self._behavior_id:
            self._graph = {}
            self._checksums = {}
            self._graph_behavior_id = None

    def _set_behavior_id(self, behavior_id: Optional[int], now: float) -> None:
        if behavior_id is None or behavior_id in (0, -1):
            return
        if behavior_id != self._behavior_id:
            old = self._behavior_id
            self._behavior_id = behavior_id
            self._behavior_name = self._names_by_id.get(behavior_id)
            self._reset_behavior()
            self._emit(FlexBEEventType.BEHAVIOR_CHANGED, now, old_behavior_id=old,
                       behavior_name=self._behavior_name)

    def _resolve_path(self, candidate: str) -> Optional[str]:
        """mirror 由来の path ('_mirror' 付き, root名付き) を structure 上の path に寄せる."""
        if not self._graph:
            return candidate
        cands = [candidate, candidate.replace("_mirror", "")]
        for c in list(cands):
            parts = [p for p in c.split("/") if p]
            if len(parts) > 1:
                cands.append("/" + "/".join(parts[1:]))
        for c in cands:
            if c in self._graph:
                return c
        return None

    def _set_active(self, path: Optional[str], source: str, now: float) -> None:
        if path == self._active_path:
            if path is not None:
                self._active_source = source
            return
        prev = self._active_path
        self._active_path = path
        self._active_source = source
        self._state_enter_time = now
        if path is not None:
            self._emit(FlexBEEventType.STATE_ENTERED, now, state_path=path, previous_state_path=prev,
                       source=source)

    # ---------------------------------------------------------------- inputs

    def on_start_request(self, behavior_id: int, input_keys: Sequence[str], input_values: Sequence[str],
                         now: float) -> None:
        with self._lock:
            self._behavior_inputs[int(behavior_id)] = dict(zip(input_keys, input_values))

    def on_log(self, text: str, now: float) -> None:
        m = _START_LOG_RE.search(text)
        if not m:
            return
        with self._lock:
            bid = int(m.group("id"))
            name = m.group("name").strip()
            self._names_by_id[bid] = name
            if self._behavior_id == bid or self._behavior_id is None:
                self._behavior_name = name

    def on_status(self, code: int, behavior_id: int, args: Sequence[str], now: float) -> None:
        status = BehaviorStatus.from_code(code)
        with self._lock:
            prev = self._status
            self._status = status
            if status in (BehaviorStatus.STARTED, BehaviorStatus.RUNNING, BehaviorStatus.SWITCHING):
                self._set_behavior_id(behavior_id, now)
                self._behavior_name = self._names_by_id.get(self._behavior_id, self._behavior_name)
            if status == BehaviorStatus.STARTED:
                self._behavior_start_time = now
                # 同一 behavior の再起動でも state 系はリセット
                self._active_path = None
                self._state_enter_time = None
                self._history.clear()
                self._emit(FlexBEEventType.BEHAVIOR_STARTED, now, behavior_name=self._behavior_name,
                           args=list(args))
            elif status == BehaviorStatus.FINISHED:
                self._emit(FlexBEEventType.BEHAVIOR_FINISHED, now, behavior_name=self._behavior_name,
                           args=list(args), last_state_path=self._active_path)
            elif status == BehaviorStatus.FAILED:
                self._emit(FlexBEEventType.BEHAVIOR_FAILED, now, behavior_name=self._behavior_name,
                           args=list(args), last_state_path=self._active_path)
            if status != prev:
                self._emit(FlexBEEventType.STATUS, now, status=status.value, previous=prev.value,
                           args=list(args))
            if status in (BehaviorStatus.READY, BehaviorStatus.FINISHED, BehaviorStatus.FAILED):
                self._set_active(None, "status", now)

    def on_structure(self, behavior_id: int, containers: Iterable[dict], now: float) -> None:
        """containers: [{"path", "children", "outcomes", "transitions", "autonomy"}, ...]"""
        graph: Dict[str, StateNode] = {}
        for c in containers:
            path = str(c.get("path", ""))
            graph[path] = StateNode(
                path=path,
                name=path.rsplit("/", 1)[-1] if path else "",
                children=list(c.get("children", [])),
                outcomes=list(c.get("outcomes", [])),
                transitions=list(c.get("transitions", [])),
                autonomy=[int(a) for a in c.get("autonomy", [])],
            )
        with self._lock:
            self._set_behavior_id(behavior_id, now)
            self._graph = graph
            self._graph_behavior_id = behavior_id
            self._checksums = {state_checksum(p): p for p in graph}
            self._emit(FlexBEEventType.STRUCTURE_RECEIVED, now, num_states=len(graph),
                       structure_behavior_id=behavior_id)
            # structure 到着前に来ていた heartbeat を解決
            if self._unresolved_checksum is not None and self._unresolved_checksum in self._checksums:
                self._set_active(self._checksums[self._unresolved_checksum], "heartbeat", now)
                self._unresolved_checksum = None

    def on_heartbeat(self, behavior_id: int, checksum: int, now: float) -> None:
        with self._lock:
            self._last_heartbeat_time = now
            if behavior_id not in (0, -1) and self._status in (BehaviorStatus.STARTED, BehaviorStatus.RUNNING,
                                                               BehaviorStatus.UNKNOWN):
                self._set_behavior_id(behavior_id, now)
            if checksum in (0, -1):
                return
            path = self._checksums.get(checksum)
            if path is None:
                self._unresolved_checksum = checksum
                return
            self._unresolved_checksum = None
            # behavior_update (mirror) の方が即時性が高いので, 同一なら source を上書きしない
            if path != self._active_path:
                self._set_active(path, "heartbeat", now)

    def on_behavior_update(self, path: str, now: float) -> None:
        with self._lock:
            resolved = self._resolve_path(path)
            if resolved is not None:
                self._set_active(resolved, "behavior_update", now)

    def on_state_result(self, text: str, now: float) -> None:
        """flexbe/debug/current_state: '<path> > <outcome>'."""
        if " > " not in text:
            return
        path, outcome = text.rsplit(" > ", 1)
        path, outcome = path.strip(), outcome.strip()
        with self._lock:
            target = None
            node = self._graph.get(path)
            if node is not None:
                target = node.transition_map().get(outcome)
            rec = TransitionRecord(time=now, state_path=path, outcome=outcome, target=target)
            self._history.append(rec)
            self._emit(FlexBEEventType.STATE_OUTCOME, now, state_path=path, outcome=outcome, target=target)
            # 遷移先が兄弟 State なら即時に active を進める (heartbeat は 1Hz なので)
            if target is not None:
                sibling = parent_path(path) + "/" + target
                if sibling in self._graph:
                    self._set_active(sibling, "outcome", now)

    def on_userdata(self, entries: Iterable[UserdataEntry], now: float) -> None:
        with self._lock:
            self._userdata = list(entries)
            self._userdata_time = now
            self._emit(FlexBEEventType.USERDATA_UPDATED, now, num_entries=len(self._userdata))

    # ---------------------------------------------------------------- output

    @property
    def active_state_path(self) -> Optional[str]:
        with self._lock:
            return self._active_path

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._status in (BehaviorStatus.STARTED, BehaviorStatus.RUNNING)

    def snapshot(self, now: float, include_graph: bool = True) -> FlexBEContext:
        with self._lock:
            node = self._graph.get(self._active_path) if self._active_path else None
            active_states = ancestor_paths(self._active_path) if self._active_path else []
            return FlexBEContext(
                timestamp=now,
                status=self._status,
                behavior_id=self._behavior_id,
                behavior_name=self._behavior_name,
                active_state=self._active_path.rsplit("/", 1)[-1] if self._active_path else None,
                active_state_path=self._active_path,
                active_states=active_states,
                active_state_source=self._active_source,
                available_outcomes=list(node.outcomes) if node else [],
                transitions=node.transition_map() if node else {},
                userdata=list(self._userdata),
                userdata_time=self._userdata_time,
                behavior_inputs=dict(self._behavior_inputs.get(self._behavior_id, {}))
                if self._behavior_id is not None else {},
                graph=dict(self._graph) if include_graph else {},
                graph_behavior_id=self._graph_behavior_id,
                elapsed_time=(now - self._behavior_start_time) if self._behavior_start_time is not None
                and self._status in (BehaviorStatus.STARTED, BehaviorStatus.RUNNING) else None,
                state_elapsed_time=(now - self._state_enter_time) if self._state_enter_time is not None
                else None,
                last_outcome=self._history[-1] if self._history else None,
                recent_transitions=list(self._history),
                heartbeat_age=(now - self._last_heartbeat_time) if self._last_heartbeat_time else None,
                unresolved_checksum=self._unresolved_checksum,
            )


def render_graph_text(graph: Dict[str, StateNode], root: str = "") -> str:
    """Behavior graph を人間/VLM 向けのテキストにする.

    例:
      /Pick [container] outcomes=[finished, failed]
        /Pick/Detect: found -> Approach, not_found -> failed
    """
    lines: List[str] = []

    def walk(path: str, depth: int) -> None:
        node = graph.get(path)
        if node is None:
            return
        indent = "  " * depth
        edges = ", ".join(f"{o} -> {t}" for o, t in zip(node.outcomes, node.transitions))
        if node.is_container:
            label = path or "(root)"
            head = f"{indent}{label} [container] outcomes=[{', '.join(node.outcomes)}]"
            lines.append(head + (f" ; {edges}" if edges else ""))
            for child in node.children:
                walk(f"{path}/{child}", depth + 1)
        else:
            lines.append(f"{indent}{path}: {edges}")

    walk(root, 0)
    return "\n".join(lines)
