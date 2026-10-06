from vlm_supervisor.core.decision_parser import extract_json_object, parse_decision
from vlm_supervisor.core.models import Assessment, Intervention


def test_plain_json():
    d = parse_decision('{"assessment": "semantic_failure", "reason": "beside the object", "confidence": 0.91,'
                       ' "intervention": "RECOVER"}')
    assert d.valid and d.assessment == Assessment.SEMANTIC_FAILURE and d.confidence == 0.91
    assert d.intervention == Intervention.RECOVER and d.parse_error is None


def test_fenced_with_preamble_and_braces_in_string():
    text = 'Sure!\n```json\n{"assessment": "success", "reason": "gripper {closed} on cup", "confidence": "0.8"}\n```'
    d = parse_decision(text)
    assert d.valid and d.assessment == Assessment.SEMANTIC_SUCCESS and d.confidence == 0.8
    assert d.reason == "gripper {closed} on cup"


def test_invalid_values_are_reported_not_raised():
    d = parse_decision('{"assessment": "maybe", "confidence": 3, "intervention": "dance"}')
    assert not d.valid and "unknown assessment" in d.parse_error
    assert d.confidence == 1.0 and "out of range" in d.parse_error and "unknown intervention" in d.parse_error


def test_no_json():
    d = parse_decision("I cannot tell.")
    assert not d.valid and d.parse_error == "no JSON object found"


def test_extract_skips_broken_object():
    assert extract_json_object('{broken {"a": 1}') == {"a": 1}
    assert extract_json_object("[1, 2]") is None
