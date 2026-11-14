#!/usr/bin/env python3
"""Two-stream pipeline: two video streams detected at the same time, FPS measured per stream.

Each stream has its own reader thread and its own detector process (detector.DetectorProcess,
so the two NCNN models run in parallel on separate cores). A source is a camera device
(/dev/video0, 0) or a folder / video file, so the second stream can be a second USB camera or a
recording when only one camera is plugged in.

    .venv/bin/python two_stream.py --a /dev/video0 --b /dev/video2 --seconds 60
    .venv/bin/python two_stream.py --a /dev/video0 --b ../data/webcam/raw --seconds 60

Every 5 s it prints per-stream video FPS, detection FPS and detector ms, and at the end it writes
logs/two_stream.csv (one row per 5 s window per stream) and a summary line per stream.
"""
import argparse
import csv
import statistics
import threading
import time
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = HERE / "models" / "vizion_ncnn_model"
IMAGE_EXT = (".jpg", ".jpeg", ".png")


class Source:
    """Newest frame from a camera, a video file or an image folder (looped), read in a thread."""

    def __init__(self, spec, fps):
        self.spec, self.fps = spec, fps
        self.images, self.cap = None, None
        p = Path(spec)
        if p.is_dir():
            self.images = [cv2.imread(str(f)) for f in sorted(p.iterdir()) if f.suffix.lower() in IMAGE_EXT]
            self.images = [i for i in self.images if i is not None]
            if not self.images:
                raise SystemExit(f"No images in {spec}")
        else:
            self.cap = cv2.VideoCapture(int(spec) if spec.isdigit() else spec)
            if not self.cap.isOpened():
                raise SystemExit(f"Cannot open {spec}")
            self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.frame, self.seq, self.frames = None, 0, 0
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        interval, i, nxt = 1.0 / self.fps, 0, time.monotonic()
        while not self.stop.is_set():
            if self.images is not None:
                nxt += interval
                time.sleep(max(0.0, nxt - time.monotonic()))
                frame = self.images[(i // int(self.fps * 2)) % len(self.images)].copy()  # 2 s per image
                i += 1
            else:
                ok, frame = self.cap.read()
                if not ok:
                    if Path(self.spec).is_file():  # a recording: loop it
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    time.sleep(0.05)
                    continue
            with self.lock:
                self.frame, self.seq, self.frames = frame, self.seq + 1, self.frames + 1

    def newest(self):
        with self.lock:
            return self.seq, self.frame

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        if self.cap is not None:
            self.cap.release()


class Stream:
    def __init__(self, name, spec, model, fps, imgsz):
        from detector import DetectorProcess

        self.name, self.spec = name, spec
        self.source = Source(spec, fps)
        self.det = DetectorProcess(str(model), conf=0.25, imgsz=imgsz)
        self.sent = 0
        self.window = {"dets": 0, "ms": [], "frames0": 0}
        self.rows = []

    def step(self):
        """Collects a finished detection and submits the newest frame. Returns True if busy work happened."""
        did = False
        result = self.det.poll()
        if result:
            _, dets, ms = result
            self.window["dets"] += 1
            self.window["ms"].append(ms)
            self.last_count = len(dets)
            did = True
        seq, frame = self.source.newest()
        if frame is not None and seq > self.sent and not self.det.busy:
            self.det.submit(seq, frame)
            self.sent = seq
            did = True
        return did

    def report(self, span, t_wall):
        w = self.window
        video_fps = (self.source.frames - w["frames0"]) / span
        det_fps = w["dets"] / span
        ms = statistics.median(w["ms"]) if w["ms"] else 0.0
        row = {"wall_time": t_wall, "stream": self.name, "source": self.spec, "video_fps": round(video_fps, 2),
               "detect_fps": round(det_fps, 2), "detect_ms_median": round(ms, 1),
               "objects_last": getattr(self, "last_count", 0)}
        self.rows.append(row)
        self.window = {"dets": 0, "ms": [], "frames0": self.source.frames}
        return row

    def close(self):
        self.source.close()
        self.det.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True, help="stream A: camera (/dev/video0 or 0), video file or image folder")
    ap.add_argument("--b", required=True, help="stream B: as --a")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--imgsz", type=int, default=None)
    ap.add_argument("--fps", type=float, default=15)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--csv", type=Path, default=HERE / "logs" / "two_stream.csv")
    args = ap.parse_args()

    streams = [Stream("A", args.a, args.model, args.fps, args.imgsz), Stream("B", args.b, args.model, args.fps, args.imgsz)]
    print("Loading both models...", flush=True)
    for s in streams:
        s.source.start()
    t0 = t_win = time.monotonic()
    try:
        while time.monotonic() - t0 < args.seconds:
            busy = False
            for s in streams:
                busy |= s.step()
            if not busy:
                time.sleep(0.002)
            now = time.monotonic()
            if now - t_win >= 5:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                parts = [s.report(now - t_win, stamp) for s in streams]
                print(" | ".join(f"{r['stream']}: video {r['video_fps']:4.1f} fps, detect {r['detect_fps']:4.1f} fps, "
                                 f"{r['detect_ms_median']:5.1f} ms" for r in parts), flush=True)
                t_win = now
    finally:
        for s in streams:
            s.close()

    rows = [r for s in streams for r in s.rows[1:]]  # the first window includes model loading
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0].keys()) if rows else ["stream"])
        w.writeheader()
        w.writerows(rows)
    for s in streams:
        rs = s.rows[1:]
        if rs:
            print(f"Stream {s.name} ({s.spec}): video {statistics.mean(r['video_fps'] for r in rs):.1f} fps, "
                  f"detection {statistics.mean(r['detect_fps'] for r in rs):.1f} fps, "
                  f"detector {statistics.median(r['detect_ms_median'] for r in rs):.1f} ms median "
                  f"over {len(rs) * 5} s")
    print(f"Wrote {args.csv}")


if __name__ == "__main__":
    main()
