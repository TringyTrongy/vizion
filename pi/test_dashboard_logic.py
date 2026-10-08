"""Checks for dashboard_logic.py. Run: python test_dashboard_logic.py"""
import tempfile
from pathlib import Path

import cv2
import numpy as np

from dashboard_logic import Designators, EmptyTable, count_parts, describe_parts, zone

NAMES = {0: "resistor", 1: "capacitor"}
W, H = 610, 480


def test_zones_cover_the_3x3_grid():
    assert zone((0, 0, 20, 20), W, H) == ("A1", "Top-Left")
    assert zone((290, 0, 320, 20), W, H) == ("A2", "Top-Center")
    assert zone((590, 0, 610, 20), W, H) == ("A3", "Top-Right")
    assert zone((0, 230, 20, 250), W, H) == ("B1", "Center-Left")
    assert zone((295, 230, 315, 250), W, H) == ("B2", "Center")
    assert zone((450, 200, 520, 230), W, H) == ("B3", "Center-Right")
    assert zone((0, 460, 20, 480), W, H) == ("C1", "Bottom-Left")
    assert zone((295, 460, 315, 480), W, H) == ("C2", "Bottom-Center")
    assert zone((600, 470, 610, 480), W, H) == ("C3", "Bottom-Right")
    # The centre decides: a box straddling a line belongs where its middle is.
    assert zone((180, 100, 240, 130), W, H)[0] == "A2"


def test_designators_are_stable_and_reuse_free_numbers():
    d = Designators(NAMES)
    refs = d.update([(10, 0), (11, 0), (12, 1)])
    assert refs == {10: "R1", 11: "R2", 12: "C1"}
    refs = d.update([(11, 0), (12, 1)])  # R1 left the table
    assert refs == {11: "R2", 12: "C1"}, "remaining parts keep their designators"
    refs = d.update([(11, 0), (12, 1), (13, 0)])
    assert refs[13] == "R1", "a new part takes the lowest free number"
    refs = d.update([(11, 1), (12, 1), (13, 0)])  # part 11 now looks like a capacitor
    assert refs[11] == "C2" and refs[12] == "C1"


def test_parts_are_described_counted_and_ordered():
    tracks = [(5, 1, 0.81, 400, 50, 440, 90), (3, 0, 0.924, 100, 330, 160, 354), (4, 0, 0.5, 300, 220, 360, 244)]
    refs = Designators(NAMES).update(tracks)
    parts = describe_parts(tracks, NAMES, refs, W, H)
    assert [p["ref"] for p in parts] == ["R1", "R2", "C1"]
    assert parts[0] == {"ref": "R1", "cls": "resistor", "conf": 0.924, "box": [100, 330, 160, 354],
                        "zone": "C1", "where": "Bottom-Left"}
    assert count_parts(parts, NAMES) == {"resistor": 2, "capacitor": 1, "total": 3}
    assert count_parts([], NAMES) == {"resistor": 0, "capacitor": 0, "total": 0}


def table(seed=0):
    """A textured, light 'table' picture with sensor noise."""
    rng = np.random.default_rng(seed)
    base = np.full((H, W, 3), (170, 185, 195), np.float32)
    base += cv2.GaussianBlur(rng.normal(0, 25, (H, W, 1)).astype(np.float32), (0, 0), 6)[..., None]
    return np.clip(base + rng.normal(0, 3, base.shape), 0, 255).astype(np.uint8)


def settle(et, frame, boxes=()):
    for _ in range(EmptyTable.CONFIRM):
        et.check(frame, list(boxes))
    return et.state


def test_unrecognised_object_needs_a_learned_table():
    et = EmptyTable()
    assert settle(et, table()) == "not_learned"


def test_empty_table_has_nothing_unrecognised_despite_exposure_changes():
    et = EmptyTable()
    et.learn(table(0))
    assert settle(et, table(1)) == "none"
    brighter = np.clip(table(2).astype(np.float32) * 1.25 + 10, 0, 255).astype(np.uint8)
    assert settle(et, brighter) == "none", "auto-exposure changes must not look like objects"


def test_object_on_the_table_is_present_and_outlined():
    et = EmptyTable()
    et.learn(table(0))
    frame = table(1)
    cv2.rectangle(frame, (100, 100), (160, 150), (40, 40, 40), -1)
    assert settle(et, frame) == "present"
    (x1, y1, x2, y2), = et.boxes
    assert abs(x1 - 100) <= 8 and abs(y1 - 100) <= 8 and abs(x2 - 160) <= 8 and abs(y2 - 150) <= 8


def test_detected_parts_and_their_leads_are_not_unrecognised():
    et = EmptyTable()
    et.learn(table(0))
    frame = table(1)
    cv2.rectangle(frame, (300, 200), (360, 224), (90, 60, 30), -1)  # a resistor body
    cv2.line(frame, (240, 212), (300, 212), (200, 200, 200), 2)  # its leads
    cv2.line(frame, (360, 212), (420, 212), (200, 200, 200), 2)
    assert settle(et, frame, [(300, 200, 360, 224)]) == "none"
    assert settle(et, frame, []) == "present", "without the detection it is just an object"


def test_state_needs_confirmation_before_changing():
    et = EmptyTable()
    et.learn(table(0))
    obj = table(1)
    cv2.rectangle(obj, (100, 100), (160, 150), (40, 40, 40), -1)
    et.check(obj, [])
    assert et.state == "none", "one frame is not enough"
    settle(et, obj)
    assert et.state == "present"


def test_big_change_asks_to_relearn_and_reference_persists():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty.png"
        et = EmptyTable(path)
        et.learn(table(0))
        assert path.exists()
        again = EmptyTable(path)
        assert again.state == "none" and again.learned_at is not None
        assert settle(again, np.full((H, W, 3), 60, np.uint8)) == "relearn", "lens covered or lights off"
        again.forget()
        assert not path.exists() and settle(again, table(0)) == "not_learned"


def test_knocked_camera_asks_to_relearn():
    striped = table(0)  # a cutting mat with a printed grid
    for x in range(0, W, 40):
        cv2.rectangle(striped, (x, 0), (x + 14, H), (40, 50, 60), -1)
    et = EmptyTable()
    et.learn(striped)
    assert settle(et, striped) == "none"
    assert settle(et, np.roll(striped, 20, axis=1)) == "relearn"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
