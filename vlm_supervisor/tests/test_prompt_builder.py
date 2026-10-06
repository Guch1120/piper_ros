from vlm_supervisor.core.flexbe_context import FlexBEContextTracker, state_checksum
from vlm_supervisor.core.models import JointObservation, UserdataEntry
from vlm_supervisor.core.observation import ObservationStore
from vlm_supervisor.core.prompt_builder import PromptOptions, build_context_dict, build_prompt
from vlm_supervisor.core.supervisor import Supervisor

from .helpers import STRUCTURE, frame


def make_input(with_entry=True):
    s = ObservationStore({"image": 0.1})
    s.update_image(frame(10.0), 10.0)
    s.update_joint_state(JointObservation(timestamp=10.0, names=["joint1"], positions=[0.12345]), 10.0)
    t = FlexBEContextTracker()
    t.on_log("Onboard Behavior Engine starting [Pick : 1]", 0.0)
    t.on_structure(1, STRUCTURE, 0.0)
    t.on_status(0, 1, [], 0.0)
    t.on_heartbeat(1, state_checksum("/Grasp/Close"), 5.0)
    t.on_state_result("/Grasp/Close > done", 9.0)
    t.on_userdata([UserdataEntry(state="Pick", key="target", type="str", data="x" * 1000)], 9.0)
    sup = Supervisor(task_instruction="pick up the cup",
                     state_descriptions={"/Grasp/Close": "Close the gripper around the target."})
    return sup.build_input(s.snapshot(10.5), t.snapshot(10.5), trigger="STATE_OUTCOME",
                           state_entry_image=frame(5.0) if with_entry else None)


def test_context_dict_contents():
    si = make_input()
    d = build_context_dict(si, PromptOptions(max_userdata_chars=50))
    fb = d["flexbe"]
    assert d["task_instruction"] == "pick up the cup"
    assert fb["behavior_name"] == "Pick" and fb["last_outcome"] == {"state_path": "/Grasp/Close", "outcome": "done",
                                                                     "next": "Check"}
    assert fb["state_descriptions"] == {"/Grasp/Close": "Close the gripper around the target."}
    assert len(fb["userdata"]["target"]) == 50
    assert d["robot_state"]["joint_positions"] == {"joint1": 0.123}
    assert d["robot_state"]["stale_inputs"] == ["image"]


def test_prompt_images_and_graph():
    p = build_prompt(make_input())
    assert len(p.images) == 2 and p.image_labels[0].startswith("image at the moment")
    assert "[1] image at the moment" in p.user_text and "Nominal behavior graph" in p.user_text
    assert '"assessment"' in p.system


def test_prompt_options_remove_parts():
    p = build_prompt(make_input(), PromptOptions(include_graph=False, include_state_entry_image=False,
                                                 include_userdata=False))
    assert len(p.images) == 1 and "Nominal behavior graph" not in p.user_text and '"userdata"' not in p.user_text


def test_prompt_without_image_or_flexbe():
    si = Supervisor().build_input(ObservationStore().snapshot(1.0))
    p = build_prompt(si)
    assert p.images == [] and "No camera image" in p.user_text
