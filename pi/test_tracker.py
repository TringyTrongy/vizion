"""Checks for tracker.py. Run: python pi/test_tracker.py"""
import random

import numpy as np

from tracker import Tracker

R, C = 0, 1


def det(cls, conf, x, y, w=60, h=24):
    return (cls, conf, x, y, x + w, y + h)


def test_jitter_is_smoothed_and_never_blinks():
    random.seed(0)
    t, xs, shown = Tracker(2), [], []
    for _ in range(100):
        t.update([det(R, random.uniform(0.45, 0.75), 200 + random.uniform(-4, 4), 100 + random.uniform(-4, 4))])
        v = t.visible()
        shown.append(len(v))
        if v:
            xs.append(v[0][2])
    assert shown[2:] == [1] * 98, "part should stay visible every frame once shown"
    assert np.std(xs[5:]) < 2.0, f"box jitter not smoothed: std {np.std(xs[5:]):.2f}px (raw ~2.3px)"


def test_survives_missed_frames():
    """Detected ~70% of frames with gaps of up to 4 misses: must never blink.
    (5+ misses in a row is how a removed part looks; see test_removed_part_disappears_quickly.)"""
    random.seed(1)
    t, shown, streak = Tracker(2), [], 0
    for i in range(300):
        hit = random.random() < 0.7 or streak == 4
        streak = 0 if hit else streak + 1
        t.update([det(C, 0.55, 300, 200)] if hit else [])
        shown.append(bool(t.visible()))
    assert all(shown[10:]), "part blinked out during short detection gaps"


def test_single_frame_false_positive_not_shown():
    t = Tracker(2)
    t.update([det(R, 0.5, 50, 50)])
    seen = bool(t.visible())
    for _ in range(5):
        t.update([])
        seen |= bool(t.visible())
    assert not seen, "a one-frame 0.5 detection should not be drawn"


def test_class_flicker_keeps_one_box_with_majority_label():
    t = Tracker(2)
    for i in range(30):
        t.update([det(C, 0.55, 100, 100)] if i % 3 else [det(R, 0.45, 101, 99)])
        v = t.visible()
        if i > 3:
            assert len(v) == 1 and v[0][0] == C, f"frame {i}: {v}"


def test_same_frame_duplicates_merge():
    t = Tracker(2)
    for _ in range(3):
        t.update([det(R, 0.5, 100, 100), det(C, 0.45, 102, 101)])
    assert len(t.visible()) == 1


def test_removed_part_disappears_quickly():
    t = Tracker(2)
    for _ in range(10):
        t.update([det(R, 0.7, 100, 100)])
    gone_after = next(i for i in range(1, 20) if not (t.update([]) or t.visible()))
    assert gone_after <= 5, f"took {gone_after} empty frames to disappear"


def test_moving_part_is_followed():
    t = Tracker(2)
    for i in range(40):
        t.update([det(C, 0.7, 100 + 8 * i, 100)])  # 8 px per detection ~ brisk hand movement
    (_, _, x1, *_), = t.visible()
    assert abs(x1 - (100 + 8 * 39)) <= 10, f"box lags {100 + 8 * 39 - x1}px behind"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
