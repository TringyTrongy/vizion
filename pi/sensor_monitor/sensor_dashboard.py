"""Vizion Sense: the DHT11 and fan dashboard, with anomaly detection and safety shutdowns.

    .venv/bin/python sensor_monitor/sensor_dashboard.py            # then open http://127.0.0.1:8766/
    .venv/bin/python sensor_monitor/sensor_dashboard.py --dht11 sim   # no sensor: simulated DHT11 (development)

Four streams run side by side, each with its own history:

- live       the DHT11 on GPIO4, read every 2 s and logged to data/log/live-YYYY-MM-DD.csv
- motor      the fan (the SG90 servo on GPIO18), switched by the DHT11's humidity and shut down by
             its safety checks (fan_control.py); logged every second to data/log/motor-....csv
- machine    replay of the NAB industrial machine temperature dataset (public data)
- ambient    replay of the NAB office temperature dataset (public data)

The page chooses which one to show. The DHT11 and the replays can be paused or reset (the chart,
alerts, counts and baseline; the CSV logs on disk are kept); the fan has its own buttons. Separate
from the camera dashboard (port 8765) and its model, but it shares the two LEDs with it: whichever
starts first gets them. Standard library only, plus lgpio for the sensor, the servo and the LEDs.
"""
import argparse
import json
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from itertools import islice
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import datasets
import fan_control
from anomaly_detector import DHT11, PROFILES, SENSOR_ERROR, AlertLog, AnomalyDetector
from export_csv import COLUMNS, MOTOR_COLUMNS, REPLAY_COLUMNS, Recorder, make_row, read_log, save_export, to_csv
from fan_control import FanController, load_settings, read_power
from sensor_reader import DHT11_GPIO, Reading, ReplaySource, SimulatedDht11, open_dht11

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
SETTINGS = HERE / "data" / "fan_settings.json"
HISTORY = 43200  # readings kept in memory per stream: 24 h at one every 2 s
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".woff2": "font/woff2", ".svg": "image/svg+xml",
                 ".txt": "text/plain; charset=utf-8", ".csv": "text/csv; charset=utf-8"}
STATUS_CODE = {"NORMAL": "N", "ANOMALY": "A", "SENSOR ERROR": "E"}
SENSOR_STATS = [{"key": "readings", "label": "Readings"}, {"key": "flagged", "label": "Flagged"},
                {"key": "failed", "label": "Failed reads"}, {"key": "anomaly_alerts", "label": "Anomaly alerts"}]


def iso(t):
    return t.strftime("%Y-%m-%d %H:%M:%S")


