#!/usr/bin/env python3
"""Live USB camera preview on the Pi desktop: detects resistors and capacitors, captures stills.

Buttons under the image:
    Capture     save the current frame (without boxes) to the captures folder
    Detect      toggle resistor/capacitor detection on the live view
Close the window to quit.

Keyboard shortcuts (preview window focused):
    SPACE / c   capture
    d           toggle detection
    q / ESC     quit

Remote capture while the preview is running (e.g. over SSH):
    pkill -USR1 -f '[c]amera_preview.py'
(the brackets stop pkill from matching the shell that runs it)

The camera is read in its own thread and the detector runs in its own process, so the video
never waits for detection; detections are smoothed over time by tracker.Tracker.
"""
import argparse
import signal
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

WINDOW = "Vizion camera"
MAX_FAILED_READS = 50  # ~5 s of failed grabs => assume camera unplugged
MAX_PAD = 64
DET_CANDIDATE_CONF = 0.15  # the model reports weak boxes too; the tracker decides what to show
FONT = cv2.FONT_HERSHEY_SIMPLEX
PANEL_H = 56
BUTTONS = {"capture": (12, 10, 140, 36), "detect": (162, 10, 120, 36)}  # x, y (in panel), w, h
FLASH_S, PRESS_S = 1.5, 0.15
CLASS_COLORS = {"resistor": (0, 140, 255), "capacitor": (255, 190, 0)}  # BGR: orange, sky blue
DEFAULT_MODEL = Path(__file__).resolve().parent / "models" / "vizion_ncnn_model"


def open_camera(device, width, height, fps):
    cap = try_open_camera(device, width, height, fps)
    if cap is None:
        raise SystemExit(f"Could not open camera {device}")
    return cap


def try_open_camera(device, width, height, fps):
    """Like open_camera, but returns None instead of exiting (the dashboard keeps retrying)."""
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    # Cheap UVC cameras often return dark frames while auto-exposure settles.
    for _ in range(10):
        cap.read()
    return cap


def detect_right_padding(cap):
    """Columns to crop off the right edge.

    Some cheap UVC sensors (e.g. Arkmicro 18ec:3399) only fill ~610 of 640 columns and
    pad the rest with one constant colour, plus a bright seam before it. Real pixels
    flicker with sensor noise between frames; the padding does not.
    """
    frames = [cap.read()[1] for _ in range(4)]
    if any(f is None for f in frames):
        return 0
    a, b = frames[0].astype(np.int16), frames[-1].astype(np.int16)
    w = a.shape[1]
    pad = 0
    while pad < MAX_PAD:
        x = w - 1 - pad
        # Padding next to the seam carries a little bleed (std ~3); real columns are ~70.
        if a[:, x].std(axis=0).max() > 5.0 or np.abs(a[:, x] - b[:, x]).mean() > 1.0:
            break
        pad += 1
    if pad == 0 or pad == MAX_PAD:  # MAX_PAD => uniform scene (lens covered?), not padding
        return 0
    return pad + 2


class FrameGrabber(threading.Thread):
    """Reads the camera continuously and keeps only the newest frame.

    Reading in the render loop let frames queue up in the driver whenever a render ran
    long; the backlog was then read in a burst and thrown away, so the video jumped.
    OpenCV releases the GIL while it waits for the camera, so this thread costs the
    preview nothing.
    """

    def __init__(self, cap, crop, fps_cap):
        super().__init__(daemon=True)
        self.cap, self.crop, self.min_interval = cap, crop, 1.0 / fps_cap
        self.cond = threading.Condition()
        self.frame, self.seq, self.dead, self.running = None, 0, False, True

    def run(self):
        failed, t_last = 0, 0.0
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                failed += 1
                if failed >= MAX_FAILED_READS:
                    with self.cond:
                        self.dead = True
                        self.cond.notify_all()
                    return
                time.sleep(0.1)
                continue
            failed = 0
            now = time.monotonic()
            # Drop surplus frames in case the camera ignores the requested rate; 0.8 absorbs jitter.
            if now - t_last < 0.8 * self.min_interval:
                continue
            t_last = now
            with self.cond:
                self.frame, self.seq = (frame[:, :-self.crop] if self.crop else frame), self.seq + 1
                self.cond.notify_all()

    def newer_than(self, seq, timeout):
        """Waits up to timeout for a frame newer than seq. Returns (frame, seq), maybe unchanged."""
        with self.cond:
            self.cond.wait_for(lambda: self.seq > seq or self.dead, timeout)
            return self.frame, self.seq

    def stop(self):
        self.running = False
        self.join(timeout=2)


def save_frame(frame, out_dir):
    path = out_dir / f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}.jpg"
    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"Saved {path}", flush=True)
    return path


def button_rect(name, image_h):
    x, y, bw, bh = BUTTONS[name]
    return x, image_h + y, x + bw, image_h + y + bh


