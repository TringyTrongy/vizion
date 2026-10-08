"""Resistor/capacitor detector: an exported Ultralytics model (NCNN).

Inference keeps the CPU busy and the NCNN binding holds Python's GIL while it runs, so a
detection *thread* stalls the preview by up to ~120 ms (measured on the Pi 5). The preview
therefore uses DetectorProcess, which runs the model in a separate process.

Frames are colour-balanced before detection (balance_colours).
"""
import multiprocessing as mp
import os
import time
from pathlib import Path

import cv2
import numpy as np

BALANCE_GAIN_LIMITS = (0.5, 2.0)


def balance_colours(frame):
    """Grey-world white balance: scales blue, green and red so the scene averages to grey.

    In bright light the webcam's automatic white balance tints the whole picture cyan (red drops to
    ~70% of green and blue), blue capacitors wash out, and the model's capacitor confidence falls
    from ~0.9 to ~0.3. On 24 bright live frames, balancing first found the capacitor in 24 of 24
    instead of 15; the labelled webcam frames (52/52), the public test split and empty-room frames
    (no false boxes) were unchanged. Clipped and very dark pixels are ignored, and the gains are
    limited, so a scene filled by one coloured object is not pushed to an extreme.
    """
    sample = frame[::4, ::4].reshape(-1, 3).astype(np.float32)
    usable = (sample.max(axis=1) < 250) & (sample.mean(axis=1) > 20)
    means = sample[usable].mean(axis=0) if usable.sum() > 500 else sample.mean(axis=0)
    gains = np.clip(means.mean() / np.maximum(means, 1.0), *BALANCE_GAIN_LIMITS)
    lut = np.clip(np.arange(256, dtype=np.float32)[:, None] * gains, 0, 255).astype(np.uint8)
    return cv2.LUT(frame, lut.reshape(256, 1, 3))


class Detector:
    def __init__(self, model_path, conf=0.4, imgsz=None, balance=True):
        from ultralytics import YOLO  # slow import (torch); only paid when detection is used

        if imgsz is None:  # NCNN models have a fixed input size; read it from the export metadata
            import yaml

            imgsz = yaml.safe_load((Path(model_path) / "metadata.yaml").read_text())["imgsz"][0]
        self.model = YOLO(str(model_path), task="detect")
        self.names = self.model.names
        self.conf, self.imgsz, self.balance = conf, imgsz, balance
        self.model.predict(np.zeros((480, 640, 3), np.uint8), imgsz=imgsz, verbose=False)  # warm-up

    def __call__(self, frame):
        """Returns ([(class_id, confidence, x1, y1, x2, y2), ...], milliseconds)."""
        t0 = time.perf_counter()
        if self.balance:
            frame = balance_colours(frame)
        r = self.model.predict(frame, imgsz=self.imgsz, conf=self.conf, verbose=False)[0]
        b = r.boxes
        dets = [(int(c), float(s), *map(int, xyxy))
                for c, s, xyxy in zip(b.cls.tolist(), b.conf.tolist(), b.xyxy.tolist())]
        return dets, (time.perf_counter() - t0) * 1000


def _serve(conn, model_path, conf, imgsz):
    cores = os.cpu_count() or 1
    if hasattr(os, "sched_setaffinity") and cores >= 4:
        os.sched_setaffinity(0, set(range(1, cores)))  # leave core 0 to the camera and preview
    import torch

    torch.set_num_threads(1)  # pre/post-processing is tiny; NCNN does the heavy lifting
    det = Detector(model_path, conf=conf, imgsz=imgsz)
    conn.send((det.names, det.imgsz))
    while (msg := conn.recv()) is not None:
        seq, frame = msg
        conn.send((seq, *det(frame)))


class DetectorProcess:
    """Runs Detector in a child process with one frame in flight, so results are never stale."""

    def __init__(self, model_path, conf, imgsz=None):
        ctx = mp.get_context("spawn")  # the parent has a Qt window and threads; don't fork them
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=_serve, args=(child, str(model_path), conf, imgsz), daemon=True)
        self.proc.start()
        child.close()
        self.names, self.imgsz = self.conn.recv()  # waits for the model to load (~10 s on the Pi)
        self.busy = self.dead = False

    def submit(self, seq, frame):
        try:
            self.conn.send((seq, frame))
            self.busy = True
        except OSError:
            self.dead = True

    def poll(self):
        """(seq, detections, milliseconds) if a result is ready, else None."""
        try:
            if self.busy and self.conn.poll():
                self.busy = False
                return self.conn.recv()
        except (EOFError, OSError):  # the child process died
            self.busy, self.dead = False, True
        return None

    def close(self):
        try:
            self.conn.send(None)
        except OSError:
            pass
        self.proc.join(timeout=3)
        if self.proc.is_alive():
            self.proc.terminate()