class Stream:
    """One source of readings with its own detector, alert log and history."""

    columns = COLUMNS  # of its CSV export
    tag = ""  # next to its name in the page's navigation

    def __init__(self, key, title, kind, profile, interval_s, chart_points, badge, about,
                 source_label, record=None):
        self.key, self.title, self.kind = key, title, kind
        self.profile = profile
        self.interval_s = interval_s
        self.chart_points = chart_points
        self.badge, self.about = badge, about
        self.source_label = source_label  # the CSV `source` column
        self.recorder = Recorder(record) if record else None  # record: the log's name
        self.lock = threading.Lock()  # guards the state below
        self.step = threading.Lock()  # one read-and-assess at a time; seek() waits for it
        self.thread = None
        self.stop_event = threading.Event()
        self.source = None
        self.method = None
        self.started = None
        self.paused = False
        self.epoch = 0  # goes up on every reset, so the page knows to drop what it has drawn
        self.reset()

    def reset(self):
        with self.lock:
            self.epoch += 1
            self.session_start = datetime.now()
            self.detector = AnomalyDetector(self.profile)
            self.alerts = AlertLog(self.profile)
            self.history = deque(maxlen=HISTORY)  # (seq, reading, assessment)
            self.seq = 0
            self.counts = {"readings": 0, "flagged": 0, "failed": 0}
            self.last = None
            self.last_good = None  # the newest reading that has values (the fan uses its humidity)
            self.last_event = None

    # --- sources -------------------------------------------------------------------------
    def open_source(self):
        raise NotImplementedError

    def next_reading(self):
        return self.source.read()

    def clear(self):
        """Reset readings from the page: a fresh chart, alerts, counts and baseline. Logs are kept."""
        with self.step:
            self.reset()

    def set_paused(self, paused):
        self.paused = bool(paused)

    def start(self):
        if self.thread:
            return
        self.started = datetime.now()
        self.thread = threading.Thread(target=self._run, name=f"stream-{self.key}", daemon=True)
        self.thread.start()

    def _run(self):
        if self.kind != "replay":  # read just after a whole second, so the logged times step evenly
            time.sleep((1.1 - time.time() % 1) % 1)
        next_at = time.monotonic()
        while not self.stop_event.is_set():
            if self.paused:  # nothing is read, assessed or logged
                self.stop_event.wait(0.2)
                next_at = time.monotonic()
                continue
            if self.source is None:
                try:
                    self.source = self.open_source()
                    self.method = getattr(self.source, "method", None)
                except Exception as e:  # no lgpio, no GPIO chip, GPIO busy...
                    self.ingest(Reading(datetime.now(), error=f"DHT11 not available: {e}"))
                    self.stop_event.wait(self.interval_s)
                    continue
            with self.step:
                reading = self.next_reading()
                if reading is not None:
                    self.ingest(reading)
            next_at += self.interval_s
            delay = next_at - time.monotonic()
            if delay < -self.interval_s:  # fell behind (a slow read): don't try to catch up
                next_at = time.monotonic()
                delay = 0
            self.stop_event.wait(max(delay, 0))

    def ingest(self, reading):
        with self.lock:
            assessment = self.detector.update(reading)
            event = self.alerts.update(reading.timestamp, assessment)
            self.seq += 1
            self.history.append((self.seq, reading, assessment))
            self.counts["readings"] += 1
            if assessment.status == SENSOR_ERROR:
                self.counts["failed"] += 1
            elif assessment.status != "NORMAL":
                self.counts["flagged"] += 1
            self.last = (reading, assessment)
            if assessment.status != SENSOR_ERROR:
                self.last_good = reading
            if event:
                self.last_event = (self.seq, event)
        if self.recorder:
            try:
                self.recorder.write(make_row(reading, assessment, self.source_label))
            except OSError as e:
                print(f"Could not write the {self.key} log: {e}", file=sys.stderr, flush=True)
        return assessment

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
        if self.source:
            self.source.close()
        if self.recorder:
            self.recorder.close()

    # --- state for the page --------------------------------------------------------------
    def meta(self):
        return {"key": self.key, "title": self.title, "kind": self.kind, "badge": self.badge,
                "about": self.about, "method": self.method, "interval_s": self.interval_s,
                "chart_points": self.chart_points, "rules": self.profile.describe(),
                "channels": [{"key": c.key, "label": c.label, "unit": c.unit, "decimals": c.decimals,
                              "k": c.k, "low": c.low, "high": c.high} for c in self.profile.channels],
                "stats": SENSOR_STATS, "windows": [], "simulated": False}

    def state(self, since):
        with self.lock:
            points = []  # newest first, then reversed: never walks the whole 24 h history
            for seq, r, a in reversed(self.history):
                if seq <= since or len(points) >= self.chart_points:
                    break
                points.append(self._point(seq, r, a))
            points.reverse()
            recent = [self._row(r, a) for _, r, a in islice(reversed(self.history), 14)]
            alerts = [a.as_dict() for a in list(self.alerts.alerts)[-12:]][::-1]
            current = None
            if self.last:
                r, a = self.last
                current = {"timestamp": iso(r.timestamp), "status": a.status, "reasons": a.reasons,
                           "learning": a.learning, "error": r.error, "note": r.note,
                           "channels": {k: self._clean(d) for k, d in a.channels.items()},
                           "values": {c.key: getattr(r, c.key) for c in self.profile.channels}}
            return {"seq": self.seq, "status": self.alerts.status if self.last else "STARTING",
                    "current": current, "points": points, "recent": recent, "alerts": alerts,
                    "open_alert": self.alerts.open.as_dict() if self.alerts.open else None,
                    "counts": dict(self.counts, anomaly_alerts=sum(a.kind == "ANOMALY" for a in self.alerts.alerts),
                                   error_alerts=sum(a.kind == SENSOR_ERROR for a in self.alerts.alerts)),
                    "since": iso(self.started) if self.started else None,
                    "session_start": iso(self.session_start), "epoch": self.epoch,
                    "paused": self.paused, "last_event": self.last_event}

    def _point(self, seq, r, a):
        point = [seq, iso(r.timestamp), STATUS_CODE.get(a.status, "N")]
        for c in self.profile.channels:
            d = a.channels.get(c.key, {})
            band = d.get("band")
            flagged = a.status == "ANOMALY" and any(x.startswith(c.label) for x in a.reasons)
            point += [getattr(r, c.key), round(band[0], 3) if band else None,
                      round(band[1], 3) if band else None, 1 if flagged else 0]
        return point

    def _row(self, r, a):
        return [iso(r.timestamp)] + [getattr(r, c.key) for c in self.profile.channels] + [a.status, a.reason]

    @staticmethod
    def _clean(d):
        out = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items() if k != "band"}
        if "band" in d:
            out["band"] = [round(d["band"][0], 3), round(d["band"][1], 3)]
        return out

    def export_rows(self):
        with self.lock:
            return [make_row(r, a, self.source_label) for _, r, a in self.history]


