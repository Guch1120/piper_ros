from vlm_supervisor.core.models import ImageFrame

# JPEG magic だけ持つダミー (中身はデコードしない)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


def frame(ts=10.0):
    return ImageFrame(timestamp=ts, frame_id="camera", width=1, height=1, mime_type="image/jpeg", data=JPEG)


# FlexBE structure: /Approach -> /Grasp(container: /Grasp/Close -> /Grasp/Check) -> /Lift
STRUCTURE = [
    {"path": "", "children": ["Approach", "Grasp", "Lift"], "outcomes": ["finished", "failed"]},
    {"path": "/Approach", "outcomes": ["done", "failed"], "transitions": ["Grasp", "failed"]},
    {"path": "/Grasp", "children": ["Close", "Check"], "outcomes": ["grasped", "failed"],
     "transitions": ["Lift", "failed"]},
    {"path": "/Grasp/Close", "outcomes": ["done"], "transitions": ["Check"]},
    {"path": "/Grasp/Check", "outcomes": ["ok", "ng"], "transitions": ["grasped", "failed"]},
    {"path": "/Lift", "outcomes": ["done"], "transitions": ["finished"]},
]