def button_at(x, y, image_h, enabled):
    for name in enabled:
        x0, y0, x1, y1 = button_rect(name, image_h)
        if x0 <= x <= x1 and y0 <= y <= y1:
            return name
    return None


def draw_detections(img, dets, names):
    for c, conf, x1, y1, x2, y2 in dets:
        name = names[c]
        color = CLASS_COLORS.get(name, (255, 255, 255))
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        label = f"{name} {conf:.0%}"
        (tw, th), _ = cv2.getTextSize(label, FONT, 0.45, 1)
        ty = y1 - 4 if y1 - th - 8 >= 0 else y2 + th + 4  # above the box, or below at the top edge
        cv2.rectangle(img, (x1, ty - th - 4), (x1 + tw + 6, ty + 3), color, -1)
        cv2.putText(img, label, (x1 + 3, ty), FONT, 0.45, (0, 0, 0), 1, cv2.LINE_AA)


def render(frame, ui):
    """Camera image (with detections) and a control panel underneath."""
    h, w = frame.shape[:2]
    canvas = np.full((h + PANEL_H, w, 3), 38, np.uint8)
    canvas[:h] = frame
    if ui["detect_on"]:
        draw_detections(canvas[:h], ui["dets"], ui["names"])
    if ui["saved_text"]:
        cv2.rectangle(canvas, (0, 0), (w - 1, h - 1), (255, 255, 255), 6)

    x0, y0, x1, y1 = button_rect("capture", h)
    cy = (y0 + y1) // 2
    fill = (30, 120, 45) if ui["pressed"] else (70, 200, 95) if ui["hover"] == "capture" else (50, 165, 75)
    cv2.rectangle(canvas, (x0, y0), (x1, y1), fill, -1)
    cv2.circle(canvas, (x0 + 22, cy), 8, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.putText(canvas, "Capture", (x0 + 40, cy + 7), FONT, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
    info_x = x1 + 14

    if ui["names"] is not None:
        x0, y0, x1, y1 = button_rect("detect", h)
        on, hot = ui["detect_on"], ui["hover"] == "detect"
        fill = ((200, 130, 30) if hot else (170, 105, 20)) if on else ((95, 95, 95) if hot else (70, 70, 70))
        cv2.rectangle(canvas, (x0, y0), (x1, y1), fill, -1)
        cv2.putText(canvas, f"Detect {'ON' if on else 'OFF'}", (x0 + 10, cy + 6), FONT, 0.55,
                    (255, 255, 255), 2 if on else 1, cv2.LINE_AA)
        info_x = x1 + 14

    if ui["saved_text"]:
        cv2.putText(canvas, ui["saved_text"], (info_x, cy + 5), FONT, 0.5, (90, 230, 90), 1, cv2.LINE_AA)
    elif ui["detect_on"]:
        for row, name in enumerate(("resistor", "capacitor")):
            n = sum(1 for d in ui["dets"] if ui["names"][d[0]] == name)
            cv2.putText(canvas, f"{name.capitalize()}s: {n}", (info_x, h + 24 + row * 20), FONT, 0.48,
                        CLASS_COLORS[name], 1, cv2.LINE_AA)

    lines = [f"{ui['fps']:4.1f} fps"] + ([f"{ui['det_ms']:.0f} ms"] if ui["detect_on"] else [])
    for row, text in enumerate(lines):
        (tw, _), _ = cv2.getTextSize(text, FONT, 0.48, 1)
        y = cy + 5 if len(lines) == 1 else h + 24 + row * 20
        cv2.putText(canvas, text, (w - tw - 12, y), FONT, 0.48, (200, 200, 200), 1, cv2.LINE_AA)
    return canvas


def show_message(text, w, h):
    canvas = np.full((h + PANEL_H, w, 3), 38, np.uint8)
    cv2.putText(canvas, text, (20, h // 2), FONT, 0.7, (220, 220, 220), 1, cv2.LINE_AA)
    cv2.imshow(WINDOW, canvas)
    cv2.waitKey(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="/dev/video0")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=15,
                    help="frame-rate cap; in dim light the camera's auto-exposure may run slower")
    ap.add_argument("--out", type=Path, default=Path.home() / "vizion" / "captures")
    ap.add_argument("--crop-right", type=int, default=-1,
                    help="columns to drop from the right edge (-1 = auto-detect sensor padding)")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL,
                    help="exported detector (NCNN dir); missing => preview only")
    ap.add_argument("--conf", type=float, default=0.25, help="confidence needed before a part is drawn")
    ap.add_argument("--imgsz", type=int, default=None, help="detector input size (default: from the model)")
    ap.add_argument("--stats", action="store_true", help="print frame-gap and detection-rate stats every 5 s")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    cap = open_camera(args.device, args.width, args.height, args.fps)
    crop = detect_right_padding(cap) if args.crop_right < 0 else args.crop_right
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Camera {args.device}: {w}x{h} @ {cap.get(cv2.CAP_PROP_FPS):.0f} fps (cap {args.fps}), "
          f"cropping {crop}px padding -> {w - crop}x{h}; saving to {args.out}", flush=True)

    capture_requested = False

    def on_usr1(_signum, _frame):
        nonlocal capture_requested
        capture_requested = True

    signal.signal(signal.SIGUSR1, on_usr1)

    # GUI_NORMAL drops the Qt toolbar so the window fits the 1450x906 desktop.
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE | cv2.WINDOW_GUI_NORMAL)
    cv2.moveWindow(WINDOW, 40, 60)

    detector = tracker = None
    if args.model.exists():
        show_message("Loading detector...", w - crop, h)
        from detector import DetectorProcess
        from tracker import Tracker

        try:
            detector = DetectorProcess(args.model, conf=DET_CANDIDATE_CONF, imgsz=args.imgsz)
            tracker = Tracker(len(detector.names), show_conf=args.conf, hide_conf=0.6 * args.conf)
            print(f"Detector {args.model.name} @ {detector.imgsz}: classes {detector.names}", flush=True)
        except (EOFError, OSError) as e:
            print(f"Detector failed to start ({e!r}); preview only", flush=True)
            detector = None
    else:
        print(f"No model at {args.model}; preview only", flush=True)

    ui = {"hover": None, "pressed": False, "saved_text": "", "fps": 0.0, "det_ms": 0.0, "dets": [],
          "detect_on": detector is not None, "names": detector.names if detector else None}
    enabled = ("capture", "detect") if detector else ("capture",)

    def toggle_detection():
        ui["detect_on"] = not ui["detect_on"]
        tracker.reset()
        ui["dets"] = []

    def on_mouse(event, x, y, _flags, _param):
        nonlocal capture_requested
        target = button_at(x, y, h, enabled)
        if event == cv2.EVENT_MOUSEMOVE:
            ui["hover"] = target
        elif event == cv2.EVENT_LBUTTONDOWN:
            if target == "capture":
                capture_requested = True
            elif target == "detect":
                toggle_detection()

    cv2.setMouseCallback(WINDOW, on_mouse)
    grabber = FrameGrabber(cap, crop, args.fps)
    grabber.start()
    seq = sent_seq = 0
    frame, t_prev = None, time.monotonic()
    saved_text, saved_at = "", float("-inf")
    stats = {"t0": time.monotonic(), "frames": 0, "max_gap": 0.0, "dets": 0}

    try:
        while True:
            latest, latest_seq = grabber.newer_than(seq, timeout=0.03)
            if grabber.dead:
                raise SystemExit("Camera stopped delivering frames (unplugged?)")

            if detector:
                result = detector.poll()
                if result and ui["detect_on"]:
                    _, dets, ms = result
                    tracker.update(dets)
                    ui["dets"] = tracker.visible()
                    ui["det_ms"] = ms if ui["det_ms"] == 0 else 0.8 * ui["det_ms"] + 0.2 * ms
                    stats["dets"] += 1
                if ui["detect_on"] and not detector.busy and latest_seq > sent_seq:
                    detector.submit(latest_seq, latest)
                    sent_seq = latest_seq
                if detector.dead:
                    print("Detector process died; continuing as preview only", flush=True)
                    detector, enabled = None, ("capture",)
                    ui.update(detect_on=False, names=None, dets=[])

            if latest_seq > seq:
                seq, frame = latest_seq, latest
                now = time.monotonic()
                dt, t_prev = now - t_prev, now
                ui["fps"] = 1 / dt if ui["fps"] == 0 else 0.9 * ui["fps"] + 0.1 / dt
                stats["frames"] += 1
                stats["max_gap"] = max(stats["max_gap"], dt)

                if capture_requested:
                    capture_requested = False
                    save_frame(frame, args.out)
                    saved_text, saved_at = f"Saved {datetime.now():%H:%M:%S}", now
                since_save = now - saved_at
                ui["saved_text"] = saved_text if since_save < FLASH_S else ""
                ui["pressed"] = since_save < PRESS_S
                cv2.imshow(WINDOW, render(frame, ui))

                if args.stats and now - stats["t0"] >= 5:
                    span = now - stats["t0"]
                    print(f"video {stats['frames'] / span:4.1f} fps, max gap {stats['max_gap'] * 1000:3.0f} ms | "
                          f"detections {stats['dets'] / span:4.1f}/s, {ui['det_ms']:3.0f} ms each", flush=True)
                    stats = {"t0": now, "frames": 0, "max_gap": 0.0, "dets": 0}

            key = cv2.waitKey(1) & 0xFF
            if key in (ord(" "), ord("c")):
                capture_requested = True
            elif key == ord("d") and detector:
                toggle_detection()
            elif key in (ord("q"), 27):
                break
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        grabber.stop()
        if detector:
            detector.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
