"""End-to-end latency: from the camera frame that caused an LED change to the GPIO pin changing.

Every time an indicator LED switches, the dashboard writes one row to a CSV:

    wall_time, cls, led, frame_to_led_ms, detect_ms

`frame_to_led_ms` runs from the moment the frame reached the pipeline (FrameGrabber hands it over
within a few ms of the camera) to the moment the LED thread drove the pin. That covers the
detector, the tracker's debounce and the LED thread's 20 ms tick: the whole chain from picture
to actuator.

    python latency_log.py logs/latency.csv     # n, median, p95, max of the logged events
"""
import csv
import statistics
import sys
import threading
import time
from pathlib import Path

FIELDS = ["wall_time", "cls", "led", "frame_to_led_ms", "detect_ms"]


class LatencyLog:
    """Thread-safe CSV appender. path None keeps the events in memory only (tests)."""

    def __init__(self, path=None, keep=500):
        self.path = Path(path) if path else None
        self.keep = keep
        self.events = []  # recent rows, newest last, for the live KPI
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists() or self.path.stat().st_size == 0:
                with self.path.open("w", newline="") as f:
                    csv.writer(f).writerow(FIELDS)

    def record(self, cls, on, led_t, frame_t, detect_ms=None):
        """led_t and frame_t are time.monotonic() values. Ignored when the cause is unknown."""
        if frame_t is None or led_t < frame_t:
            return None
        row = {"wall_time": time.strftime("%Y-%m-%d %H:%M:%S"), "cls": cls, "led": "on" if on else "off",
               "frame_to_led_ms": round((led_t - frame_t) * 1000, 1),
               "detect_ms": "" if detect_ms is None else round(detect_ms, 1)}
        with self._lock:
            self.events = (self.events + [row])[-self.keep:]
            if self.path:
                with self.path.open("a", newline="") as f:
                    csv.DictWriter(f, FIELDS).writerow(row)
        return row

    def summary(self):
        with self._lock:
            return summarise([r["frame_to_led_ms"] for r in self.events])


def percentile(values, p):
    """Nearest-rank percentile, p in 0..100."""
    if not values:
        return None
    s = sorted(values)
    k = max(1, -(-p * len(s) // 100))  # ceil(p/100 * n), at least the first value
    return s[int(k) - 1]


def summarise(ms):
    if not ms:
        return {"n": 0, "median_ms": None, "p95_ms": None, "max_ms": None}
    return {"n": len(ms), "median_ms": round(statistics.median(ms), 1), "p95_ms": round(percentile(ms, 95), 1),
            "max_ms": round(max(ms), 1)}


def read_csv(path):
    with open(path, newline="") as f:
        return [float(r["frame_to_led_ms"]) for r in csv.DictReader(f) if r.get("frame_to_led_ms")]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python latency_log.py logs/latency.csv")
    s = summarise(read_csv(sys.argv[1]))
    print(f"events {s['n']}  median {s['median_ms']} ms  p95 {s['p95_ms']} ms  max {s['max_ms']} ms")
    if s["n"] < 20:
        print("Fewer than 20 events: place and remove parts until there are at least 20.")
