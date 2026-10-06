"""Phase 4/5: 保存済み snapshot を offline で VLM 評価する (ROS 不要).

  cd ~/yamaguchi/piper_ros
  python3 -m vlm_supervisor.tools.evaluate_snapshot vlm_supervisor/logs/latest/snapshots/* --client mock
  python3 -m vlm_supervisor.tools.evaluate_snapshot <snap_dir>... --client iphone --out results.jsonl

--dry-run で prompt だけ表示 (VLM に送らない). prompt 比較用に --no-graph 等で要素を外せる.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from vlm_supervisor.core.iphone_client import make_client
from vlm_supervisor.core.prompt_builder import PromptOptions, build_prompt
from vlm_supervisor.core.snapshot import load_snapshot
from vlm_supervisor.core.supervisor import Supervisor


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshots", nargs="+")
    ap.add_argument("--client", choices=["mock", "iphone"], default="mock")
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--model", default="")
    ap.add_argument("--api", default="openai_chat", choices=["openai_chat", "supervisor"])
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--task", default=None, help="task_instruction を上書き")
    ap.add_argument("--out", default=None, help="結果を追記する jsonl")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-graph", action="store_true")
    ap.add_argument("--no-userdata", action="store_true")
    ap.add_argument("--no-entry-image", action="store_true")
    a = ap.parse_args()

    opt = PromptOptions(include_graph=not a.no_graph, include_userdata=not a.no_userdata,
                        include_state_entry_image=not a.no_entry_image)
    client = make_client({"client": a.client, "base_url": a.base_url, "model": a.model, "api": a.api,
                          "timeout_sec": a.timeout, "max_tokens": a.max_tokens})
    sup = Supervisor(client=client, prompt_options=opt)
    out = open(a.out, "a", encoding="utf-8") if a.out else None
    rc = 0
    for snap in a.snapshots:
        if not os.path.exists(os.path.join(snap, "snapshot.json")):
            continue
        si = load_snapshot(snap)
        if a.task is not None:
            si.task_instruction = a.task
        if a.dry_run:
            p = build_prompt(si, opt)
            print(f"===== {snap}\n[system]\n{p.system}\n[images] {p.image_labels}\n[user]\n{p.user_text}\n")
            continue
        r = sup.evaluate(si, record_history=False)
        rec = {"snapshot": snap, **r.to_dict(include_prompt_text=False)}
        d = r.decision
        fb = r.flexbe_summary.get("last_outcome") or {}
        print(f"{os.path.basename(snap)}: ok={r.response.ok} {r.response.error or ''} "
              f"assessment={d.assessment.value if d.assessment else None} conf={d.confidence} "
              f"flexbe={fb.get('state_path')}>{fb.get('outcome')} latency={r.response.latency_sec:.1f}s "
              f"reason={d.reason!r}" + (f" parse_error={d.parse_error}" if d.parse_error else ""))
        if not r.response.ok or not d.valid:
            rc = 1
        if out:
            out.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    if out:
        out.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
