"""The indicator LEDs on the Pi's GPIO header: one for resistors, one for capacitors.

Normally an LED is lit while at least one part of its class is detected. blink_counts() plays a
count instead: the resistor LED blinks once per resistor, then the capacitor LED once per
capacitor, and afterwards the LEDs go back to showing presence. A small thread drives the pins,
so the dashboard never waits on them.

Wiring, per LED: GPIO pin -> 220 ohm resistor -> LED long leg; LED short leg -> a GND pin.
"""
import threading
import time

ON_S, OFF_S = 0.35, 0.35  # one blink
LEAD_S = 0.7  # dark before a count starts, so a lit LED doesn't swallow the first blink
GAP_S = 1.0  # extra dark between the resistor count and the capacitor count
MAX_BLINKS = 20
TICK_S = 0.02

# BCM GPIO number -> physical pin on the 40-pin header
HEADER_PIN = {2: 3, 3: 5, 4: 7, 17: 11, 27: 13, 22: 15, 10: 19, 9: 21, 11: 23, 0: 27, 5: 29, 6: 31,
              13: 33, 19: 35, 26: 37, 14: 8, 15: 10, 18: 12, 23: 16, 24: 18, 25: 22, 8: 24, 7: 26,
              1: 28, 12: 32, 16: 36, 20: 38, 21: 40}


def blink_schedule(counts, order):
    """On-intervals [(start s, end s, class), ...] for a count, and how long the whole count takes."""
    t, spans, started = LEAD_S, [], False
    for cls in order:
        n = min(int(counts.get(cls, 0)), MAX_BLINKS)
        if n <= 0:
            continue
        if started:
            t += GAP_S
        started = True
        for _ in range(n):
            spans.append((t, t + ON_S, cls))
            t += ON_S + OFF_S
    return spans, (t + LEAD_S if spans else 0.0)


def lit_at(spans, elapsed):
    return {cls for start, end, cls in spans if start <= elapsed < end}


class Leds:
    """leds: [(class, GPIO number, colour name), ...] in blink order. GPIO None leaves that LED out."""

    def __init__(self, leds, device=None):
        self.leds = [(cls, gpio, color) for cls, gpio, color in leds if gpio is not None]
        self.order = [cls for cls, _, _ in self.leds]
        self.devices, self.available, self.detail = {}, False, "No LEDs configured"
        if self.leds:
            try:
                if device is None:
                    from gpiozero import LED as device  # imported here so the tests run without GPIO
                for cls, gpio, _ in self.leds:
                    self.devices[cls] = device(gpio)
                self.available, self.detail = True, ""
            except Exception as e:  # no GPIO (not a Pi), pin busy, or no permission
                self.close()
                self.detail = f"{type(e).__name__}: {e}"
                print(f"LEDs unavailable: {self.detail}", flush=True)
        self.presence = {cls: False for cls in self.order}
        self.lit = {cls: False for cls in self.order}
        self.count = None  # (start time, spans, duration, counts) while a count is playing
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        if self.available:
            self._thread.start()

    def show(self, present):
        """present: {class: bool} (anything true lights that LED), or None for all off."""
        self.presence = {cls: bool(present and present.get(cls)) for cls in self.order}

    def blink_counts(self, counts):
        """Starts a count; returns its duration in seconds (0 if there is nothing to count)."""
        spans, duration = blink_schedule(counts, self.order)
        if not spans:
            return 0.0
        shown = {cls: min(int(counts.get(cls, 0)), MAX_BLINKS) for cls in self.order}
        self.count = (time.monotonic(), spans, duration, shown)
        return duration

    def cancel(self):
        self.count = None

    def _wanted(self, now):
        count = self.count
        if count is not None:
            start, spans, duration, _ = count
            if now - start < duration:
                on = lit_at(spans, now - start)
                return {cls: cls in on for cls in self.order}
            if self.count is count:
                self.count = None
        return dict(self.presence)

    def _run(self):
        while not self._stop.is_set():
            for cls, on in self._wanted(time.monotonic()).items():
                if on != self.lit[cls]:
                    try:
                        self.devices[cls].on() if on else self.devices[cls].off()
                        self.lit[cls] = on
                    except Exception as e:
                        self.available, self.detail = False, f"{type(e).__name__}: {e}"
                        print(f"LED {cls} failed: {self.detail}", flush=True)
                        return
            self._stop.wait(TICK_S)

    def state(self):
        count = self.count
        playing = None
        if count is not None:
            start, _, duration, shown = count
            left = duration - (time.monotonic() - start)
            if left > 0:
                playing = {"counts": shown, "left": round(left, 1)}
        return {
            "available": self.available,
            "detail": self.detail,
            "leds": [{"cls": cls, "ref": f"D{i + 1}", "gpio": gpio, "pin": HEADER_PIN.get(gpio), "color": color,
                      "lit": self.lit[cls]} for i, (cls, gpio, color) in enumerate(self.leds)],
            "count": playing,
        }

    def close(self):
        if hasattr(self, "_stop"):
            self._stop.set()
            if self._thread.is_alive():
                self._thread.join(timeout=1)
        for dev in self.devices.values():
            try:
                dev.off()
                dev.close()
            except Exception:
                pass
        self.devices = {}
