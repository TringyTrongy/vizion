"""Checks for the sensor monitor and the fan. No sensor, GPIO or network needed: python test_sensor_monitor.py"""
import csv
import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
from argparse import Namespace
from datetime import datetime, timedelta
from pathlib import Path

import datasets
import export_csv
from anomaly_detector import (ANOMALY, DHT11, NORMAL, SENSOR_ERROR, AlertLog, AnomalyDetector, reason_kind)
from sensor_reader import Dht11Error, Reading, SimulatedDht11, decode_dht11, encode_dht11

T0 = datetime(2026, 10, 9, 12, 0, 0)


def readings(values, start=T0, step=2.0):
    """[(temp, humidity) or None] -> Readings every `step` s; None is a failed read."""
    out = []
    for i, v in enumerate(values):
        t = start + timedelta(seconds=i * step)
        out.append(Reading(t, error="No reply") if v is None else Reading(t, *v))
    return out


def run(values, profile=DHT11):
    det, log = AnomalyDetector(profile), AlertLog(profile)
    results = []
    for r in readings(values):
        a = det.update(r)
        log.update(r.timestamp, a)
        results.append(a)
    return results, log, det


def steady(n, t=24.0, h=50.0):
    return [(t + (0.1 if i % 3 == 0 else 0.0), h + (1 if i % 4 == 0 else 0)) for i in range(n)]


# --- DHT11 decoding ---------------------------------------------------------------------------

def test_decode_round_trip():
    for h, t in [(55, 24.3), (20, 0.0), (90, 50.0), (63, 31.9)]:
        assert decode_dht11(encode_dht11(h, t)) == (h, t)


def test_decode_negative_temperature():
    assert decode_dht11(encode_dht11(40, -3.5)) == (40, -3.5)


def test_decode_without_preamble_and_with_release_edge():
    edges = encode_dht11(48, 22.1, preamble=False)
    assert decode_dht11(edges) == (48, 22.1)
    # the host releasing the line adds a short high pulse first; it must be ignored
    assert decode_dht11([(-40_000, 1), (-10_000, 0)] + encode_dht11(48, 22.1)) == (48, 22.1)


def test_decode_errors():
    for edges, words in [([], "No reply"), ([(0, 1)], "No reply"),
                         (encode_dht11(55, 24.0)[:-30], "Incomplete")]:
        try:
            decode_dht11(edges)
        except Dht11Error as e:
            assert words in str(e), e
        else:
            raise AssertionError("expected an error")
    edges = encode_dht11(55, 24.0)
    i = next(i for i, (t, lv) in enumerate(edges) if i > 4 and lv == 1)  # flip one bit: lengthen a high
    t_rise, t_fall = edges[i][0], edges[i + 1][0]
    longer = t_fall - t_rise < 40_000
    shift = 43_000 if longer else -43_000
    bad = edges[:i + 1] + [(t + shift, lv) for t, lv in edges[i + 1:]]
    try:
        decode_dht11(bad)
    except Dht11Error as e:
        assert "checksum" in str(e)
    else:
        raise AssertionError("expected a checksum error")


# --- Detector ---------------------------------------------------------------------------------

def test_steady_room_is_normal_and_learns_first():
    results, log, _ = run(steady(80))
    assert all(a.status == NORMAL for a in results)
    assert results[0].learning and not results[-1].learning
    assert len(log.alerts) == 0


def test_spike_is_an_anomaly_with_a_reason():
    results, log, _ = run(steady(60) + [(30.0, 50.0)] * 3 + steady(10))
    a = results[60]
    assert a.status == ANOMALY
    assert any(r.startswith("Temperature 30.0 °C is") and "above the recent average" in r for r in a.reasons), a.reasons
    assert any("rose" in r for r in a.reasons), a.reasons
    assert len(log.alerts) == 1 and log.alerts[0].kind == ANOMALY and log.alerts[0].end is not None


def test_one_odd_reading_does_not_raise_an_alert():
    results, log, _ = run(steady(60) + [(30.0, 50.0)] + steady(10))
    assert results[60].status == ANOMALY  # logged as unusual
    assert len(log.alerts) == 0  # but DHT11.confirm = 2


def test_limits_fire_even_while_learning():
    results, _, _ = run([(24.0, 50.0)] * 5 + [(24.0, 95.0)])
    assert results[-1].status == ANOMALY
    assert any("above the 90% limit" in r for r in results[-1].reasons), results[-1].reasons


