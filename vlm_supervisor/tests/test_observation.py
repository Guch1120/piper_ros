from vlm_supervisor.core.models import JointObservation, ObjectObservation, TransformObservation
from vlm_supervisor.core.observation import ObservationStore, summarize_observation

from .helpers import frame


def test_empty_snapshot_does_not_crash():
    obs = ObservationStore().snapshot(5.0)
    assert obs.image is None and obs.joint_state is None and obs.objects == [] and obs.meta == {}
    assert obs.to_dict()["image"] is None


def test_latest_only_and_age():
    s = ObservationStore()
    s.update_image(frame(9.0), received_time=9.1)
    s.update_image(frame(10.0), received_time=10.1)
    s.update_joint_state(JointObservation(timestamp=10.0, names=["j1"], positions=[0.5]), 10.05)
    obs = s.snapshot(10.5)
    assert obs.image.timestamp == 10.0
    m = obs.meta["image"]
    assert m.count == 2
    assert abs(m.age_source - 0.5) < 1e-9 and abs(m.age_received - 0.4) < 1e-9
    assert m.stale is None  # 閾値未設定
    assert obs.joint_state.positions == [0.5]


def test_stale_threshold_with_wildcard():
    s = ObservationStore({"image": 0.2, "tf/*": 1.0})
    s.update_image(frame(10.0), 10.0)
    s.update_transform("base", "cam", TransformObservation(None, "base", "cam", (0, 0, 1), (0, 0, 0, 1)), 10.0)
    obs = s.snapshot(10.5)
    assert obs.meta["image"].stale is True
    assert obs.meta["tf/base->cam"].stale is False  # stamp 無し -> received age 0.5 < 1.0


def test_tf_failure_keeps_last_value():
    s = ObservationStore()
    s.update_transform("base", "cam", None, 1.0, error="LookupException")
    obs = s.snapshot(1.0)
    assert obs.transforms == [] and obs.meta["tf/base->cam"].valid is False
    s.update_transform("base", "cam", TransformObservation(1.0, "base", "cam", (0, 0, 1), (0, 0, 0, 1)), 2.0)
    s.update_transform("base", "cam", None, 3.0, error="ExtrapolationException")
    obs = s.snapshot(3.0)
    assert len(obs.transforms) == 1
    assert obs.meta["tf/base->cam"].valid is False and "Extrapolation" in obs.meta["tf/base->cam"].error


def test_objects_and_snapshot_isolation():
    s = ObservationStore()
    s.update_objects("sam3", [ObjectObservation(source="sam3", timestamp=None, position=(1.0, 2.0, 3.0))], 1.0)
    obs = s.snapshot(1.0)
    obs.objects[0].label = "mutated"
    assert s.snapshot(1.0).objects[0].label is None
    assert summarize_observation(obs)["objects/sam3"]["count"] == 1


def test_report_error_without_value():
    s = ObservationStore()
    s.report_error("image", "ValueError: unsupported", 1.0)
    obs = s.snapshot(2.0)
    assert obs.image is None and obs.meta["image"].count == 0 and obs.meta["image"].age_received is None
