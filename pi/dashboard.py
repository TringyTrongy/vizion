#!/usr/bin/env python3
"""Vizion dashboard: the live camera, detections and status as a full-screen page on the Pi.

    ./run_dashboard.sh                       starts this server and opens Chromium in kiosk mode
    .venv/bin/python dashboard.py            server only; open http://127.0.0.1:8765/

It runs the same pipeline as camera_preview.py: camera_preview.FrameGrabber reads the camera in
a thread, detector.DetectorProcess runs the NCNN model in its own process (the NCNN binding
holds the GIL), and tracker.Tracker smooths the boxes and counts each physical part once.
On top of that it reconnects the camera and restarts the model when they fail, checks the
table for unrecognised objects (dashboard_logic.EmptyTable) and serves the page in web/ with
Python's standard library. Two LEDs on the GPIO header (leds.py) show what is on the table: each
is lit while its class is detected, and on request they blink the counts.

Web API (used by web/dashboard.js):
    GET  /frame?after=N    newest JPEG frame after N, waiting up to 1 s (204 if none);
                           the dashboard state for that frame is JSON in the X-Vizion header
    GET  /api/state        the state JSON
    POST /api/detection    {"on": true | false}
    POST /api/empty-table  {"action": "learn" | "forget"}
    POST /api/leds         {"action": "blink"}: blink the resistor and capacitor counts on the LEDs
    POST /api/quit         stop the dashboard
"""
import argparse
import glob
import json
import queue
import re
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import cv2

from camera_preview import DEFAULT_MODEL, DET_CANDIDATE_CONF, FrameGrabber, detect_right_padding, try_open_camera
from dashboard_logic import Designators, EmptyTable, count_parts, describe_parts
from leds import Leds

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
CAMERA_RETRY_S = 2.0
CAMERA_STALL_S = 3.0  # no new picture for this long while connected: say so
EMPTY_CHECK_S = 0.25
STATE_REFRESH_S = 0.25  # how often the state is republished while no frames arrive
MODEL_RETRIES, MODEL_RETRY_WINDOW_S, MODEL_RETRY_DELAY_S = 3, 600, 2.0
NOTICE_S = 6.0
JPEG_QUALITY = 85
HIDE_RATIO = 0.6  # a shown part is hidden again below 60% of --conf (hysteresis, as in the preview)
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".woff": "font/woff", ".woff2": "font/woff2",
                 ".svg": "image/svg+xml", ".png": "image/png", ".txt": "text/plain; charset=utf-8"}


def find_camera(device):
    """'auto' prefers the stable /dev/v4l/by-id link, which survives replugging into another port."""
    if device != "auto":
        return device
    links = sorted(glob.glob("/dev/v4l/by-id/*-video-index0"))
    return links[0] if links else "/dev/video0"


