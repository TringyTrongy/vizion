"""Checks for detector.balance_colours (no model needed). Run: python test_detector.py"""
import numpy as np

from detector import BALANCE_GAIN_LIMITS, balance_colours


def scene(bgr, seed=0):
    rng = np.random.default_rng(seed)
    img = np.full((480, 610, 3), bgr, np.float32) + rng.normal(0, 6, (480, 610, 3))
    return np.clip(img, 0, 255).astype(np.uint8)


def test_cyan_cast_is_removed():
    out = balance_colours(scene((188, 190, 136)))  # the bright-light cast measured on the Pi (B, G, R)
    means = out.reshape(-1, 3).mean(axis=0)
    assert means.max() - means.min() < 4, means
    assert out.shape == (480, 610, 3) and out.dtype == np.uint8


def test_neutral_scene_is_left_alone():
    img = scene((140, 140, 140))
    assert np.abs(balance_colours(img).astype(int) - img.astype(int)).max() <= 2


def test_gains_are_limited():
    img = scene((200, 40, 40))  # a frame filled by one strongly coloured object
    out = balance_colours(img).reshape(-1, 3).mean(axis=0)
    before = img.reshape(-1, 3).mean(axis=0)
    assert np.all(out <= before * BALANCE_GAIN_LIMITS[1] + 2) and np.all(out >= before * BALANCE_GAIN_LIMITS[0] - 2)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
