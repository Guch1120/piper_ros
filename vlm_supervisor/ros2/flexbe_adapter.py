"""Phase 2: FlexBE (humble, flexbe_behavior_engine 2.3.x) -> FlexBEContextTracker.

FlexBE へは介入しない (subscribe と userdata service の呼び出しのみ).
例外: request_structure_if_missing=true の場合だけ flexbe/request_mirror_structure を publish する.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from rclpy.node import Node
from rclpy.qos import QoSProfile
from std_msgs.msg import Int32, String, UInt8

from vlm_supervisor.core.flexbe_context import FlexBEContextTracker
from vlm_supervisor.core.models import UserdataEntry

try:
    from flexbe_msgs.msg import BehaviorLog, BehaviorSelection, BehaviorSync, BEStatus, ContainerStructure
    from flexbe_msgs.srv import GetUserdata
except ImportError as e:  # pragma: no cover
    raise ImportError("flexbe_msgs not found. `source /ros2_ws/install/setup.bash` してから起動すること") from e


class FlexBEAdapter:
    def __init__(self, node: Node, tracker: FlexBEContextTracker, cfg: Dict[str, Any],
                 now: Callable[[], float], log=None):
        self.node = node
        self.tracker = tracker
        self.cfg = cfg
        self.now = now
        self.log = log or node.get_logger()
        ns = cfg.get("namespace", "").strip("/")
        self._prefix = f"/{ns}/flexbe/" if ns else "/flexbe/"
        qos = QoSProfile(depth=100)

        def t(name: str) -> str:
            return self._prefix + name

        node.create_subscription(BEStatus, t("status"), self._on_status, qos)
        node.create_subscription(BehaviorSync, t("heartbeat"), self._on_heartbeat, 10)
        node.create_subscription(ContainerStructure, t("mirror/structure"), self._on_structure, qos)
        node.create_subscription(String, t("debug/current_state"), self._on_debug_state, qos)
        node.create_subscription(String, t("behavior_update"), self._on_behavior_update, qos)
        node.create_subscription(UInt8, t("mirror/outcome"), self._on_outcome_index, qos)
        node.create_subscription(BehaviorLog, t("log"), self._on_log, qos)
        node.create_subscription(BehaviorSelection, t("start_behavior"), self._on_start_behavior, qos)

        srv = cfg.get("userdata_service", "get_user_data")
        if ns and not srv.startswith("/"):
            srv = f"/{ns}/{srv}"
        self._userdata_client = node.create_client(GetUserdata, srv)
        self._userdata_pending = False
        self._struct_pub = node.create_publisher(Int32, t("request_mirror_structure"), 2) \
            if cfg.get("request_structure_if_missing", False) else None
        self._struct_requested_for: Optional[int] = None
        self.topics = {k: t(k) for k in ("status", "heartbeat", "mirror/structure", "debug/current_state",
                                         "behavior_update", "mirror/outcome", "log", "start_behavior")}
        self.topics["userdata_service"] = srv

        poll = float(cfg.get("userdata_poll_period_sec", 0.0))
        if poll > 0:
            node.create_timer(poll, self._poll_userdata)

    # --------------------------------------------------------------- callbacks

    def _on_status(self, msg) -> None:
        self.tracker.on_status(msg.code, msg.behavior_id, list(msg.args), self.now())

    def _on_heartbeat(self, msg) -> None:
        self.tracker.on_heartbeat(msg.behavior_id, msg.current_state_checksum, self.now())
        self._maybe_request_structure(msg.behavior_id)

    def _on_structure(self, msg) -> None:
        containers = [{"path": c.path, "children": list(c.children), "outcomes": list(c.outcomes),
                       "transitions": list(c.transitions), "autonomy": list(c.autonomy)} for c in msg.containers]
        self.tracker.on_structure(msg.behavior_id, containers, self.now())

    def _on_debug_state(self, msg) -> None:
        self.tracker.on_state_result(msg.data, self.now())

    def _on_behavior_update(self, msg) -> None:
        self.tracker.on_behavior_update(msg.data, self.now())

    def _on_outcome_index(self, msg) -> None:
        # debug/current_state の方が path 付きで情報が多いので, ここではログ用途のみ
        pass

    def _on_log(self, msg) -> None:
        self.tracker.on_log(msg.text, self.now())

    def _on_start_behavior(self, msg) -> None:
        self.tracker.on_start_request(msg.behavior_id, list(msg.input_keys), list(msg.input_values), self.now())

    # --------------------------------------------------------------- structure

    def _maybe_request_structure(self, behavior_id: int) -> None:
        if self._struct_pub is None or behavior_id in (0, -1):
            return
        ctx = self.tracker.snapshot(self.now(), include_graph=False)
        if ctx.graph_behavior_id == behavior_id or self._struct_requested_for == behavior_id:
            return
        self._struct_requested_for = behavior_id
        self.log.warn(f"structure for behavior_id={behavior_id} missing; publishing request_mirror_structure")
        self._struct_pub.publish(Int32(data=behavior_id))

    # --------------------------------------------------------------- userdata

    def _poll_userdata(self) -> None:
        if self.tracker.is_running:
            self.request_userdata()

    def request_userdata(self) -> bool:
        """非同期に get_user_data を呼ぶ. 結果は tracker.on_userdata へ."""
        if self._userdata_pending:
            return False
        if not self._userdata_client.service_is_ready():
            return False
        self._userdata_pending = True
        fut = self._userdata_client.call_async(GetUserdata.Request(userdata_key=""))

        def done(f):
            self._userdata_pending = False
            try:
                res = f.result()
            except Exception as e:  # noqa: BLE001
                self.log.warn(f"get_user_data failed: {e}")
                return
            if res is None:
                return
            entries = [UserdataEntry(state=u.state, key=u.key, type=u.type, data=u.data) for u in res.userdata]
            self.tracker.on_userdata(entries, self.now())

        fut.add_done_callback(done)
        return True
