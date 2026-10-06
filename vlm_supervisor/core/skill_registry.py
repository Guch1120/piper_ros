"""Skill Registry (Phase 6B 用. 現時点ではデータ構造と FlexBE graph からの構築のみ).

Behavior ごとに生成し, Behavior が変わったら破棄する. VLM は FlexBE State そのものではなく
概念上の Skill を選択する. cancel 等の実行系は Phase 6C 以降で ROS Adapter 側に実装する.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import FlexBEContext


@dataclass
class SkillDescriptor:
    skill_id: str
    state_id: str
    state_path: str
    description: str = ""
    outcomes: List[str] = field(default_factory=list)
    input_keys: List[str] = field(default_factory=list)
    output_keys: List[str] = field(default_factory=list)
    editable_userdata: List[str] = field(default_factory=list)
    can_cancel: bool = False


@dataclass
class SkillRegistry:
    behavior_id: Optional[int]
    behavior_name: Optional[str]
    version: int
    skills: Dict[str, SkillDescriptor] = field(default_factory=dict)

    @classmethod
    def from_flexbe_context(cls, ctx: FlexBEContext, descriptions: Optional[Dict[str, str]] = None,
                            version: int = 1) -> "SkillRegistry":
        """graph の leaf state を Skill 候補として登録する.

        input/output keys は ContainerStructure に含まれないため空. 必要になったら
        Behavior manifest か thin exporter から補う (Phase 6B で検討).
        """
        descriptions = descriptions or {}
        skills: Dict[str, SkillDescriptor] = {}
        for path, node in ctx.graph.items():
            if node.is_container or not path:
                continue
            skill_id = path.strip("/").replace("/", ".")
            skills[skill_id] = SkillDescriptor(
                skill_id=skill_id, state_id=node.name, state_path=path,
                description=descriptions.get(path, descriptions.get(node.name, "")),
                outcomes=list(node.outcomes),
            )
        return cls(behavior_id=ctx.behavior_id, behavior_name=ctx.behavior_name, version=version, skills=skills)