class LiveStream(Stream):
    def __init__(self, gpio, method):
        self.gpio, self.dht_method = gpio, method
        self.simulated = method == "sim"
        self.tag = "SIM" if self.simulated else "LIVE"
        if self.simulated:  # development only: never mixed into the real sensor's log
            super().__init__("live", "DHT11", "live", DHT11, DHT11.interval_s, 300,
                             badge="Simulated DHT11 · not a real sensor",
                             about="Simulated DHT11 readings for development without the sensor.",
                             source_label="simulated", record="simulated")
        else:
            super().__init__("live", "DHT11", "live", DHT11, DHT11.interval_s, 300,
                             badge=f"Live · DHT11 on GPIO{gpio}",
                             about="Real readings from the DHT11 on the Pi, every 2 s.",
                             source_label="dht11", record="live")

    def open_source(self):
        return SimulatedDht11() if self.simulated else open_dht11(self.gpio, self.dht_method)

    def meta(self):
        return dict(super().meta(), simulated=self.simulated)


class ReplayStream(Stream):
    columns = REPLAY_COLUMNS
    tag = "DATA"

    def __init__(self, name, speed):
        info = datasets.DATASETS[name]
        profile = PROFILES[f"nab_{name}"]
        self.name = name
        self.rows = datasets.load_celsius(name)
        self.windows = datasets.load_windows(name)
        self.points_labelled = datasets.load_points(name)
        chart = {"machine": 576, "ambient": 336}[name]  # 2 days / 2 weeks
        step = info["interval_s"]
        super().__init__(name, info["title"], "replay", profile, 1 / speed, chart,
                         badge=f"Public dataset replay · NAB · ×{speed * step:,.0f} speed",
                         about=info["about"], source_label=f"nab-{name} (public dataset replay)")
        self.speed = speed

    def open_source(self):
        return ReplaySource(self.rows)

    def next_reading(self):
        reading = self.source.read()
        if reading is None:  # the end: start again
            self.reset()
            self.source = ReplaySource(self.rows)
            reading = self.source.read()
        return reading

    def seek(self, window):
        """Restart a day (or a week) before labelled window `window` (1-based; 0 = the start)."""
        start = 0
        if window:
            lead = {"machine": 288, "ambient": 168}[self.name]
            begin = self.windows[window - 1][0]
            first = next(i for i, (t, _) in enumerate(self.rows) if t >= begin)
            start = max(first - lead, 0)
        with self.step:
            self.reset()
            # Run the detector quietly over what came before, so the baseline is ready.
            warm = max(start - self.profile.channels[0].window * 2, 0)
            with self.lock:
                for t, v in self.rows[warm:start]:
                    self.detector.update(Reading(t, v))
            self.source = ReplaySource(self.rows, start)

    def clear(self):
        self.seek(0)

    def export_rows(self):
        info = datasets.DATASETS[self.name]
        unit = f"{info['unit']} ({info['unit_basis']})"
        with self.lock:
            return [{"timestamp": iso(r.timestamp), "temperature_c": f"{r.temperature_c:.2f}",
                     "dataset_value": f"{r.temperature_c * 9 / 5 + 32:.2f}", "dataset_unit": unit,
                     "anomaly_status": a.status, "alert_reason": a.reason, "source": self.source_label}
                    for _, r, a in self.history]

    def meta(self):
        m = super().meta()
        m["windows"] = [{"start": iso(a), "end": iso(b), "label": iso(p)}
                        for (a, b), p in zip(self.windows, self.points_labelled)]
        m["rows"] = len(self.rows)
        m["unit_note"] = datasets.DATASETS[self.name]["unit_note"]
        m["unit_basis"] = datasets.DATASETS[self.name].get("unit_basis")
        m["dataset_unit"] = datasets.DATASETS[self.name]["unit"]
        m["dataset_span"] = [iso(self.rows[0][0]), iso(self.rows[-1][0])]
        return m

    def state(self, since):
        s = super().state(since)
        s["replay"] = {"progress": self.source.progress if self.source else 0.0,
                       "position": self.source.index if self.source else 0}
        return s