def test_failed_and_impossible_readings_are_sensor_errors():
    results, log, _ = run(steady(40) + [None, None] + steady(5))
    assert results[40].status == SENSOR_ERROR
    assert len(log.alerts) == 0  # two failures in a row: below error_confirm
    results, log, _ = run(steady(40) + [None] * 4 + steady(10))
    assert len(log.alerts) == 1 and log.alerts[0].kind == SENSOR_ERROR and log.alerts[0].end
    results, _, _ = run(steady(10) + [(24.0, 0.0)])
    assert results[-1].status == SENSOR_ERROR and "Impossible humidity" in results[-1].reasons[0]


def test_anomalies_stay_out_of_the_baseline():
    _, _, det = run(steady(60) + [(35.0, 50.0)] * 20)
    mean, _ = det.states["temperature_c"].baseline.stats()
    assert mean < 24.2, mean


def test_a_lasting_change_becomes_the_new_normal():
    results, log, det = run(steady(60) + [(28.0, 50.0)] * (DHT11.relearn_after + 40))
    assert results[61].status == ANOMALY
    assert results[-1].status == NORMAL, results[-1].reasons
    assert det.notes and "new level" in det.notes[0][1]
    assert log.alerts[0].end is not None


def test_alert_kind_change_and_reason_grouping():
    results, log, _ = run(steady(60) + [(30.0, 50.0)] * 3 + [None] * 4 + steady(10))
    kinds = [a.kind for a in log.alerts]
    assert kinds == [ANOMALY, SENSOR_ERROR], kinds
    assert reason_kind("Temperature 31.0 °C is 4.2σ above the recent average of 24.0 °C") == \
        reason_kind("Temperature 29.5 °C is 6.0σ above the recent average of 24.1 °C")


# --- Simulator --------------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def test_simulator_is_quiet_then_reacts_to_events():
    clock = Clock()
    sim = SimulatedDht11(seed=1, auto_events=False, clock=clock)
    base = []
    for _ in range(60):
        clock.t += 2
        r = sim.read()
        assert r.error is None and r.humidity_percent == round(r.humidity_percent)
        base.append(r.temperature_c)
    assert 25 < min(base) and max(base) < 27
    sim.inject("heat")
    clock.t += 60
    assert sim.read().temperature_c > max(base) + 5
    sim.inject("fault")
    clock.t += 2
    assert sim.read().error


def test_simulated_heat_spike_is_detected():
    clock = Clock()
    sim = SimulatedDht11(seed=2, auto_events=False, clock=clock)
    det, log = AnomalyDetector(DHT11), AlertLog(DHT11)
    for i in range(200):
        clock.t += 2
        if i == 100:
            sim.inject("heat")
        r = sim.read()
        log.update(r.timestamp, det.update(r))
    assert [a.kind for a in log.alerts] == [ANOMALY], [(a.kind, a.reasons) for a in log.alerts]


# --- CSV log and export -----------------------------------------------------------------------

