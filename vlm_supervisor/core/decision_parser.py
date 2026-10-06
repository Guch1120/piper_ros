"""VLM の自由テキスト応答 -> SupervisorDecision.

小型 VLM は ```json fence や前置きを付けがちなので, 最初の JSON object を寛容に抽出する.
不正な値は valid=False + parse_error にして呼び出し側で記録する (例外は投げない).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .models import Assessment, Intervention, SupervisorDecision

_ASSESSMENT_ALIASES = {
    "success": Assessment.SEMANTIC_SUCCESS,
    "semantic_success": Assessment.SEMANTIC_SUCCESS,
    "failure": Assessment.SEMANTIC_FAILURE,
    "fail": Assessment.SEMANTIC_FAILURE,
    "semantic_failure": Assessment.SEMANTIC_FAILURE,
    "in_progress": Assessment.IN_PROGRESS,
    "uncertain": Assessment.UNCERTAIN,
    "unknown": Assessment.UNCERTAIN,
}


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """text 中の最初の (バランスの取れた) JSON object を返す."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, dict):
                        return obj
                    break
        start = text.find("{", start + 1)
    return None


def parse_decision(text: str) -> SupervisorDecision:
    obj = extract_json_object(text or "")
    if obj is None:
        return SupervisorDecision(valid=False, parse_error="no JSON object found")

    errors = []
    assessment = None
    raw_a = obj.get("assessment")
    if raw_a is not None:
        assessment = _ASSESSMENT_ALIASES.get(str(raw_a).strip().lower())
        if assessment is None:
            errors.append(f"unknown assessment: {raw_a!r}")
    else:
        errors.append("missing assessment")

    confidence = None
    if "confidence" in obj:
        try:
            confidence = float(obj["confidence"])
            if not 0.0 <= confidence <= 1.0:
                errors.append(f"confidence out of range: {confidence}")
                confidence = min(max(confidence, 0.0), 1.0)
        except (TypeError, ValueError):
            errors.append(f"invalid confidence: {obj['confidence']!r}")

    intervention = None
    if obj.get("intervention") is not None:
        try:
            intervention = Intervention(str(obj["intervention"]).strip().upper())
        except ValueError:
            errors.append(f"unknown intervention: {obj['intervention']!r}")

    params = obj.get("parameters") if isinstance(obj.get("parameters"), dict) else {}
    return SupervisorDecision(
        valid=assessment is not None,
        assessment=assessment,
        reason=str(obj.get("reason", "")),
        confidence=confidence,
        intervention=intervention,
        next_skill=obj.get("next_skill"),
        parameters=params,
        parse_error="; ".join(errors) or None,
        raw_json=obj,
    )
