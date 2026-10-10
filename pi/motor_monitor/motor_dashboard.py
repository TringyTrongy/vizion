"""Vizion Motor: watches the SG90 servo arm with the webcam and stops it on an anomaly.

    .venv/bin/python motor_monitor/motor_dashboard.py              # then open http://127.0.0.1:8767/
    .venv/bin/python motor_monitor/motor_dashboard.py --rig sim    # no hardware: a drawn arm (development)

The servo sweeps ±40° every 3 s. Learn normal records what the arm looks like at every point of the
sweep; from then on every camera frame is compared with those master images (motor_watch.py). A
mismatch over the learned limit for three frames in a row is an anomaly: the servo stops being driven,
the red LED flashes, and it stays stopped until Restart. Every inspected frame is logged to
data/log/motor-watch-YYYY-MM-DD.csv, and each anomaly's two pictures are kept in data/evidence/.

Separate from the camera dashboard (port 8765) and Vizion Sense (port 8766), but it needs the webcam
(like the camera dashboard) and the servo and LEDs (like Vizion Sense), so run one of them at a time.
Standard library, numpy and OpenCV from the venv, lgpio for the servo and LEDs.
"""
import argparse
import csv
import io
import json
import signal
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np

import motor_rig
import motor_watch
from motor_watch import ANOMALY, LEARNING, Master, Monitor, grey_small

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
DATA = HERE / "data"  # the log, the anomalies' pictures and the learned normal (--data moves it)
COLUMNS = ["timestamp", "state", "command_us", "command_deg", "seen_deg", "mismatch", "limit", "event"]
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".woff2": "font/woff2", ".svg": "image/svg+xml",
                 ".png": "image/png", ".jpg": "image/jpeg"}
MOTION_HZ = 25


class Recorder:
    """Appends every inspected frame to data/log/motor-watch-YYYY-MM-DD.csv (flushed once a second)."""

    def __init__(self, folder, enabled=True):
        self.folder = Path(folder)
        self.enabled = enabled
        self.rows = []
        self.lock = threading.Lock()

    def write(self, row):
        if self.enabled:
            with self.lock:
                self.rows.append(row)

    def flush(self):
        with self.lock:
            rows, self.rows = self.rows, []
        if not rows:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        by_day = {}
        for r in rows:
            by_day.setdefault(r["timestamp"][:10], []).append(r)
        for day, day_rows in by_day.items():
            path = self.folder / f"motor-watch-{day}.csv"
            new = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, COLUMNS)
                if new:
                    w.writeheader()
                w.writerows(day_rows)

    def export(self, since=None, day=None):
        """The logged rows as CSV text: from `since` (a timestamp string), one day, or everything."""
        self.flush()
        out = io.StringIO()
        w = csv.DictWriter(out, COLUMNS)
        w.writeheader()
        for path in sorted(self.folder.glob("motor-watch-*.csv")):
            if day and not path.name.endswith(f"{day}.csv"):
                continue
            with path.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if since is None or row["timestamp"] >= since:
                        w.writerow({k: row.get(k, "") for k in COLUMNS})
        return out.getvalue()


def save_master(master, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, **master.to_arrays())
    tmp.replace(path)


def load_master(path):
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=True) as a:
            return Master.from_arrays(a)
    except Exception as e:  # an old or broken file: learn again
        print(f"Could not load {path}: {e}", file=sys.stderr)
        return None


def plate_box(master):
    """The part of the camera frame the EXPECTED and LIVE panes show: the arm's region with room round it.

    (x, y, w, h) in the full frame, and the arm's box inside it as fractions of the pane.
    """
    W, H = motor_rig.FRAME_W, motor_rig.FRAME_H
    if master is None:
        return (0, 0, W, H), None
    x0, y0, x1, y1 = (v * 2 for v in master.box)
    bw, bh = x1 - x0, y1 - y0
    w = int(min(W, max(240, bw * 1.8, bh * 1.8 * 4 / 3)))
    h = int(min(H, w * 3 / 4))
    w = int(min(W, h * 4 / 3))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    x = int(min(max(0, cx - w / 2), W - w))
    y = int(min(max(0, cy - h / 2), H - h))
    box = [round((x0 - x) / w, 4), round((y0 - y) / h, 4), round(bw / w, 4), round(bh / h, 4)]
    return (x, y, w, h), box