def test_recorder_and_export():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        rec = export_csv.Recorder("live", folder)
        det = AnomalyDetector(DHT11)
        rs = readings(steady(5) + [None], start=datetime(2026, 10, 9, 23, 59, 52))
        for r in rs:
            rec.write(export_csv.make_row(r, det.update(r), "dht11"))
        rec.close()
        files = sorted(p.name for p in folder.iterdir())
        assert files == ["live-2026-10-09.csv", "live-2026-10-10.csv"], files
        with open(folder / files[0], newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert list(rows[0]) == export_csv.COLUMNS
        assert rows[0]["anomaly_status"] == "NORMAL" and rows[0]["source"] == "dht11"
        all_rows = list(export_csv.read_log("live", folder=folder))
        assert len(all_rows) == 6 and all_rows[-1]["anomaly_status"] == SENSOR_ERROR
        assert all_rows[-1]["temperature_c"] == "" and all_rows[-1]["alert_reason"] == "No reply"
        late = list(export_csv.read_log("live", datetime(2026, 10, 10), folder=folder))
        assert len(late) == 2
        text, count = export_csv.to_csv(all_rows)
        assert count == 6 and text.startswith(",".join(export_csv.COLUMNS))


# --- Public data and the server ---------------------------------------------------------------

def test_public_datasets_if_downloaded():
    if not datasets.local("machine").exists():
        print("   (NAB files not downloaded: skipped; run python datasets.py)")
        return
    rows = datasets.load_series("machine")
    assert len(rows) == 22695 and len(datasets.load_windows("machine")) == 4
    c = datasets.load_celsius("machine")
    assert abs(c[0][1] - (rows[0][1] - 32) * 5 / 9) < 1e-9 and c[0][0] == rows[0][0]
    assert len(datasets.load_series("ambient")) == 7267


class TestServer:
    """The dashboard on a free port, with a simulated DHT11 and no GPIO. Logs go to a temporary folder."""

    def __init__(self):
        import sensor_dashboard as sd
        from http.server import ThreadingHTTPServer

        self.sd = sd
        self.began = time.time() - 1
        self.tmp = tempfile.TemporaryDirectory()
        folder = Path(self.tmp.name)
        self.saved = sd.Recorder, sd.read_log, sd.SETTINGS
        sd.Recorder = lambda name, **kw: export_csv.Recorder(name, folder, **kw)  # keep test rows out of data/log
        sd.read_log = lambda name, start=None, end=None: export_csv.read_log(name, start, end, folder=folder)
        sd.SETTINGS = folder / "fan_settings.json"
        self.app = sd.App(Namespace(dht11="sim", gpio=4, motor="none", leds="off", replay_speed=200))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), sd.Handler)
        self.server.app = self.app
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.read(), r.headers

    def state(self, stream):
        return json.loads(self.get(f"/api/state?stream={stream}")[0])

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def close(self):
        self.server.shutdown()
        self.app.close()
        self.sd.Recorder, self.sd.read_log, self.sd.SETTINGS = self.saved
        for p in export_csv.EXPORTS.glob("vizion-*.csv"):  # the exports made by the tests
            if p.stat().st_mtime >= self.began:
                p.unlink()
        self.tmp.cleanup()


def test_server_smoke():
    t = TestServer()
    try:
        assert b"Vizion Sense" in t.get("/")[0]
        assert t.get("/static/sensor.css")[1]["Content-Type"].startswith("text/css")
        state = t.state("live")
        assert state["stream"] == "live" and state["meta"]["simulated"]
        keys = [s["key"] for s in state["streams"]]
        assert keys[:2] == ["live", "motor"] and "simulated" not in keys, keys
        assert state["streams"][0]["tag"] == "SIM"
        if "machine" in t.app.streams:
            time.sleep(0.3)
            state = t.state("machine")
            assert state["meta"]["kind"] == "replay" and len(state["meta"]["windows"]) == 4
            text = t.get("/api/export.csv?stream=machine&range=all")[0].decode()  # replays export value + unit
            assert text.startswith("timestamp,temperature_c,dataset_value,dataset_unit,"), text[:60]
            assert ",°F (assumed)," in text.splitlines()[1]
        time.sleep(2.3)  # the DHT11 is read every 2 s
        body, headers = t.get("/api/export.csv?stream=live&range=all")
        assert body.decode().startswith("timestamp,") and int(headers["X-Rows"]) >= 1
        assert "simulated" in Path(headers["X-Saved-To"]).name  # never filed as real readings
        try:
            t.get("/static/../sensor_dashboard.py")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        t.close()


def test_pause_reset_and_session_export():
    t = TestServer()
    try:
        # Pause stops a stream reading; resume starts it again (the machine replay reads every 5 ms).
        if "machine" in t.app.streams:
            replay = t.app.stream("machine")
            time.sleep(0.3)
            assert t.post("/api/pause", {"stream": "machine", "paused": True})["paused"] is True
            time.sleep(0.1)
            seq = replay.seq
            time.sleep(0.3)
            assert replay.seq == seq, "a paused stream must not read"
            assert t.state("machine")["paused"]
            t.post("/api/pause", {"stream": "machine", "paused": False})
            time.sleep(0.3)
            assert replay.seq > seq

        # Reset: fresh history, counts, alerts and baseline, a new epoch; the log on disk stays.
        live = t.app.streams["live"]
        live.set_paused(True)  # keep the background reader out of the counts below
        time.sleep(0.3)
        before = datetime.now() - timedelta(minutes=10)
        for r in readings(steady(40) + [(30.0, 50.0)] * 3, start=before):
            live.ingest(r)
        assert live.counts["readings"] >= 43 and live.counts["flagged"] >= 3 and len(live.alerts.alerts) == 1
        epoch = live.epoch
        result = t.post("/api/reset", {"stream": "live"})
        assert result["ok"] and "log on the Pi is kept" in result["message"]
        assert live.epoch == epoch + 1 and live.counts == {"readings": 0, "flagged": 0, "failed": 0}
        assert len(live.history) == 0 and len(live.alerts.alerts) == 0 and live.seq == 0
        assert len(live.detector.states["temperature_c"].baseline) == 0
        for r in readings(steady(3), start=datetime.now() + timedelta(seconds=2)):
            live.ingest(r)
        _, all_count, _ = t.app.export("live", "all")
        _, session_count, _ = t.app.export("live", "session")
        assert all_count >= 46 and session_count == 3, (all_count, session_count)
        # The fan can't be paused or reset; it says why.
        assert not t.post("/api/pause", {"stream": "motor", "paused": True})["ok"]
    finally:
        t.close()


