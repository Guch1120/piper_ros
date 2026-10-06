"""Phase 3: snapshot を人間が読める形で表示する (「この情報だけで状況を判断できるか」の確認用).

  cd ~/yamaguchi/piper_ros
  python3 -m vlm_supervisor.tools.show_snapshot vlm_supervisor/logs/latest/snapshots/00003_*
"""

from __future__ import annotations

import sys

from vlm_supervisor.core.flexbe_context import render_graph_text
from vlm_supervisor.core.observation import summarize_observation
from vlm_supervisor.core.snapshot import load_snapshot


def main() -> int:
    for snap in sys.argv[1:]:
        si = load_snapshot(snap)
        print(f"===== {snap}")
        print(f"trigger: {si.trigger}  ros_time: {si.timestamp:.3f}  task: {si.task_instruction!r}")
        img = si.observation.image
        print(f"image: {img.summary() if img else None}")
        print(f"state_entry_image: {si.state_entry_image.summary() if si.state_entry_image else None}")
        print("inputs:")
        for k, v in summarize_observation(si.observation).items():
            print(f"  {k}: {v}")
        if si.observation.joint_state:
            js = si.observation.joint_state
            print("joints:", {n: round(p, 3) for n, p in zip(js.names, js.positions)})
        for t in si.observation.transforms:
            print(f"tf {t.parent_frame}->{t.child_frame}: {[round(v, 3) for v in t.translation]}")
        for o in si.observation.objects:
            print(f"object[{o.source}] label={o.label} pos={o.position} bbox={o.bbox}")
        c = si.flexbe_context
        if c:
            print(f"flexbe: {c.status.value} behavior={c.behavior_name} ({c.behavior_id})")
            print(f"  active: {c.active_state_path} (source={c.active_state_source}, "
                  f"state_elapsed={c.state_elapsed_time})")
            print(f"  outcomes: {c.transitions}")
            print(f"  last_outcome: {c.last_outcome}")
            for r in c.recent_transitions:
                print(f"    {r.state_path} > {r.outcome} -> {r.target}")
            for u in c.userdata:
                print(f"  userdata {u.key} ({u.type}): {u.data[:200]}")
            if c.graph:
                print("  graph:\n" + "\n".join("    " + l for l in render_graph_text(c.graph).splitlines()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
