from vlm_supervisor.core.flexbe_context import FlexBEContextTracker, render_graph_text, state_checksum
from vlm_supervisor.core.models import BehaviorStatus, FlexBEEventType, UserdataEntry

from .helpers import STRUCTURE

BID = 123456


def started_tracker():
    t = FlexBEContextTracker()
    t.on_log("Onboard Behavior Engine starting [Pick Demo : 123456]", 0.5)
    t.on_start_request(BID, ["target"], ["cup"], 0.6)
    t.on_structure(BID, STRUCTURE, 0.9)
    t.on_status(0, BID, [], 1.0)
    return t


def test_behavior_start_name_inputs_graph():
    t = started_tracker()
    ctx = t.snapshot(3.0)
    assert ctx.status == BehaviorStatus.STARTED
    assert ctx.behavior_name == "Pick Demo" and ctx.behavior_id == BID
    assert ctx.behavior_inputs == {"target": "cup"}
    assert set(ctx.graph) == {s["path"] for s in STRUCTURE}
    assert ctx.elapsed_time == 2.0
    types = [e.type for e in t.drain_events()]
    assert FlexBEEventType.BEHAVIOR_CHANGED in types and FlexBEEventType.BEHAVIOR_STARTED in types
    assert t.drain_events() == []


def test_heartbeat_resolves_nested_state():
    t = started_tracker()
    t.drain_events()
    t.on_heartbeat(BID, state_checksum("/Grasp/Close"), 2.0)
    ctx = t.snapshot(2.5)
    assert ctx.active_state == "Close" and ctx.active_state_path == "/Grasp/Close"
    assert ctx.active_states == ["/Grasp"]
    assert ctx.available_outcomes == ["done"] and ctx.transitions == {"done": "Check"}
    assert ctx.state_elapsed_time == 0.5 and ctx.active_state_source == "heartbeat"
    ev = t.drain_events()
    assert ev[0].type == FlexBEEventType.STATE_ENTERED and ev[0].data["state_path"] == "/Grasp/Close"


def test_heartbeat_before_structure_is_resolved_later():
    t = FlexBEContextTracker()
    t.on_status(0, BID, [], 1.0)
    t.on_heartbeat(BID, state_checksum("/Approach"), 1.5)
    assert t.snapshot(1.5).unresolved_checksum == state_checksum("/Approach")
    t.on_structure(BID, STRUCTURE, 2.0)
    ctx = t.snapshot(2.0)
    assert ctx.active_state_path == "/Approach" and ctx.unresolved_checksum is None


def test_outcome_advances_active_state_and_records_transition():
    t = started_tracker()
    t.on_heartbeat(BID, state_checksum("/Grasp/Close"), 2.0)
    t.drain_events()
    t.on_state_result("/Grasp/Close > done", 3.0)
    ctx = t.snapshot(3.0)
    assert ctx.last_outcome.state_path == "/Grasp/Close" and ctx.last_outcome.target == "Check"
    assert ctx.active_state_path == "/Grasp/Check" and ctx.active_state_source == "outcome"
    types = [e.type for e in t.drain_events()]
    assert types == [FlexBEEventType.STATE_OUTCOME, FlexBEEventType.STATE_ENTERED]
    # 親 outcome への遷移は active を勝手に動かさない
    t.on_state_result("/Grasp/Check > ok", 4.0)
    assert t.snapshot(4.0).active_state_path == "/Grasp/Check"


def test_mirror_behavior_update_path_normalization():
    t = started_tracker()
    t.on_behavior_update("/Grasp_mirror/Check_mirror", 2.0)
    assert t.snapshot(2.0).active_state_path == "/Grasp/Check"
    t.on_behavior_update("/Unknown", 2.1)
    assert t.snapshot(2.1).active_state_path == "/Grasp/Check"


def test_behavior_change_resets_state_and_graph():
    t = started_tracker()
    t.on_heartbeat(BID, state_checksum("/Lift"), 2.0)
    t.on_userdata([UserdataEntry(state="Pick", key="target", type="str", data="cup")], 2.1)
    t.on_status(1, BID, [], 5.0)  # FINISHED
    assert t.snapshot(5.0).active_state_path is None
    t.on_status(0, 999, [], 6.0)  # 別 behavior
    ctx = t.snapshot(6.0)
    assert ctx.behavior_id == 999 and ctx.graph == {} and ctx.userdata == [] and ctx.behavior_name is None
    types = [e.type for e in t.drain_events()]
    assert FlexBEEventType.BEHAVIOR_FINISHED in types and types.count(FlexBEEventType.BEHAVIOR_CHANGED) == 2


def test_userdata_and_serialization():
    t = started_tracker()
    t.on_userdata([UserdataEntry(state="Pick", key="pose", type="list", data="[1, 2]")], 2.0)
    d = t.snapshot(2.0).to_dict()
    assert d["status"] == "STARTED" and d["userdata"][0]["key"] == "pose"
    assert "graph" not in t.snapshot(2.0).to_dict(include_graph=False)


def test_render_graph_text():
    t = started_tracker()
    text = render_graph_text(t.snapshot(1.0).graph)
    assert "/Approach: done -> Grasp, failed -> failed" in text
    assert "/Grasp [container]" in text and "    /Grasp/Check: ok -> grasped" in text


def test_checksum_matches_flexbe_formula():
    import zlib
    assert state_checksum("/A/B") == zlib.adler32(b"/A/B") & 0x7FFFFFFF
