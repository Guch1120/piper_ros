"""実行ごとのログディレクトリ管理.

logs/<run_id>/
  run_info.json        起動設定 (config 全体, 引数, 時刻)
  supervisor.log       Python logging (node の主要ログ)
  events.jsonl         FlexBE event (behavior/state 変化, outcome, ...)
  observations.jsonl   一定周期の入力サマリ (受信数, age, stale)
  vlm.jsonl            VLM 評価結果 (Phase 4/5)
  snapshots/<seq>_<stamp>_<trigger>/   SupervisorInput (Phase 3)
  console.log          scripts/run_ros2.sh が stdout/stderr を tee したもの

エラー時は logs/latest (最新 run への symlink) ごと共有すれば状況を再現できる.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

from .snapshot import save_snapshot, snapshot_dir_name
from .models import SupervisorInput


def default_log_root() -> str:
    return os.environ.get("VLM_SUPERVISOR_LOG_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


class RunLogger:
    def __init__(self, root: Optional[str] = None, run_id: Optional[str] = None, logger_name: str = "vlm_supervisor"):
        self.root = root or default_log_root()
        self.run_id = run_id or os.environ.get("VLM_SUPERVISOR_RUN_ID") or time.strftime("%Y%m%d_%H%M%S")
        self.dir = os.path.join(self.root, self.run_id)
        self.snapshot_dir = os.path.join(self.dir, "snapshots")
        os.makedirs(self.snapshot_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._files: Dict[str, Any] = {}
        self._seq = 0
        self._update_latest_link()

        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler(os.path.join(self.dir, "supervisor.log"), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s", "%H:%M:%S"))
        fh.setLevel(logging.DEBUG)
        self.logger.addHandler(fh)
        self._fh = fh

    def _update_latest_link(self) -> None:
        link = os.path.join(self.root, "latest")
        try:
            if os.path.islink(link):
                os.remove(link)
            if not os.path.exists(link):
                os.symlink(self.run_id, link)
        except OSError:
            pass

    def write_json(self, name: str, obj: Any) -> None:
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, default=str)

    def append(self, stream: str, record: Dict[str, Any]) -> None:
        """stream: 'events' / 'observations' / 'vlm' -> <stream>.jsonl"""
        line = json.dumps({"wall_time": round(time.time(), 3), **record}, ensure_ascii=False, default=str)
        with self._lock:
            f = self._files.get(stream)
            if f is None:
                f = open(os.path.join(self.dir, f"{stream}.jsonl"), "a", encoding="utf-8")
                self._files[stream] = f
            f.write(line + "\n")
            f.flush()

    def save_snapshot(self, sup_input: SupervisorInput, extra: Optional[Dict[str, Any]] = None) -> str:
        with self._lock:
            self._seq += 1
            seq = self._seq
        out = os.path.join(self.snapshot_dir, snapshot_dir_name(seq, sup_input.timestamp, sup_input.trigger))
        return save_snapshot(sup_input, out, extra)

    def close(self) -> None:
        with self._lock:
            for f in self._files.values():
                f.close()
            self._files.clear()
        self.logger.removeHandler(self._fh)
        self._fh.close()
