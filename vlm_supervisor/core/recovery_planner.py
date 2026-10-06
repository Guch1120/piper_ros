"""Recovery Plan (Phase 6. 未実装: データ構造のみ).

Receding-horizon: VLM -> 1 Skill 実行 -> Observation 更新 -> VLM 再判断.
Plan は最後まで実行する列ではなく, 次回判断への hint として扱う.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class RejoinMode(str, enum.Enum):
    RESUME = "RESUME"
    FORCE_TRANSITION = "FORCE_TRANSITION"
    ARBITRARY_REJOIN = "ARBITRARY_REJOIN"


@dataclass
class RecoveryStep:
    skill_id: str
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryPlan:
    registry_version: int
    steps: List[RecoveryStep] = field(default_factory=list)
    rejoin_mode: Optional[RejoinMode] = None
    rejoin_target: Optional[str] = None  # state path or outcome
    reason: str = ""


class RecoveryPlanner:
    def next_step(self, *args, **kwargs) -> Optional[RecoveryStep]:
        raise NotImplementedError("Phase 6B 以降で実装")