class App:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if args.rig == "sim":
            rig = motor_rig.SimRig()
            self.outputs, self.camera = rig, rig
        else:
            self.outputs = motor_rig.open_outputs(leds=args.leds == "on")
            self.camera = motor_rig.Webcam() if motor_rig.cv2 is not None else None
        data = Path(args.data)
        self.evidence_dir = data / "evidence"
        self.master_file = data / "master.npz"
        self.recorder = Recorder(data / "log", enabled=not args.no_log)
        master = None if args.fresh else load_master(self.master_file)
        self.monitor = Monitor(master, record=self.recorder.write, keep=self._keep)
        self.latest = None  # the newest camera frame (BGR)
        self.frames = 0
        self.plates = {}  # small cache of encoded panes
        self.saved_evidence = set()
        self.learned = self.monitor.counts["learned"]
        self.threads = [threading.Thread(target=self._camera_loop, daemon=True, name="camera"),
                        threading.Thread(target=self._motion_loop, daemon=True, name="motion"),
                        threading.Thread(target=self._housekeeping, daemon=True, name="housekeeping")]

    def start(self):
        for t in self.threads:
            t.start()

    @staticmethod
    def _keep(frame):
        return None if frame is None else motor_rig.encode_jpeg(frame, 80)

    # --- Loops ----------------------------------------------------------------------------------

    def _camera_loop(self):
        while not self.stopping.is_set():
            if self.camera is None:
                time.sleep(0.5)
                continue
            frame = self.camera.read()
            if frame is None:
                continue
            t = time.monotonic()
            small = grey_small(frame)
            with self.lock:
                self.monitor.on_frame(small, t, frame)
                self.latest = frame
                self.frames += 1
                trip = self.monitor.trip
                learned = self.monitor.counts["learned"]
            if trip and trip.get("kind") == "anomaly" and trip.get("id") not in self.saved_evidence:
                self._save_evidence(trip)
            if learned != self.learned:
                self.learned = learned
                self.plates.clear()
                threading.Thread(target=save_master, args=(self.monitor.master, self.master_file),
                                 daemon=True).start()

    def _motion_loop(self):
        while not self.stopping.is_set():
            t = time.monotonic()
            with self.lock:
                self.monitor.check_camera(t)
                us, _ = self.monitor.command(t)
                leds = self.monitor.leds(t)
            self.outputs.servo(us)
            for name, on in leds.items():
                self.outputs.led(name, on)
            time.sleep(max(0.0, 1 / MOTION_HZ - (time.monotonic() - t)))

    def _housekeeping(self):
        while not self.stopping.wait(1.0):
            try:
                self.recorder.flush()
            except OSError as e:
                print(f"Could not write the log: {e}", file=sys.stderr)

    # --- Pictures -------------------------------------------------------------------------------

    def _crop(self, frame):
        (x, y, w, h), _ = plate_box(self.monitor.master)
        return frame[y:y + h, x:x + w]

    def _expected_frame(self, ref):
        m = self.monitor.master
        if m is None or ref is None:
            return None
        kind, i = ref
        keeps = m.keeps if kind == "sweep" else m.still_keeps
        if i is None or i >= len(keeps) or keeps[i] is None:
            return None
        return motor_rig.decode_jpeg(keeps[i])

    def plate(self, which):
        """JPEG of the EXPECTED or LIVE pane. While an anomaly is shown, both are the frames that tripped it."""
        with self.lock:
            trip = self.monitor.trip if self.monitor.state == ANOMALY else None
            ref = self.monitor.expected_ref
            frames = self.frames
            latest = self.latest
        if trip and trip.get("kind") == "anomaly":
            path = self.evidence_dir / f"{trip['id']:05d}-{which}.jpg"
            key = ("trip", trip["id"], which)
            if key not in self.plates:
                if path.exists():
                    self.plates[key] = path.read_bytes()
                else:
                    self._save_evidence(trip)
                    self.plates[key] = path.read_bytes() if path.exists() else None
            return self.plates[key]
        if which == "live":
            if latest is None:
                return None
            key = ("live", frames)
            if key not in self.plates:
                self.plates = {k: v for k, v in self.plates.items() if k[0] != "live"}
                self.plates[key] = motor_rig.encode_jpeg(self._crop(latest), 82)
            return self.plates[key]
        key = ("expected", ref)
        if key not in self.plates:
            if len(self.plates) > 64:
                self.plates = {k: v for k, v in self.plates.items() if k[0] == "trip"}
            frame = self._expected_frame(ref)
            self.plates[key] = None if frame is None else motor_rig.encode_jpeg(self._crop(frame), 82)
        return self.plates[key]

    def _save_evidence(self, trip):
        """Keep the two pictures of an anomaly in data/evidence/ (NNNNN-live.jpg, NNNNN-expected.jpg)."""
        self.saved_evidence.add(trip["id"])
        try:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            live = motor_rig.decode_jpeg(trip["live"]) if trip.get("live") else None
            expected = self._expected_frame(trip.get("expected"))
            for which, frame in (("live", live), ("expected", expected)):
                if frame is not None:
                    data = motor_rig.encode_jpeg(self._crop(frame), 85)
                    (self.evidence_dir / f"{trip['id']:05d}-{which}.jpg").write_bytes(data)
        except OSError as e:
            print(f"Could not keep the anomaly's pictures: {e}", file=sys.stderr)

    def evidence(self, event_id, which):
        path = self.evidence_dir / f"{int(event_id):05d}-{which}.jpg"
        return path.read_bytes() if path.exists() else None

    # --- API ------------------------------------------------------------------------------------

    def state(self, after):
        t = time.monotonic()
        with self.lock:
            snap = self.monitor.snapshot(t, after)
            frames = self.frames
            master = self.monitor.master
        crop, box = plate_box(master)
        for ev in snap["events"]:
            if ev["kind"] == "anomaly":
                ev["evidence"] = (self.evidence_dir / f"{ev['id']:05d}-live.jpg").exists()
        notes = [n for n in (getattr(self.outputs, "note", None),
                             getattr(self.camera, "note", None) if self.camera else
                             "OpenCV is not installed here, so there is no camera.") if n]
        snap.update({
            "frames": frames,
            "plate": {"crop": list(crop), "box": box},
            "session_started": self.started,
            "rig": {"simulated": bool(getattr(self.outputs, "simulated", True)),
                    "servo": getattr(self.outputs, "description", "servo"),
                    "camera": getattr(self.camera, "description", "no camera"),
                    "leds": sorted(getattr(self.outputs, "leds", {}) or {}),
                    "notes": notes},
            "settings": {"sweep_deg": round(motor_watch.SWEEP_US * motor_watch.DEG_PER_US),
                         "period_s": motor_watch.PERIOD_S, "confirm_frames": motor_watch.CONFIRM,
                         "learn_s": motor_watch.SETTLE_S + motor_watch.LEARN_S},
        })
        return snap

    def control(self, action):
        t = time.monotonic()
        with self.lock:
            m = self.monitor
            if action == "learn":
                if m.state == LEARNING:
                    raise ValueError("Already learning.")
                if self.camera is None:
                    raise ValueError("There is no camera to learn with.")
                m.learn(t)
            elif action == "start":
                if m.state not in (motor_watch.STOPPED, motor_watch.NOT_LEARNED):
                    raise ValueError("Start works when the motor is stopped.")
                m.start(t)
            elif action == "restart":
                m.restart(t)
            elif action == "stop":
                if m.state in (motor_watch.STOPPED, motor_watch.NOT_LEARNED):
                    raise ValueError("The motor is already stopped.")
                m.stop(t)
            else:
                raise ValueError(f"Unknown action {action!r}.")
            return m.state

    def simulate(self, action):
        if not isinstance(self.camera, motor_rig.SimRig):
            raise ValueError("Disturbances only work with the simulated rig (--rig sim).")
        self.camera.disturb(action)

    def export(self, range_):
        if range_ == "session":
            return self.recorder.export(since=self.started), f"vizion-motor-session-{self.started[:10]}.csv"
        if range_ == "today":
            day = datetime.now().strftime("%Y-%m-%d")
            return self.recorder.export(day=day), f"vizion-motor-{day}.csv"
        if range_ == "all":
            return self.recorder.export(), "vizion-motor-all.csv"
        raise ValueError("range must be session, today or all")

    def close(self):
        self.stopping.set()
        for t in self.threads:
            t.join(timeout=2)
        try:
            self.outputs.servo(0)
            self.outputs.close()
        finally:
            if self.camera is not None and self.camera is not self.outputs:
                self.camera.close()
            self.recorder.flush()