class MotorStream:
    """The fan: the SG90 servo, switched by the DHT11's humidity (fan_control.FanController).
    Sampled once a second for the chart and the log."""

    key, title, kind = "motor", "Motor", "motor"
    interval_s = 1.0
    chart_points = 600  # 10 minutes
    columns = MOTOR_COLUMNS
    STALE_S = 10  # a humidity value older than this is not used to switch the fan
    CODE = {"RUNNING": "R", "STANDBY": "S", "OFF": "O", "SHUT DOWN": "X", "WAITING": "W"}

    def __init__(self, live, outputs, settings_path=SETTINGS, record=True, power=True):
        self.live = live
        self.fan = FanController(outputs, load_settings(settings_path), settings_path)
        self.recorder = Recorder("motor", columns=MOTOR_COLUMNS) if record else None
        self.power = power
        self.lock = threading.Lock()
        self.thread = None
        self.stop_event = threading.Event()
        self.started = None
        self.paused = False
        self.epoch = 1
        self.session_start = datetime.now()
        self.history = deque(maxlen=HISTORY)  # (seq, time, humidity, state code, on_at, off_at)
        self.seq = 0
        real = outputs.method is not None
        self.badge = f"Live · SG90 servo on GPIO{fan_control.SERVO_GPIO}" if real else "No GPIO · servo not driven"
        self.tag = "LIVE" if real else "NO GPIO"

    def start(self):
        if self.thread:
            return
        self.started = datetime.now()
        self.thread = threading.Thread(target=self._run, name="stream-motor", daemon=True)
        self.thread.start()

    def _run(self):
        time.sleep((1.35 - time.time() % 1) % 1)  # just after the DHT11's read at the whole second
        self.fan.start_motion()
        next_at = time.monotonic()
        while not self.stop_event.is_set():
            self.tick()
            next_at += self.interval_s
            delay = next_at - time.monotonic()
            if delay < -self.interval_s:
                next_at = time.monotonic()
                delay = 0
            self.stop_event.wait(max(delay, 0))

    def sensor_input(self, now):
        """-> (humidity to act on or None, sensor state, age of that humidity in s)."""
        live = self.live
        if live is None:
            return None, "none", None
        with live.lock:
            paused, last, good = live.paused, live.last, live.last_good
            alert = live.alerts.status if live.last else None
        if paused:
            return None, "paused", None
        if last is None:
            return None, "waiting", None
        age = (now - good.timestamp).total_seconds() if good else None
        humidity = good.humidity_percent if good is not None and age <= self.STALE_S else None
        if last[0].error:
            sensor = "error" if alert == SENSOR_ERROR else "failing"
        else:
            sensor = "ok"
        return humidity, sensor, age

    def tick(self, now=None):
        now = now or datetime.now()
        humidity, sensor, age = self.sensor_input(now)
        volts, under = read_power() if self.power else (None, None)
        self.fan.update(now, humidity, sensor, age, volts, under)
        self.sample(now)

    def sample(self, now):
        fan = self.fan
        with fan.lock:
            row = (now, fan.humidity, self.CODE[fan.state], fan.on_at, fan.off_at)
            log = {"timestamp": iso(now), "humidity_percent": "" if fan.humidity is None else f"{fan.humidity:.0f}",
                   "fan": "running" if fan.running else "stopped", "state": fan.state, "mode": fan.mode,
                   "on_at": fan.on_at, "off_at": fan.off_at, "servo_pulse_us": fan.out.pulse,
                   "event": " | ".join(fan.drain_log())}
        with self.lock:
            self.seq += 1
            self.history.append((self.seq,) + row)
        if self.recorder:
            try:
                self.recorder.write(log)
            except OSError as e:
                print(f"Could not write the motor log: {e}", file=sys.stderr, flush=True)

    def clear(self):
        raise ValueError("The fan keeps its history. Use Off or the emergency stop to stop it.")

    def set_paused(self, paused):
        raise ValueError("The fan can't be paused. Use Off to keep it stopped.")

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
        self.fan.close()
        if self.recorder:
            self.recorder.close()

    def meta(self):
        f = fan_control
        return {"key": self.key, "title": self.title, "kind": self.kind, "badge": self.badge,
                "about": "The SG90 servo as a fan, switched by the DHT11's humidity.",
                "method": self.fan.out.method, "interval_s": self.interval_s, "chart_points": self.chart_points,
                "rules": "", "windows": [], "simulated": bool(self.live and getattr(self.live, "simulated", False)),
                "channels": [{"key": "humidity_percent", "label": "Humidity", "unit": "%", "decimals": 0,
                              "k": None, "low": None, "high": None}],
                "stats": [{"key": "starts", "label": "Fan starts"},
                          {"key": "run_s", "label": "Run time", "format": "duration"},
                          {"key": "shutdowns", "label": "Shutdowns"}],
                "sweep": {"degrees": round(f.SWEEP_US * f.DEG_PER_US), "period_s": f.SWEEP_PERIOD_S,
                          "gpio": f.SERVO_GPIO, "middle_us": f.MIDDLE_US},
                "levels": {"on_min": f.ON_RANGE[0], "on_max": f.ON_RANGE[1], "off_min": f.OFF_MIN,
                           "min_gap": f.MIN_GAP},
                "leds": {"red": f.RED_LED_GPIO, "yellow": f.YELLOW_LED_GPIO}}

    def state(self, since):
        now = datetime.now()
        snap = self.fan.snapshot(now)
        with self.lock:
            points = []
            for seq, t, h, code, on, off in reversed(self.history):
                if seq <= since or len(points) >= self.chart_points:
                    break
                points.append([seq, iso(t), code, h, on, off])
            points.reverse()
            seq = self.seq
        return {"seq": seq, "status": snap["state"], "current": snap,
                "points": points, "recent": [], "alerts": self.fan.timeline(12), "open_alert": None,
                "counts": self.fan.totals(now), "since": iso(self.started) if self.started else None,
                "session_start": iso(self.session_start), "epoch": self.epoch, "paused": False,
                "last_event": None}