def test_fan_buttons_and_log():
    t = TestServer()
    try:
        motor = t.app.streams["motor"]
        r = t.post("/api/fan", {"action": "mode", "mode": "hand"})
        assert r["ok"] and "Hand" in r["message"]
        assert t.state("motor")["current"]["running"]
        r = t.post("/api/fan", {"action": "stop"})
        s = t.state("motor")
        assert r["ok"] and s["status"] == "SHUT DOWN" and s["current"]["trip"]["check"] == "estop"
        assert s["alerts"][0]["kind"] == "SHUTDOWN" and s["alerts"][0]["end"] is None
        r = t.post("/api/fan", {"action": "restart"})
        assert r["ok"] and t.state("motor")["status"] == "RUNNING"
        r = t.post("/api/fan", {"action": "levels", "on_at": 80, "off_at": 79})
        assert not r["ok"] and "below the ON level" in r["message"]
        assert t.post("/api/fan", {"action": "levels", "on_at": 80, "off_at": 72})["ok"]
        assert json.loads(t.sd.SETTINGS.read_text()) == {"mode": "hand", "on_at": 80, "off_at": 72}
        t.post("/api/fan", {"action": "mode", "mode": "off"})
        motor.tick()
        text, count, path = t.app.export("motor", "all")
        path.unlink()
        rows = list(csv.DictReader(text.splitlines()))
        assert list(rows[0]) == export_csv.MOTOR_COLUMNS
        events = " | ".join(r["event"] for r in rows)
        assert "SHUT DOWN: Emergency stop" in events and "Mode: Off" in events, events
        assert rows[-1]["fan"] == "stopped" and rows[-1]["mode"] == "off"
    finally:
        t.close()


# --- The fan controller -----------------------------------------------------------------------

def fan(**settings):
    from fan_control import FanController, NoOutputs
    return FanController(NoOutputs(), settings)


def feed(f, humidities, start=0, step=2, sensor="ok"):
    """Feed one humidity every `step` s from second `start`; returns the second after the last."""
    for i, h in enumerate(humidities):
        f.update(T0 + timedelta(seconds=start + i * step), h, sensor, 1)
    return start + len(humidities) * step


def test_fan_switches_with_a_gap_between_on_and_off():
    f = fan()
    assert (f.on_at, f.off_at, f.mode) == (75, 70, "auto")
    feed(f, [65, 74])
    assert f.state == "STANDBY" and not f.running
    feed(f, [75], 4)
    assert f.running and "reached the 75% ON level" in f.why
    feed(f, [73, 71], 6)
    assert f.running, "between the levels a running fan keeps running"
    feed(f, [70], 10)
    assert not f.running and f.state == "STANDBY"
    feed(f, [72], 12)
    assert not f.running, "between the levels a stopped fan stays stopped"
    run = f.timeline()[0]
    assert run["kind"] == "RUN" and run["end"] and run["reasons"][1] == "Humidity 70% fell to the 70% OFF level"


def test_fan_sweeps_while_running_and_parks_when_stopped():
    import fan_control as fc
    f = fan(mode="hand")
    feed(f, [60])
    t = f.sweep_t0
    pulses = [f.pulse_now(t + i * 0.1) for i in range(30)]
    assert min(pulses) <= fc.MIDDLE_US - 400 and max(pulses) >= fc.MIDDLE_US + 400
    assert all(fc.MIDDLE_US - fc.SWEEP_US <= p <= fc.MIDDLE_US + fc.SWEEP_US for p in pulses)
    f.set_mode("off", T0 + timedelta(seconds=3))
    now = time.monotonic()
    assert f.pulse_now(now) == fc.MIDDLE_US and f.pulse_now(now + fc.PARK_S + 0.1) == 0