class Handler(BaseHTTPRequestHandler):
    server_version = "VizionMotor/1"

    def log_message(self, fmt, *args):
        if self.server.verbose:
            super().log_message(fmt, *args)

    @property
    def app(self):
        return self.server.app

    def do_GET(self):
        url = urlsplit(self.path)
        q = parse_qs(url.query)
        path = url.path
        if path in ("/", "/index.html"):
            return self._file("index.html")
        if path == "/api/state":
            after = int(q.get("after", ["0"])[0] or 0)
            return self._json(self.app.state(after))
        if path in ("/api/plate/live.jpg", "/api/plate/expected.jpg"):
            data = self.app.plate(path.rsplit("/", 1)[1].split(".")[0])
            if data is None:
                return self._send(204, "text/plain", b"")
            return self._send(200, "image/jpeg", data, {"Cache-Control": "no-store"})
        if path.startswith("/api/evidence/"):
            parts = path.split("/")
            if len(parts) == 5 and parts[3].isdigit() and parts[4] in ("live.jpg", "expected.jpg"):
                data = self.app.evidence(parts[3], parts[4][:-4])
                if data:
                    return self._send(200, "image/jpeg", data)
            return self._send(404, "text/plain", b"not found")
        if path == "/api/export":
            try:
                text, name = self.app.export(q.get("range", ["session"])[0])
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._send(200, "text/csv; charset=utf-8", text.encode("utf-8"),
                              {"Content-Disposition": f'attachment; filename="{name}"'})
        if path.startswith("/static/"):
            return self._file(path[len("/static/"):])
        return self._send(404, "text/plain", b"not found")

    def do_POST(self):
        url = urlsplit(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "The request body must be JSON."}, 400)
        if url.path == "/api/control":
            try:
                state = self.app.control(str(body.get("action", "")))
            except ValueError as e:
                return self._json({"error": str(e)}, 409)
            return self._json({"ok": True, "state": state})
        if url.path == "/api/sim":
            try:
                self.app.simulate(str(body.get("action", "")))
            except ValueError as e:
                return self._json({"error": str(e)}, 409)
            return self._json({"ok": True})
        if url.path == "/api/quit":
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        return self._send(404, "text/plain", b"not found")

    def _json(self, obj, code=200):
        self._send(code, "application/json", json.dumps(obj).encode("utf-8"), {"Cache-Control": "no-store"})

    def _file(self, name):
        path = (WEB / name).resolve()
        if WEB.resolve() not in path.parents or not path.is_file():
            return self._send(404, "text/plain", b"not found")
        ctype = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        cache = {"Cache-Control": "max-age=86400"} if path.suffix == ".woff2" else {"Cache-Control": "no-cache"}
        return self._send(200, ctype, path.read_bytes(), cache)

    def _send(self, code, ctype, body, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--port", type=int, default=8767)
    p.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to open it from another computer")
    p.add_argument("--rig", choices=["pi", "sim"], default="pi",
                   help="pi: the real servo and webcam (default); sim: a drawn arm, for trying it without hardware")
    p.add_argument("--leds", choices=["on", "off"], default="on")
    p.add_argument("--fresh", action="store_true", help="ignore the saved normal and learn again")
    p.add_argument("--data", default=str(DATA), help="folder for the log, the anomalies' pictures and the normal")
    p.add_argument("--no-log", action="store_true", help="don't write data/log/ (tests)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    app = App(args)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.app, server.verbose = app, args.verbose
    app.start()
    rig = "simulated rig" if args.rig == "sim" else f"{app.outputs.description}, {getattr(app.camera, 'description', 'no camera')}"
    print(f"Vizion Motor on http://{args.host}:{args.port}/ ({rig})", flush=True)

    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        app.close()
        print("Vizion Motor stopped", flush=True)


if __name__ == "__main__":
    main()