class ImageSource:
    """Stands in for the camera in tests: shows image files in turn, `hold` seconds each."""

    def __init__(self, path, fps, hold):
        path = Path(path)
        files = sorted(f for f in path.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png")) \
            if path.is_dir() else [path]
        loaded = [(f.name, cv2.imread(str(f))) for f in files]
        self.images = [(name, img) for name, img in loaded if img is not None]
        if not self.images:
            raise SystemExit(f"No images in {path}")
        self.name = self.images[0][0]
        self.interval, self.hold, self.t0, self.next = 1.0 / fps, hold, time.monotonic(), 0.0

    def read(self):
        now = time.monotonic()
        if self.next > now:
            time.sleep(self.next - now)
        self.next = max(now, self.next) + self.interval
        i = int((time.monotonic() - self.t0) / self.hold) % len(self.images)
        self.name, img = self.images[i]
        return True, img.copy()

    def release(self):
        pass


class Camera:
    """The USB camera, reopened every few seconds while it is missing or not sending pictures."""

    def __init__(self, args):
        self.args = args
        self.grabber = self.cap = None
        self.state, self.detail, self.size = "connecting", "Looking for the camera", None
        self.seq, self.next_try, self.t_last = 0, 0.0, 0.0

    def poll(self, timeout):
        """The newest frame since the last call, or None after waiting up to timeout."""
        if self.grabber is None:
            wait = self.next_try - time.monotonic()
            if wait > 0:
                time.sleep(min(timeout, wait))
                return None
            self._open()
            if self.grabber is None:
                return None
        frame, seq = self.grabber.newer_than(self.seq, timeout)
        if self.grabber.dead:
            self._close("lost", "The camera stopped sending pictures. Check its USB cable.")
            return None
        now = time.monotonic()
        if seq <= self.seq:
            if self.state == "ok" and now - self.t_last > CAMERA_STALL_S:
                self.state, self.detail = "stalled", "The camera has stopped sending new pictures."
                print("Camera stalled", flush=True)
            return None
        self.seq, self.t_last = seq, now
        if self.state != "ok":
            self.state, self.detail, self.size = "ok", "", [frame.shape[1], frame.shape[0]]
            print(f"Camera sending {frame.shape[1]}x{frame.shape[0]}", flush=True)
        return frame

    def _open(self):
        a = self.args
        if a.source:
            cap, crop, name = ImageSource(a.source, a.fps, a.source_hold), 0, a.source
        else:
            name = find_camera(a.device)
            cap = try_open_camera(name, a.width, a.height, a.fps)
            if cap is None:
                self._close("lost", f"No camera at {name}. Plug in the USB camera.")
                return
            crop = detect_right_padding(cap) if a.crop_right < 0 else a.crop_right
        print(f"Camera {name} opened (cropping {crop} px)", flush=True)
        self.cap, self.seq, self.t_last = cap, 0, time.monotonic()
        self.grabber = FrameGrabber(cap, crop, a.fps)
        self.grabber.start()
        self.state, self.detail = "connecting", "Waiting for the first picture"

    def _close(self, state, detail):
        if self.state != state or self.detail != detail:
            print(f"Camera {state}: {detail}", flush=True)
        if self.grabber:
            self.grabber.stop()
        if self.cap is not None:
            self.cap.release()
        self.grabber = self.cap = None
        self.state, self.detail, self.next_try = state, detail, time.monotonic() + CAMERA_RETRY_S

    @property
    def source_name(self):
        """The test image on show, so the page never passes test pictures off as the live camera."""
        return self.cap.name if isinstance(self.cap, ImageSource) else None

    def close(self):
        if self.grabber:
            self.grabber.stop()
        if self.cap is not None:
            self.cap.release()


class Model:
    """The detector process. Loads in the background (~10 s) and is restarted if it dies."""

    def __init__(self, args):
        self.args = args
        self.proc = self._loaded = None
        self.state, self.detail = "loading", ""
        self.names, self.imgsz, self.label = {}, None, model_label(args.model)
        self.failures, self.retry_at = [], None
        self.start()

    def start(self):
        if not Path(self.args.model).exists():
            self.state, self.detail = "failed", f"No model at {self.args.model}"
            return
        self.state, self.detail, self.retry_at = "loading", "", None

        def load():
            from detector import DetectorProcess  # imports here keep startup fast; the child loads torch

            try:
                self._loaded = DetectorProcess(self.args.model, conf=DET_CANDIDATE_CONF, imgsz=self.args.imgsz)
            except (EOFError, OSError) as e:  # the child exited while loading (its traceback is in the log)
                print(f"Model failed to load: {e!r}", flush=True)
                self._loaded = e

        threading.Thread(target=load, daemon=True).start()

    def poll(self):
        """Picks up a finished load and handles a dead process. True when the model just became ready."""
        loaded, self._loaded = self._loaded, None
        if isinstance(loaded, Exception):
            self._failed("The model could not be loaded")
        elif loaded is not None:
            self.proc, self.names, self.imgsz, self.state = loaded, loaded.names, loaded.imgsz, "ready"
            print(f"Model ready: {self.label} @ {self.imgsz}, classes {self.names}", flush=True)
            return True
        if self.proc is not None and self.proc.dead:
            print("Model process died", flush=True)
            self.proc.close()
            self.proc = None
            self._failed("The model process stopped")
        if self.retry_at is not None and time.monotonic() >= self.retry_at:
            self.start()
        return False

    def _failed(self, why):
        now = time.monotonic()
        self.failures = [t for t in self.failures if now - t < MODEL_RETRY_WINDOW_S] + [now]
        if len(self.failures) <= MODEL_RETRIES:
            self.state, self.detail, self.retry_at = "restarting", why, now + MODEL_RETRY_DELAY_S
        else:
            self.state, self.retry_at = "failed", None
            self.detail = f"{why}. Turn detection off and on to try again; details are in dashboard.log."

    def retry(self):
        if self.state == "failed":
            self.failures = []
            self.start()

    def close(self):
        if self.proc is not None:
            self.proc.close()


def model_label(model_dir):
    """'YOLO26n NCNN 480' from the export metadata, for the title block."""
    try:
        import yaml

        meta = yaml.safe_load((Path(model_dir) / "metadata.yaml").read_text())
        arch = re.search(r"YOLO\w+", meta.get("description", ""))
        return f"{arch.group(0) if arch else 'YOLO'} NCNN {meta['imgsz'][0]}"
    except Exception:
        return Path(model_dir).name


class Dashboard:
    """The pipeline loop (main thread) and the state it publishes to the web handlers."""

    def __init__(self, args):
        self.args = args
        self.camera, self.model, self.empty = Camera(args), Model(args), EmptyTable(args.empty_table)
        self.leds = Leds([("resistor", *args.resistor_led), ("capacitor", *args.capacitor_led)])
        self.tracker = self.designators = None
        self.detect_on = True
        self.commands = queue.Queue()
        self.running = True
        self.frame, self.frame_seq, self.sent_seq = None, 0, 0
        self.parts, self.fps, self.det_ms, self.results = [], 0.0, 0.0, 0
        self.t_frame = self.t_empty = self.t_state = 0.0
        self.notice = None  # (kind, text, until)
        self.cond = threading.Condition()
        self.pub_seq, self.pub_jpeg, self.pub_state = 0, None, "{}"
        self.stats = {"t0": time.monotonic(), "frames": 0, "dets": 0, "max_gap": 0.0}

    # --- called from web handler threads -----------------------------------------------------
    def request(self, *command):
        """Queues a command for the pipeline loop and waits for its reply."""
        reply = queue.Queue(maxsize=1)
        self.commands.put((command, reply))
        try:
            return reply.get(timeout=3)
        except queue.Empty:
            return {"ok": False, "message": "Vizion is busy; try again."}

    def wait_frame(self, after, timeout):
        """(seq, jpeg or None, state json): the first frame newer than `after`, or the state on timeout."""
        with self.cond:
            # A page from before a restart may be ahead of us; it gets the current frame at once.
            self.cond.wait_for(lambda: self.pub_seq != after or not self.running, timeout)
            return self.pub_seq, (self.pub_jpeg if self.pub_seq != after else None), self.pub_state

    def state_json(self):
        with self.cond:
            return self.pub_state

    # --- pipeline loop ------------------------------------------------------------------------
    def run(self):
        while self.running:
            self._handle_commands()
            frame = self.camera.poll(timeout=0.03)
            self._service_model()
            now = time.monotonic()
            if frame is not None:
                self._on_frame(frame, now)
            elif now - self.t_state >= STATE_REFRESH_S:
                if self.camera.state != "ok":
                    self.fps = 0.0
                    if self.parts:
                        self._clear_parts()  # nothing is known about the table without a picture
                self._publish(None, now)

    def _service_model(self):
        m = self.model
        if m.poll():
            from tracker import Tracker

            self.tracker = Tracker(len(m.names), show_conf=self.args.conf, hide_conf=HIDE_RATIO * self.args.conf)
            self.designators = Designators(m.names)
        if m.proc is None:
            if self.parts:
                self._clear_parts()
            return
        result = m.proc.poll()
        if result and self.detect_on:
            _, dets, ms = result
            self.tracker.update(dets)
            self.det_ms = ms if self.det_ms == 0 else 0.8 * self.det_ms + 0.2 * ms
            self.results += 1
            self.stats["dets"] += 1
            self._describe()
        if self.detect_on and not m.proc.busy and not m.proc.dead and self.frame_seq > self.sent_seq:
            m.proc.submit(self.frame_seq, self.frame)
            self.sent_seq = self.frame_seq

    def _describe(self):
        tracks = self.tracker.visible_tracks()
        refs = self.designators.update(tracks)
        h, w = self.frame.shape[:2]
        self.parts = describe_parts(tracks, self.model.names, refs, w, h)

    def _clear_parts(self):
        self.parts = []
        if self.tracker:
            self.tracker.reset()
        if self.designators:
            self.designators.reset()

    def _on_frame(self, frame, now):
        if self.frame is not None and frame.shape != self.frame.shape:
            self._clear_parts()  # a different camera mode; old boxes no longer fit
        self.frame, self.frame_seq = frame, self.frame_seq + 1
        if self.t_frame:
            dt = now - self.t_frame
            self.fps = 1 / dt if self.fps == 0 else 0.9 * self.fps + 0.1 / dt
            self.stats["max_gap"] = max(self.stats["max_gap"], dt)
        self.t_frame = now
        self.stats["frames"] += 1
        if self.detect_on and self.model.state == "ready" and now - self.t_empty >= EMPTY_CHECK_S:
            self.t_empty = now
            self.empty.check(frame, [p["box"] for p in self.parts])
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        self._publish(jpeg.tobytes() if ok else None, now)
        if self.args.stats and now - self.stats["t0"] >= 5:
            s, span = self.stats, now - self.stats["t0"]
            print(f"video {s['frames'] / span:4.1f} fps, max gap {s['max_gap'] * 1000:3.0f} ms | detections "
                  f"{s['dets'] / span:4.1f}/s, {self.det_ms:3.0f} ms each | parts {len(self.parts)}, "
                  f"unrecognised {self.empty.state}", flush=True)
            self.stats = {"t0": now, "frames": 0, "dets": 0, "max_gap": 0.0}

    def _live_counts(self):
        """Counts of what is on the table, or None when they aren't known (detection off, no camera, no model)."""
        if self.detect_on and self.model.state == "ready" and self.camera.state == "ok":
            return count_parts(self.parts, self.model.names)
        return None

    def _publish(self, jpeg, now):
        self.t_state = now
        self.leds.show(self._live_counts())
        state = json.dumps(self._state(now), separators=(",", ":"))
        with self.cond:
            if jpeg is not None:
                self.pub_seq, self.pub_jpeg = self.frame_seq, jpeg
            self.pub_state = state
            self.cond.notify_all()

    def _state(self, now):
        m, cam = self.model, self.camera
        counts = self._live_counts()
        working = counts is not None
        if not self.detect_on:
            unknown = "off"
        elif cam.state != "ok":
            unknown = "no_camera"
        elif m.state != "ready":
            unknown = "waiting"
        else:
            unknown = self.empty.state
        notice = self.notice if self.notice and self.notice[2] > now else None
        return {
            "seq": self.frame_seq,
            "camera": {"state": cam.state, "detail": cam.detail, "fps": round(self.fps, 1), "size": cam.size,
                       "test_image": cam.source_name},
            "model": {"state": m.state, "detail": m.detail, "label": m.label,
                      "ms": round(self.det_ms) if m.state == "ready" else None},
            "detection": {"on": self.detect_on, "threshold": self.args.conf, "hide_below": round(HIDE_RATIO * self.args.conf, 2),
                          "results": self.results},
            "parts": self.parts if working else [],
            "counts": counts,
            "unknown": {"state": unknown, "boxes": self.empty.boxes if unknown == "present" else [],
                        "learned_at": self.empty.learned_at and int(self.empty.learned_at * 1000)},
            "notice": notice and {"kind": notice[0], "text": notice[1]},
            "leds": self.leds.state(),
        }

    def _handle_commands(self):
        while True:
            try:
                command, reply = self.commands.get_nowait()
            except queue.Empty:
                return
            name, *rest = command
            try:
                reply.put(getattr(self, f"_cmd_{name}")(*rest))
            except Exception as e:  # never let a bad request stop the pipeline
                print(f"Command {command!r} failed: {e!r}", flush=True)
                reply.put({"ok": False, "message": "Something went wrong; see dashboard.log."})
            self._publish(None, time.monotonic())

    def _cmd_detection(self, on):
        self.detect_on = bool(on)
        self._clear_parts()
        if not self.detect_on:
            self.leds.cancel()
        if self.detect_on:
            self.model.retry()
        print(f"Detection {'on' if self.detect_on else 'off'}", flush=True)
        return {"ok": True, "on": self.detect_on}

    def _cmd_empty_table(self, action):
        if action == "forget":
            self.empty.forget()
            return self._notice(True, "Forgot the empty table.")
        if action != "learn":
            return {"ok": False, "message": f"Unknown action {action!r}"}
        if self.camera.state != "ok" or self.frame is None:
            return self._notice(False, "No camera picture to learn from.")
        if not self.detect_on or self.model.state != "ready":
            return self._notice(False, "Turn detection on first, so Vizion can check the table is empty.")
        if self.parts:
            return self._notice(False, "Take the parts off the table first, then learn it.")
        self.empty.learn(self.frame)
        print("Learned the empty table", flush=True)
        return self._notice(True, "Learned the empty table.")

    def _cmd_leds(self, action):
        if action != "blink":
            return {"ok": False, "message": f"Unknown action {action!r}"}
        if not self.leds.available:
            return {"ok": False, "message": "The LEDs are not available."}
        counts = self._live_counts()
        if counts is None:
            return {"ok": False, "message": "Nothing is being detected right now."}
        seconds = self.leds.blink_counts(counts)
        if not seconds:
            return {"ok": False, "message": "No parts to count."}
        print(f"Blinking counts: {counts['resistor']} resistors, {counts['capacitor']} capacitors", flush=True)
        return {"ok": True, "seconds": round(seconds, 1), "counts": counts}

    def _notice(self, ok, text):
        self.notice = ("ok" if ok else "error", text, time.monotonic() + NOTICE_S)
        return {"ok": ok, "message": text}

    def _cmd_quit(self):
        self.running = False
        return {"ok": True}

    def close(self):
        with self.cond:
            self.running = False
            self.cond.notify_all()
        self.camera.close()
        self.model.close()
        self.leds.close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: the page fetches a frame every ~70 ms
    server_version = "Vizion"

    def log_message(self, fmt, *args):
        pass

    @property
    def dash(self):
        return self.server.dash

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/frame":
            try:
                after = int(parse_qs(url.query).get("after", ["0"])[0])
            except ValueError:
                after = 0
            seq, jpeg, state = self.dash.wait_frame(after, timeout=1.0)
            headers = {"X-Vizion": state}
            if jpeg is None:
                self._send(204, None, b"", headers)
            else:
                self._send(200, "image/jpeg", jpeg, headers)
        elif url.path == "/api/state":
            self._send(200, "application/json", self.dash.state_json().encode())
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
            return self._send(400, "application/json", b'{"ok":false,"message":"Bad JSON"}')
        if url.path == "/api/detection":
            result = self.dash.request("detection", bool(body.get("on")))
        elif url.path == "/api/empty-table":
            result = self.dash.request("empty_table", body.get("action", "learn"))
        elif url.path == "/api/leds":
            result = self.dash.request("leds", body.get("action", "blink"))
        elif url.path == "/api/quit":
            result = self.dash.request("quit")
        else:
            return self._send(404, "text/plain", b"Not found")
        self._send(200, "application/json", json.dumps(result).encode())

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


def led_arg(text):
    """'17:red' -> (17, 'red'); 'none' -> (None, None)."""
    if text.lower() == "none":
        return None, None
    gpio, _, color = text.partition(":")
    try:
        return int(gpio), (color or "led").lower()
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected GPIO:COLOUR such as 17:red, or none (got {text!r})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to serve on; 0.0.0.0 lets other computers on the network watch (and control) it")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--device", default="auto", help="camera device ('auto': the first USB camera)")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=15, help="frame-rate cap (the camera may be slower in dim light)")
    ap.add_argument("--crop-right", type=int, default=-1,
                    help="columns to drop from the right edge (-1 = auto-detect sensor padding)")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="exported detector (NCNN dir)")
    ap.add_argument("--conf", type=float, default=0.25, help="confidence needed before a part is shown")
    ap.add_argument("--imgsz", type=int, default=None, help="detector input size (default: from the model)")
    ap.add_argument("--empty-table", type=Path, default=HERE / "empty_table.png",
                    help="where the learned empty-table picture is kept")
    ap.add_argument("--resistor-led", type=led_arg, default="17:red",
                    help="GPIO number and colour of the resistor LED, or 'none' (default 17:red, header pin 11)")
    ap.add_argument("--capacitor-led", type=led_arg, default="27:yellow",
                    help="GPIO number and colour of the capacitor LED, or 'none' (default 27:yellow, header pin 13)")
    ap.add_argument("--source", type=Path, help="test: show these image files instead of the camera")
    ap.add_argument("--source-hold", type=float, default=1e9, help="test: seconds to show each --source image")
    ap.add_argument("--stats", action="store_true", help="print frame and detection rates every 5 s")
    args = ap.parse_args()

    dash = Dashboard(args)
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        dash.close()
        raise SystemExit(f"Cannot serve on {args.host}:{args.port} ({e.strerror}). Is the dashboard already running?")
    server.daemon_threads = True
    server.dash = dash
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def stop(_signum, _frame):
        dash.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"Vizion dashboard on http://{args.host}:{args.port}/ (threshold {args.conf})", flush=True)
    try:
        dash.run()
    finally:
        dash.close()
        server.shutdown()
        print("Dashboard stopped", flush=True)


if __name__ == "__main__":
    main()
