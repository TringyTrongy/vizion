"""Checks for leds.py without any GPIO hardware. Run: python test_leds.py"""
import time

from leds import GAP_S, LEAD_S, MAX_BLINKS, ON_S, Leds, blink_schedule, lit_at

ORDER = ["resistor", "capacitor"]


class FakeLED:
    """Records every switch, like a gpiozero.LED would drive the pin."""

    def __init__(self, gpio):
        self.gpio, self.on_now, self.edges = gpio, False, []

    def on(self):
        self.on_now = True
        self.edges.append((time.monotonic(), True))

    def off(self):
        self.on_now = False
        self.edges.append((time.monotonic(), False))

    def close(self):
        pass


def test_schedule_blinks_resistors_then_capacitors():
    spans, duration = blink_schedule({"resistor": 3, "capacitor": 2}, ORDER)
    assert [c for _, _, c in spans] == ["resistor"] * 3 + ["capacitor"] * 2
    assert spans[0][0] == LEAD_S, "starts dark, so a lit LED doesn't hide the first blink"
    last_r, first_c = spans[2], spans[3]
    assert first_c[0] - last_r[1] >= GAP_S, "a clear pause between the two counts"
    assert all(abs((e - s) - ON_S) < 1e-9 for s, e, _ in spans)
    assert duration > spans[-1][1]
    assert lit_at(spans, spans[1][0] + 0.01) == {"resistor"}
    assert lit_at(spans, spans[1][1] + 0.01) == set()


def test_schedule_skips_absent_classes_and_caps_long_counts():
    spans, _ = blink_schedule({"resistor": 0, "capacitor": 2}, ORDER)
    assert [c for _, _, c in spans] == ["capacitor"] * 2
    assert spans[0][0] == LEAD_S, "no gap for a class with nothing to count"
    spans, _ = blink_schedule({"resistor": 50}, ORDER)
    assert len(spans) == MAX_BLINKS
    assert blink_schedule({"resistor": 0, "capacitor": 0}, ORDER) == ([], 0.0)


def make():
    return Leds([("resistor", 17, "red"), ("capacitor", 27, "yellow")], device=FakeLED)


def test_presence_lights_the_matching_led():
    leds = make()
    try:
        leds.show({"resistor": 2, "capacitor": 0})
        time.sleep(0.1)
        assert leds.devices["resistor"].on_now and not leds.devices["capacitor"].on_now
        leds.show(None)
        time.sleep(0.1)
        assert not any(d.on_now for d in leds.devices.values()), "detection off or no camera: all dark"
        s = leds.state()
        assert [(l["ref"], l["pin"], l["color"]) for l in s["leds"]] == [("D1", 11, "red"), ("D2", 13, "yellow")]
    finally:
        leds.close()


def test_count_blinks_exactly_then_returns_to_presence():
    leds = make()
    try:
        leds.show({"resistor": 1, "capacitor": 1})
        time.sleep(0.1)
        duration = leds.blink_counts({"resistor": 3, "capacitor": 2})
        assert leds.state()["count"]["counts"] == {"resistor": 3, "capacitor": 2}
        t0 = time.monotonic()
        time.sleep(duration + 0.2)
        for cls, n in (("resistor", 3), ("capacitor", 2)):
            rises = [t for t, on in leds.devices[cls].edges if on and t > t0]
            # n blinks, then the LED comes back on because the part is still there
            assert len(rises) == n + 1, (cls, len(rises))
        r_last = [t for t, on in leds.devices["resistor"].edges if on and t > t0][2]
        c_first = [t for t, on in leds.devices["capacitor"].edges if on and t > t0][0]
        assert c_first > r_last, "capacitor count comes after the resistor count"
        assert leds.state()["count"] is None
        assert all(d.on_now for d in leds.devices.values())
    finally:
        leds.close()


def test_missing_gpio_is_reported_not_fatal():
    def broken(_gpio):
        raise RuntimeError("no GPIO here")

    leds = Leds([("resistor", 17, "red")], device=broken)
    assert not leds.available and "no GPIO here" in leds.detail
    leds.show({"resistor": 1})
    assert leds.blink_counts({"resistor": 2}) > 0  # harmless: nothing drives pins
    leds.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
