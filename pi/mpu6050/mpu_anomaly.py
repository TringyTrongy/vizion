#!/usr/bin/env python3
"""Motor anomaly model trained on NORMAL vibration only (MPU6050), with a live alert.

Features: the signal is cut into 1 s windows (100 samples, 50% overlap). Each window gives, per
axis (ax, ay, az, gx, gy, gz), the standard deviation (vibration energy) and the peak-to-peak
range: 12 numbers. The model is the mean and spread of those 12 numbers over the normal runs; a
window's anomaly score is its largest robust z-score (|x - median| / (1.4826 * MAD)). The
threshold is the 99.5th percentile of the normal training scores times a 1.5 safety margin, so
normal runs very rarely cross it. An alert needs 3 windows in a row over the threshold (debounce).

    python mpu_anomaly.py train data/normal_1.csv data/normal_2.csv data/normal_3.csv
    python mpu_anomaly.py evaluate data/*.csv                 # alert rate per run, normal and fault
    python mpu_anomaly.py false-alarms data/check_normal_*.csv  # alerts over 5 unseen normal runs
    python mpu_anomaly.py live                                 # reads the sensor, prints ALERT
"""
import argparse
import csv
import json
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

AXES = ["ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps"]
WIN, HOP = 100, 50
CONFIRM = 3
MODEL = Path(__file__).resolve().parent / "model.json"


def load(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return np.array([[float(r[a]) for a in AXES] for r in rows])


def features(sig):
    """(n_windows, 12): std and peak-to-peak per axis for each 1 s window."""
    out = []
    for s in range(0, len(sig) - WIN + 1, HOP):
        w = sig[s:s + WIN]
        out.append(np.concatenate([w.std(axis=0), np.ptp(w, axis=0)]))
    return np.array(out)


class Model:
    def __init__(self, median, mad, threshold):
        self.median, self.mad, self.threshold = np.asarray(median), np.asarray(mad), float(threshold)

    @classmethod
    def fit(cls, normal_feats, margin=1.5):
        med = np.median(normal_feats, axis=0)
        mad = 1.4826 * np.median(np.abs(normal_feats - med), axis=0)
        mad = np.maximum(mad, 1e-6)
        m = cls(med, mad, 0)
        m.threshold = float(np.percentile(m.scores(normal_feats), 99.5) * margin)
        return m

    def scores(self, feats):
        return np.max(np.abs(feats - self.median) / self.mad, axis=1)

    def alerts(self, feats):
        """Number of alerts (3 windows in a row over the threshold, then re-armed)."""
        n, run = 0, 0
        for over in self.scores(feats) > self.threshold:
            run = run + 1 if over else 0
            if run == CONFIRM:
                n += 1
        return n

    def save(self, path=MODEL):
        Path(path).write_text(json.dumps({"median": self.median.tolist(), "mad": self.mad.tolist(),
                                          "threshold": self.threshold, "window": WIN, "hop": HOP,
                                          "confirm": CONFIRM, "axes": AXES}, indent=1))

    @classmethod
    def load(cls, path=MODEL):
        d = json.loads(Path(path).read_text())
        return cls(d["median"], d["mad"], d["threshold"])


def cmd_train(files):
    feats = np.vstack([features(load(f)) for f in files])
    m = Model.fit(feats)
    m.save()
    print(f"Trained on {len(files)} normal runs, {len(feats)} windows. Threshold {m.threshold:.2f} -> {MODEL}")


def cmd_evaluate(files):
    m = Model.load()
    print(f"{'run':28} {'windows':>7} {'over thr':>8} {'alerts':>6} {'max score':>9}")
    for f in files:
        feats = features(load(f))
        s = m.scores(feats)
        print(f"{Path(f).name:28} {len(s):7d} {int((s > m.threshold).sum()):8d} {m.alerts(feats):6d} {s.max():9.2f}")


def cmd_false_alarms(files):
    m = Model.load()
    total = sum(m.alerts(features(load(f))) for f in files)
    minutes = sum(len(load(f)) for f in files) / 100 / 60
    print(f"{total} false alarms over {len(files)} normal runs ({minutes:.1f} min); threshold {m.threshold:.2f}")


def cmd_live():
    from mpu_logger import Mpu6050

    m, mpu = Model.load(), Mpu6050()
    buf, run, n = deque(maxlen=WIN), 0, 0
    nxt = time.monotonic()
    while True:
        buf.append(mpu.read())
        n += 1
        if len(buf) == WIN and n % HOP == 0:
            score = float(m.scores(features(np.array(buf)))[0])
            run = run + 1 if score > m.threshold else 0
            state = "ALERT" if run >= CONFIRM else "normal"
            print(f"{time.strftime('%H:%M:%S')} score {score:6.2f} (threshold {m.threshold:.2f}) {state}", flush=True)
        nxt += 0.01
        time.sleep(max(0.0, nxt - time.monotonic()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["train", "evaluate", "false-alarms", "live"])
    ap.add_argument("files", nargs="*")
    a = ap.parse_args()
    if a.command != "live" and not a.files:
        sys.exit("give the CSV files")
    {"train": cmd_train, "evaluate": cmd_evaluate, "false-alarms": cmd_false_alarms}.get(
        a.command, lambda _: cmd_live())(a.files)


if __name__ == "__main__":
    main()
