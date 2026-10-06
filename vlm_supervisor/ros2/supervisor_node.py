"""VLM Supervisor ROS 2 node.

起動 (コンテナ内):
  bash /ros2_ws/vlm_supervisor/scripts/run_ros2.sh
  # = python3 -m vlm_supervisor.ros2.supervisor_node --ros-args -p supervisor_config:=... -p topics_config:=...

services:
  ~/save_snapshot  (std_srvs/srv/Trigger)  現在の SupervisorInput を snapshot として保存
  ~/evaluate_now   (std_srvs/srv/Trigger)  snapshot を保存し VLM で評価 (vlm.enabled 時のみ)

FlexBE へは介入しない (Phase 1-5).
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import rclpy
import yaml
from rclpy.node import Node
from std_srvs.srv import Trigger

from vlm_supervisor.core.flexbe_context import FlexBEContextTracker
from vlm_supervisor.core.iphone_client import make_client
from vlm_supervisor.core.models import FlexBEEventType, ImageFrame, SupervisorInput
from vlm_supervisor.core.observation import ObservationStore, summarize_observation
from vlm_supervisor.core.prompt_builder import PromptOptions
from vlm_supervisor.core.run_logger import RunLogger
from vlm_supervisor.core.supervisor import Supervisor
from vlm_supervisor.ros2.observation_adapter import ObservationAdapter

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_yaml(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class SupervisorNode(Node):
    def __init__(self):
        super().__init__("vlm_supervisor")
        self.declare_parameter("supervisor_config", os.path.join(PKG_DIR, "config", "supervisor.yaml"))
        self.declare_parameter("topics_config", os.path.join(PKG_DIR, "config", "topics.yaml"))
        self.declare_parameter("task_instruction", "")
        self.declare_parameter("log_dir", "")

        sup_path = self.get_parameter("supervisor_config").value
        topics_path = self.get_parameter("topics_config").value
        self.cfg = _load_yaml(sup_path)
        self.topics_cfg = _load_yaml(topics_path)
        task = self.get_parameter("task_instruction").value or self.cfg.get("task_instruction", "")

        self.run = RunLogger(root=self.get_parameter("log_dir").value or None)
        self.flog = self.run.logger
        self.run.write_json("run_info.json", {
            "start_wall_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "argv": sys.argv,
            "supervisor_config_path": sup_path,
            "topics_config_path": topics_path,
            "use_sim_time": self.get_parameter("use_sim_time").value,
            "supervisor_config": self.cfg,
            "topics_config": self.topics_cfg,
        })
        self._info(f"log dir: {self.run.dir}")

        # ---------------- Phase 1
        self.store = ObservationStore(self.cfg.get("stale_thresholds") or {})
        self.obs_adapter = ObservationAdapter(self, self.store, self.topics_cfg, self.now_sec, self.get_logger())
        for k, v in self.obs_adapter.subscribed.items():
            self._info(f"[observation] {k}: {v}")
        if not self.obs_adapter.subscribed:
            self._warn("no observation input enabled in topics.yaml")

        # ---------------- Phase 2
        fcfg = self.cfg.get("flexbe") or {}
        self.tracker: Optional[FlexBEContextTracker] = None
        self.flexbe = None
        if fcfg.get("enabled", False):
            from vlm_supervisor.ros2.flexbe_adapter import FlexBEAdapter  # flexbe_msgs が必要
            self.tracker = FlexBEContextTracker(history_size=int(fcfg.get("history_size", 20)))
            self.flexbe = FlexBEAdapter(self, self.tracker, fcfg, self.now_sec, self.get_logger())
            for k, v in self.flexbe.topics.items():
                self._info(f"[flexbe] {k}: {v}")
        else:
            self._info("[flexbe] disabled (supervisor.yaml flexbe.enabled)")

        # ---------------- Phase 3
        scfg = self.cfg.get("snapshot") or {}
        self.snapshot_events = set(scfg.get("on_events") or [])
        self.snapshot_delay = float(scfg.get("event_delay_sec", 0.3))
        self.keep_entry_image = bool(scfg.get("keep_state_entry_image", True))
        self.state_entry_image: Optional[ImageFrame] = None
        self._pending: List[Tuple[float, str, Dict[str, Any]]] = []  # (due, trigger, extra)

        # ---------------- Phase 4/5
        vcfg = self.cfg.get("vlm") or {}
        self.vlm_enabled = bool(vcfg.get("enabled", False))
        popt = PromptOptions(**{k: v for k, v in (vcfg.get("prompt") or {}).items()
                                if k in PromptOptions.__dataclass_fields__})
        self.supervisor = Supervisor(client=make_client(vcfg) if self.vlm_enabled else None, task_instruction=task,
                                     prompt_options=popt, state_descriptions=self.cfg.get("state_descriptions") or {})
        self.vlm_events = set(vcfg.get("evaluate_on_events") or [])
        self.vlm_drop_if_busy = bool(vcfg.get("drop_if_busy", True))
        self._vlm_queue: "queue.Queue[Tuple[SupervisorInput, str]]" = queue.Queue(maxsize=1 if self.vlm_drop_if_busy
                                                                                  else 100)
        if self.vlm_enabled:
            if vcfg.get("mode", "shadow") != "shadow":
                raise RuntimeError("Phase 5 までは vlm.mode=shadow のみ対応")
            self._info(f"[vlm] enabled: client={vcfg.get('client')} api={vcfg.get('api')} "
                       f"base_url={vcfg.get('base_url')} (shadow mode, no intervention)")
            threading.Thread(target=self._vlm_worker, daemon=True).start()
            threading.Thread(target=self._vlm_health, daemon=True).start()
        else:
            self._info("[vlm] disabled (supervisor.yaml vlm.enabled)")

        # ---------------- timers / services
        self.create_timer(0.05, self._tick)
        lcfg = self.cfg.get("logging") or {}
        if float(lcfg.get("observation_summary_period_sec", 1.0)) > 0:
            self.create_timer(float(lcfg.get("observation_summary_period_sec", 1.0)), self._log_observation_summary)
        if float(lcfg.get("console_summary_period_sec", 5.0)) > 0:
            self.create_timer(float(lcfg.get("console_summary_period_sec", 5.0)), self._console_summary)
        if float(scfg.get("period_sec", 0.0)) > 0:
            self.create_timer(float(scfg["period_sec"]), lambda: self._save_snapshot("periodic"))
        self.create_service(Trigger, "~/save_snapshot", self._srv_save_snapshot)
        self.create_service(Trigger, "~/evaluate_now", self._srv_evaluate_now)
        self._info("vlm_supervisor ready")

    # ------------------------------------------------------------------ utils

    def now_sec(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _info(self, msg: str) -> None:
        self.get_logger().info(msg)
        self.flog.info(msg)

    def _warn(self, msg: str) -> None:
        self.get_logger().warn(msg)
        self.flog.warning(msg)

    def _error(self, msg: str) -> None:
        self.get_logger().error(msg)
        self.flog.error(msg)

    # ------------------------------------------------------------------ main loop

    def _tick(self) -> None:
        try:
            now = self.now_sec()
            if self.tracker is not None:
                for ev in self.tracker.drain_events():
                    self._handle_event(ev, now)
            due = [p for p in self._pending if p[0] <= now or now < p[0] - 60.0]  # 時刻巻き戻り(bagループ)対策
            self._pending = [p for p in self._pending if p not in due]
            for _, trigger, extra in due:
                path = self._save_snapshot(trigger, extra)
                if path and self.vlm_enabled and extra.get("evaluate"):
                    self._enqueue_vlm(path)
        except Exception as e:  # noqa: BLE001
            self._error(f"tick failed: {e}\n{traceback.format_exc()}")

    def _handle_event(self, ev, now: float) -> None:
        rec = ev.to_dict()
        self.run.append("events", rec)
        if ev.type != FlexBEEventType.USERDATA_UPDATED:
            self._info(f"[flexbe] {ev.type.value} {ev.data}")
        if ev.type == FlexBEEventType.BEHAVIOR_CHANGED:
            self.supervisor.reset_history()
            self.state_entry_image = None
        if ev.type == FlexBEEventType.STATE_ENTERED:
            if self.keep_entry_image:
                self.state_entry_image, _ = self.store.latest_image()
            fcfg = self.cfg.get("flexbe") or {}
            if fcfg.get("fetch_userdata_on_state_change", True) and self.flexbe is not None:
                self.flexbe.request_userdata()
        name = ev.type.value
        want_snap = name in self.snapshot_events
        want_vlm = self.vlm_enabled and name in self.vlm_events
        if want_snap or want_vlm:
            trigger = name
            if "state_path" in ev.data:
                trigger += "_" + str(ev.data["state_path"]).strip("/").replace("/", ".")
            if "outcome" in ev.data:
                trigger += "_" + str(ev.data["outcome"])
            self._pending.append((now + self.snapshot_delay, trigger, {"event": rec, "evaluate": want_vlm}))

    def build_input(self, trigger: str) -> SupervisorInput:
        now = self.now_sec()
        obs = self.store.snapshot(now)
        ctx = self.tracker.snapshot(now) if self.tracker is not None else None
        return self.supervisor.build_input(obs, ctx, trigger=trigger, state_entry_image=self.state_entry_image,
                                           timestamp=now)

    def _save_snapshot(self, trigger: str, extra: Optional[Dict[str, Any]] = None) -> Optional[str]:
        try:
            si = self.build_input(trigger)
            path = self.run.save_snapshot(si, {k: v for k, v in (extra or {}).items() if k != "evaluate"})
            img = "image" if si.observation.image is not None else "NO image"
            self.flog.info(f"snapshot saved ({img}): {path}")
            return path
        except Exception as e:  # noqa: BLE001
            self._error(f"snapshot failed: {e}\n{traceback.format_exc()}")
            return None

    # ------------------------------------------------------------------ logging

    def _log_observation_summary(self) -> None:
        obs = self.store.snapshot(self.now_sec())
        rec: Dict[str, Any] = {"ros_time": round(obs.timestamp, 3), "inputs": summarize_observation(obs)}
        if self.tracker is not None:
            ctx = self.tracker.snapshot(obs.timestamp, include_graph=False)
            rec["flexbe"] = {"status": ctx.status.value, "behavior": ctx.behavior_name,
                             "behavior_id": ctx.behavior_id, "active_state_path": ctx.active_state_path,
                             "source": ctx.active_state_source, "heartbeat_age": ctx.heartbeat_age,
                             "unresolved_checksum": ctx.unresolved_checksum}
        self.run.append("observations", rec)

    def _console_summary(self) -> None:
        obs = self.store.snapshot(self.now_sec())
        parts = []
        for key in sorted(self.obs_adapter.subscribed):
            m = obs.meta.get(key)
            if m is None or m.count == 0:
                parts.append(f"{key}=NONE" + (f"({m.error[:40]})" if m and m.error else ""))
            else:
                age = m.age_source if m.age_source is not None else m.age_received
                parts.append(f"{key}=n{m.count}/age{age:.2f}s" + ("" if m.valid else "/INVALID"))
        msg = "[obs] " + " ".join(parts)
        if self.tracker is not None:
            ctx = self.tracker.snapshot(obs.timestamp, include_graph=False)
            msg += f" | [flexbe] {ctx.status.value} {ctx.behavior_name} state={ctx.active_state_path}"
        self._info(msg)

    # ------------------------------------------------------------------ services

    def _srv_save_snapshot(self, req, res):
        path = self._save_snapshot("manual")
        res.success = path is not None
        res.message = path or "failed (see log)"
        return res

    def _srv_evaluate_now(self, req, res):
        if not self.vlm_enabled:
            res.success, res.message = False, "vlm.enabled is false"
            return res
        path = self._save_snapshot("manual_eval")
        if path is None:
            res.success, res.message = False, "snapshot failed"
            return res
        queued = self._enqueue_vlm(path)
        res.success = queued
        res.message = f"queued: {path}" if queued else "VLM busy (dropped)"
        return res

    # ------------------------------------------------------------------ VLM (shadow)

    def _enqueue_vlm(self, snap_path: str) -> bool:
        from vlm_supervisor.core.snapshot import load_snapshot
        try:
            si = load_snapshot(snap_path)  # 保存物と完全に同じ入力で評価する (offline 再評価と一致)
            self._vlm_queue.put_nowait((si, snap_path))
            return True
        except queue.Full:
            self._warn(f"[vlm] busy, dropped evaluation for {os.path.basename(snap_path)}")
            self.run.append("vlm", {"snapshot": snap_path, "dropped": True})
            return False

    def _vlm_worker(self) -> None:
        import json
        while rclpy.ok():
            try:
                si, path = self._vlm_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                result = self.supervisor.evaluate(si)
                rec = result.to_dict()
                rec["snapshot"] = path
                self.run.append("vlm", rec)
                with open(os.path.join(path, "vlm_result.json"), "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False, indent=2, default=str)
                d = result.decision
                fb = result.flexbe_summary.get("last_outcome") or {}
                if result.response.ok:
                    self._info(f"[vlm] {d.assessment.value if d.assessment else 'INVALID'} "
                               f"conf={d.confidence} intervention={d.intervention.value if d.intervention else None} "
                               f"| flexbe: {fb.get('state_path')} > {fb.get('outcome')} "
                               f"| {result.response.latency_sec:.1f}s | {d.reason}"
                               + (f" | parse_error={d.parse_error}" if d.parse_error else ""))
                else:
                    self._warn(f"[vlm] request failed: {result.response.error} "
                               f"({result.response.latency_sec:.1f}s)")
            except Exception as e:  # noqa: BLE001
                self._error(f"[vlm] evaluation crashed: {e}\n{traceback.format_exc()}")

    def _vlm_health(self) -> None:
        client = self.supervisor.client
        h = client.health() if client else {}
        self.run.append("vlm", {"health": h})
        if h.get("ok"):
            self._info(f"[vlm] health ok: {h.get('models', {}) if isinstance(h.get('models'), dict) else ''}")
        else:
            self._warn(f"[vlm] health check failed: {h}")

    def destroy_node(self):
        self._info("shutting down")
        self.run.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = SupervisorNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