class App:
    def __init__(self, args):
        self.streams = {}
        live = None
        if args.dht11 != "none":
            live = self.streams["live"] = LiveStream(args.gpio, args.dht11)
        outputs = fan_control.open_outputs(leds=args.leds != "off") if args.motor != "none" \
            else fan_control.NoOutputs("The fan is switched off with --motor none")
        self.streams["motor"] = MotorStream(live, outputs, SETTINGS, power=args.motor != "none")
        for name in datasets.DATASETS:
            try:
                self.streams[name] = ReplayStream(name, args.replay_speed)
            except (OSError, ValueError, KeyError) as e:
                print(f"Replay '{name}' is off: {e}. Run: python datasets.py", file=sys.stderr, flush=True)
        for s in self.streams.values():
            if s.kind != "replay":
                s.start()  # the DHT11 and the fan always run, so their logs have no gaps
        self.quit_event = threading.Event()

    def stream(self, key):
        s = self.streams.get(key) or next(iter(self.streams.values()))
        s.start()  # replays start when first shown
        return s

    def state(self, key, since):
        s = self.stream(key)
        out = s.state(since)
        out["stream"] = s.key
        out["meta"] = s.meta()
        out["streams"] = [{"key": x.key, "title": x.title, "kind": x.kind, "tag": x.tag} for x in self.streams.values()]
        out["clock"] = iso(datetime.now())
        return out

    def export(self, key, range_):
        """range_: hour, day, session (since the last reset) or all."""
        s = self.stream(key)
        if s.recorder:  # the DHT11 and the fan: everything they logged, not just what is in memory
            now = datetime.now()
            # The log keeps whole seconds: a session starts at the next whole second after the reset,
            # so a reading from just before the reset, in the same second, stays out.
            session = s.session_start.replace(microsecond=0)
            if s.session_start.microsecond:
                session += timedelta(seconds=1)
            start = {"hour": now - timedelta(hours=1),
                     "day": now.replace(hour=0, minute=0, second=0, microsecond=0),
                     "session": session}.get(range_)
            rows = list(read_log(s.recorder.name, start))
        else:
            rows = s.export_rows()  # a replay: what has been played since it last started
        text, count = to_csv(rows, s.columns)
        path = save_export(text, s.recorder.name if s.recorder else s.key)
        return text, count, path

    def fan(self, body):
        """The fan's buttons -> (ok, message)."""
        motor = self.streams.get("motor")
        if not motor:
            raise ValueError("There is no fan")
        fan = motor.fan
        action = body.get("action")
        if action == "mode":
            return True, fan.set_mode(body.get("mode"))
        if action == "levels":
            return True, fan.set_levels(body.get("on_at"), body.get("off_at"))
        if action == "stop":
            return True, fan.emergency_stop()
        if action == "restart":
            return fan.restart()
        raise ValueError(f"Unknown fan action {action!r}")

    def close(self):
        for s in self.streams.values():
            s.close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "VizionSense"

    def log_message(self, fmt, *args):
        pass

    @property
    def app(self):
        return self.server.app

    def do_GET(self):
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/state":
            try:
                since = int(q.get("since", "0"))
            except ValueError:
                since = 0
            self._json(self.app.state(q.get("stream", "live"), since))
        elif url.path == "/api/export.csv":
            text, count, path = self.app.export(q.get("stream", "live"), q.get("range", "all"))
            self._send(200, "text/csv; charset=utf-8", text.encode("utf-8"), {
                "Content-Disposition": f'attachment; filename="{path.name}"',
                "X-Rows": str(count), "X-Saved-To": str(path)})
        elif url.path in ("/", "/index.html"):
            self._file("index.html")
        elif url.path.startswith("/static/"):
            self._file(url.path[len("/static/"):])
        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        url = urlsplit(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except (ValueError, json.JSONDecodeError):
            return self._json({"ok": False, "message": "Bad JSON"}, 400)
        try:
            if url.path == "/api/fan":
                ok, message = self.app.fan(body)
                result = {"ok": ok, "message": message}
            elif url.path == "/api/replay":
                stream = self.app.stream(body.get("stream", "machine"))
                if not isinstance(stream, ReplayStream):
                    raise ValueError("not a replay stream")
                window = int(body.get("window", 0))
                stream.seek(window)
                result = {"ok": True, "message": f"Replaying from {'the start' if not window else f'a day before window {window}'}"}
            elif url.path == "/api/pause":
                stream = self.app.stream(body.get("stream", "live"))
                stream.set_paused(body.get("paused", True))
                what = "paused: nothing is read or logged until you resume" if stream.paused else "resumed"
                result = {"ok": True, "paused": stream.paused, "message": f"{stream.title} {what}."}
            elif url.path == "/api/reset":
                stream = self.app.stream(body.get("stream", "live"))
                stream.clear()
                kept = " The log on the Pi is kept." if stream.recorder else ""
                result = {"ok": True, "message": f"{stream.title} readings reset: chart, alerts, counts "
                                                 f"and baseline start again.{kept}"}
            elif url.path == "/api/quit":
                self.app.quit_event.set()
                result = {"ok": True, "message": "Closing"}
            else:
                return self._send(404, "text/plain", b"Not found")
        except (KeyError, ValueError, TypeError, RuntimeError, StopIteration) as e:
            result = {"ok": False, "message": str(e) or "Not possible"}
        self._json(result)

    def _json(self, obj, code=200):
        self._send(code, "application/json", json.dumps(obj, separators=(",", ":")).encode())

    def _file(self, name):
        path = (WEB / name).resolve()
        if WEB not in path.parents or not path.is_file():
            return self._send(404, "text/plain", b"Not found")
        ctype = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        self._send(200, ctype, path.read_bytes())

    def _send(self, code, ctype, body, headers=None):
        self.send_response(code)
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 lets other computers open the dashboard (and press its buttons)")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--gpio", type=int, default=DHT11_GPIO, help="GPIO of the DHT11 data pin (default 4, pin 7)")
    ap.add_argument("--dht11", default="auto", choices=["auto", "kernel", "lgpio", "sim", "none"],
                    help="how to read the DHT11; sim: simulated readings for development; none: no DHT11")
    ap.add_argument("--motor", default="auto", choices=["auto", "none"],
                    help="none: don't drive the servo or the LEDs")
    ap.add_argument("--leds", default="on", choices=["on", "off"],
                    help="off: leave the LEDs on GPIO17 and GPIO27 to the camera dashboard")
    ap.add_argument("--replay-speed", type=float, default=12, help="dataset rows per second in replays")
    args = ap.parse_args()

    app = App(args)
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        app.close()
        sys.exit(f"Cannot serve on {args.host}:{args.port}: {e}")
    server.daemon_threads = True
    server.app = app
    threading.Thread(target=server.serve_forever, daemon=True).start()
    out = app.streams["motor"].fan.out
    print(f"Vizion Sense on http://{args.host}:{args.port}/  streams: {', '.join(app.streams)}  "
          f"fan: {out.method or out.note}" + (f" ({out.note})" if out.method and out.note else ""), flush=True)

    def stop(_signum, _frame):
        app.quit_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while not app.quit_event.wait(0.5):
            pass
    finally:
        server.shutdown()
        app.close()
        print("Vizion Sense stopped", flush=True)


if __name__ == "__main__":
    main()