def test_no_effect_shuts_the_fan_down_until_restart():
    f = fan()
    t = feed(f, [80] * 30)  # a hand around the sensor: 58 s of running, humidity not falling
    assert f.running
    feed(f, [82], t)
    assert f.state == "SHUT DOWN" and f.trip["check"] == "effect" and not f.running
    assert "did not come down (80% → 82%)" in f.trip["reason"]
    feed(f, [60, 60], t + 2)
    assert f.state == "SHUT DOWN", "a shutdown stays until Restart"
    ok, message = f.restart(T0 + timedelta(seconds=t + 10))
    assert ok and f.state == "STANDBY" and f.trip is None
    assert f.counts == {"starts": 1, "shutdowns": 1}
    kinds = [e["kind"] for e in f.timeline()]
    assert kinds == ["SHUTDOWN", "RUN"] and f.timeline()[0]["end"] is not None


def test_a_fan_that_helps_is_left_alone():
    f = fan()
    feed(f, [80] * 5 + [79] * 30)  # falling slowly, 70 s of running
    assert f.running and not f.trip


def test_short_cycling_shuts_down_on_the_fourth_start():
    f = fan()
    t = 0
    for _ in range(3):
        t = feed(f, [76, 69], t, step=10)
    assert f.counts["starts"] == 3 and not f.trip
    assert next(c for c in f.snapshot(T0 + timedelta(seconds=t))["checks"] if c["key"] == "cycling")["state"] == "watch"
    feed(f, [76], t, step=10)
    assert f.trip and f.trip["check"] == "cycling" and f.counts["starts"] == 3
    f.restart(T0 + timedelta(seconds=t + 5))
    feed(f, [76], t + 10)
    assert f.running and not f.trip, "Restart forgets the earlier starts"
    f2 = fan()  # starts spread over more than 3 minutes are fine
    t = 0
    for _ in range(5):
        t = feed(f2, [76, 69], t, step=40)
    assert f2.counts["starts"] == 5 and not f2.trip


def test_losing_the_sensor_shuts_auto_down():
    f = fan()
    feed(f, [76])
    feed(f, [76], 2, sensor="failing")  # one failed read: keep going on the last good value
    assert f.running and not f.trip
    feed(f, [None], 4, sensor="error")
    assert f.trip["check"] == "sensor" and not f.running
    ok, message = f.restart(T0 + timedelta(seconds=6))
    assert not ok and "still not answering" in message
    f.set_mode("hand", T0 + timedelta(seconds=7))
    ok, _ = f.restart(T0 + timedelta(seconds=8))
    assert ok and f.running, "Hand doesn't need the sensor"
    f2 = fan(mode="off")
    feed(f2, [None], sensor="error")
    assert not f2.trip


def test_under_voltage_and_emergency_stop():
    f = fan(mode="hand")
    f.update(T0, None, "ok", None, 5.14, False)
    assert f.running and not f.trip
    f.update(T0 + timedelta(seconds=1), None, "ok", None, 4.62, True)
    assert f.trip["check"] == "power"
    ok, message = f.restart(T0 + timedelta(seconds=2))
    assert not ok and "under-voltage" in message
    f.update(T0 + timedelta(seconds=3), None, "ok", None, 5.1, False)
    assert f.restart(T0 + timedelta(seconds=4))[0] and f.running
    f.emergency_stop(T0 + timedelta(seconds=5))
    assert f.trip["check"] == "estop" and not f.running
    assert f.snapshot(T0 + timedelta(seconds=6))["checks"][-1]["key"] == "estop"


def test_levels_are_checked_and_kept():
    f = fan()
    for on, off in [(96, 70), (75, 74), (75, 20)]:
        try:
            f.set_levels(on, off)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {on}/{off}")
    f.set_levels(80, 72)
    assert (f.on_at, f.off_at) == (80, 72)
    assert fan(on_at=99, off_at=10).on_at == 75, "bad saved levels fall back to the defaults"
    assert fan(mode="nonsense").mode == "auto"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
