"""Tests for the pass/fail rule (station.py) and the latency log (latency_log.py). No hardware."""
import tempfile
from pathlib import Path

import latency_log
import station
from station import FAIL, NONE, PASS


def test_verdict_rule():
    expect = {"resistor": 2, "capacitor": 2}
    full = {"resistor": 2, "capacitor": 2, "total": 4}
    assert station.verdict(full, expect, "none")[0] == PASS
    assert station.verdict(full, expect, "not_learned")[0] == PASS
    assert station.verdict({"resistor": 1, "capacitor": 2, "total": 3}, expect, "none")[0] == FAIL
    assert station.verdict({"resistor": 3, "capacitor": 2, "total": 5}, expect, "none")[0] == FAIL
    assert station.verdict(full, expect, "present")[0] == FAIL  # unrecognised object
    assert station.verdict(None, expect, "none")[0] == NONE  # camera lost: safe state, never PASS


def test_station_score_and_false_pass_rate():
    with tempfile.TemporaryDirectory() as d:
        s = station.Station({"resistor": 1}, Path(d) / "station.csv")
        s.label("good", PASS, {"resistor": 1}, "")
        s.label("good", FAIL, {"resistor": 0}, "")
        s.label("bad", FAIL, {"resistor": 0}, "")
        s.label("bad", PASS, {"resistor": 1}, "")  # a false pass
        sc = s.score()
        assert sc["trays"] == 4 and sc["correct"] == 2
        assert sc["false_pass_rate"] == 0.5 and sc["false_fail_rate"] == 0.5
        assert len(station.Station({"resistor": 1}, Path(d) / "station.csv").rows) == 4  # survives restart
        try:
            s.label("good", NONE, None, "")
            raise AssertionError("labelled without a verdict")
        except ValueError:
            pass


def test_parse_expect():
    assert station.parse_expect("resistor=2, capacitor=1") == {"resistor": 2, "capacitor": 1}


def test_latency_log_and_percentiles():
    with tempfile.TemporaryDirectory() as d:
        log = latency_log.LatencyLog(Path(d) / "lat.csv")
        for i in range(20):
            log.record("resistor", i % 2 == 0, led_t=10 + i * 0.001 + 0.1, frame_t=10 + i * 0.001, detect_ms=40)
        assert log.record("resistor", True, led_t=5, frame_t=None) is None  # unknown cause: skipped
        s = log.summary()
        assert s["n"] == 20 and abs(s["median_ms"] - 100) < 0.2
        assert latency_log.summarise(latency_log.read_csv(Path(d) / "lat.csv"))["n"] == 20
    assert latency_log.percentile(list(range(1, 101)), 95) == 95
    assert latency_log.percentile([7], 95) == 7


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
