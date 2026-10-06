"""Supervisor 本体 (ROS非依存).

Phase 3: Observation + FlexBEContext -> SupervisorInput
Phase 4/5: SupervisorInput -> prompt -> VLM client -> SupervisorDecision (記録のみ. FlexBE へ介入しない)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .decision_parser import parse_decision
from .iphone_client import VLMClient
from .models import (
    FlexBEContext,
    ImageFrame,
    Observation,
    SupervisorDecision,
    SupervisorInput,
    VLMResponse,
)
from .prompt_builder import SHADOW_SYSTEM_PROMPT, Prompt, PromptOptions, build_context_dict, build_prompt


@dataclass
class EvaluationResult:
    input_timestamp: float
    trigger: str
    prompt: Prompt
    response: VLMResponse
    decision: SupervisorDecision
    flexbe_summary: Dict[str, Any] = field(default_factory=dict)
    wall_time: float = field(default_factory=time.time)

    def to_dict(self, include_prompt_text: bool = True) -> Dict[str, Any]:
        d = {
            "wall_time": self.wall_time,
            "input_timestamp": self.input_timestamp,
            "trigger": self.trigger,
            "flexbe": self.flexbe_summary,
            "response": {
                "ok": self.response.ok,
                "error": self.response.error,
                "latency_sec": self.response.latency_sec,
                "model": self.response.model,
                "text": self.response.text,
            },
            "decision": self.decision.to_dict(),
            "num_images": len(self.prompt.images),
        }
        if include_prompt_text:
            d["prompt"] = {"system": self.prompt.system, "user_text": self.prompt.user_text,
                           "image_labels": self.prompt.image_labels}
        return d


def flexbe_summary(ctx: Optional[FlexBEContext]) -> Dict[str, Any]:
    """Phase 5 で FlexBE judgement と VLM judgement を並べて記録するための要約."""
    if ctx is None:
        return {}
    return {
        "behavior_name": ctx.behavior_name,
        "status": ctx.status.value,
        "active_state_path": ctx.active_state_path,
        "last_outcome": None if ctx.last_outcome is None else {
            "state_path": ctx.last_outcome.state_path,
            "outcome": ctx.last_outcome.outcome,
            "target": ctx.last_outcome.target,
        },
    }


class Supervisor:
    def __init__(self, client: Optional[VLMClient] = None, task_instruction: str = "",
                 prompt_options: Optional[PromptOptions] = None,
                 state_descriptions: Optional[Dict[str, str]] = None,
                 system_prompt: str = SHADOW_SYSTEM_PROMPT, history_size: int = 10):
        self.client = client
        self.task_instruction = task_instruction
        self.prompt_options = prompt_options or PromptOptions()
        self.state_descriptions = dict(state_descriptions or {})
        self.system_prompt = system_prompt
        self._history: List[Dict[str, Any]] = []
        self._history_size = history_size

    def build_input(self, observation: Observation, flexbe_context: Optional[FlexBEContext] = None,
                    trigger: str = "manual", state_entry_image: Optional[ImageFrame] = None,
                    timestamp: Optional[float] = None) -> SupervisorInput:
        return SupervisorInput(
            timestamp=timestamp if timestamp is not None else observation.timestamp,
            task_instruction=self.task_instruction,
            observation=observation,
            flexbe_context=flexbe_context,
            trigger=trigger,
            state_entry_image=state_entry_image,
            state_descriptions=dict(self.state_descriptions),
            history=list(self._history),
        )

    def evaluate(self, si: SupervisorInput, record_history: bool = True) -> EvaluationResult:
        if self.client is None:
            raise RuntimeError("VLM client is not configured")
        prompt = build_prompt(si, self.prompt_options, self.system_prompt)
        response = self.client.evaluate(prompt, build_context_dict(si, self.prompt_options))
        if response.ok:
            decision = parse_decision(response.text)
        else:
            decision = SupervisorDecision(valid=False, parse_error=f"request failed: {response.error}")
        result = EvaluationResult(input_timestamp=si.timestamp, trigger=si.trigger, prompt=prompt,
                                  response=response, decision=decision,
                                  flexbe_summary=flexbe_summary(si.flexbe_context))
        if record_history and decision.valid:
            self._history.append({
                "time": si.timestamp,
                "state": (si.flexbe_context.active_state_path if si.flexbe_context else None),
                "vlm_assessment": decision.assessment.value if decision.assessment else None,
                "reason": decision.reason,
            })
            self._history = self._history[-self._history_size:]
        return result

    def reset_history(self) -> None:
        """Behavior 変更時に呼ぶ."""
        self._history = []
