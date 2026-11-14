#!/usr/bin/env python3
"""Drift report: are today's camera frames still like the frames the system was validated on?

Compares a BASELINE set of frames with a RECENT set (folders of .jpg/.png, e.g. the first week's
captures vs today's) on what drifts in a fixed camera rig:
    brightness, contrast, colour cast (R/G and B/G), sharpness (variance of the Laplacian)
and, with --model, the detector itself: parts found per frame and their mean confidence.
Each input statistic gets a PSI (population stability index) on a 10-bin histogram:
    PSI < 0.1 stable · 0.1-0.25 watch · > 0.25 drifted (re-learn the empty table / retrain).

    python drift_report.py BASELINE_DIR RECENT_DIR [--model models/vizion_ncnn_model] [--out report.md]
"""
import argparse
import statistics
import time
from pathlib import Path

import cv2
import numpy as np

EXT = (".jpg", ".jpeg", ".png")


def frame_stats(img):
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    b, g, r = (img[..., i].mean() for i in range(3))
    return {"brightness": float(grey.mean()), "contrast": float(grey.std()),
            "r_over_g": float(r / max(g, 1)), "b_over_g": float(b / max(g, 1)),
            "sharpness": float(cv2.Laplacian(grey, cv2.CV_64F).var())}


def psi(base, recent, bins=10):
    edges = np.unique(np.quantile(base, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    p = np.histogram(base, edges)[0] / len(base)
    q = np.histogram(recent, edges)[0] / len(recent)
    p, q = np.clip(p, 1e-4, None), np.clip(q, 1e-4, None)
    return float(np.sum((q - p) * np.log(q / p)))


def verdict(v):
    return "stable" if v < 0.1 else "watch" if v < 0.25 else "DRIFTED"


def load(folder):
    files = sorted(f for f in Path(folder).iterdir() if f.suffix.lower() in EXT)
    return [(f.name, img) for f in files if (img := cv2.imread(str(f))) is not None]


def detect(model, frames):
    from detector import balance_colours

    found, confs = [], []
    for _, img in frames:
        r = model.predict(balance_colours(img), imgsz=480, conf=0.25, verbose=False)[0]
        found.append(len(r.boxes))
        confs += [float(c) for c in r.boxes.conf]
    return found, confs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline")
    ap.add_argument("recent")
    ap.add_argument("--model", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    base, recent = load(a.baseline), load(a.recent)
    if not base or not recent:
        raise SystemExit("both folders need images")
    bs = [frame_stats(i) for _, i in base]
    rs = [frame_stats(i) for _, i in recent]
    lines = [f"# Drift report ({time.strftime('%Y-%m-%d %H:%M')})", "",
             f"Baseline: `{a.baseline}` ({len(base)} frames) · Recent: `{a.recent}` ({len(recent)} frames)", "",
             "| Statistic | Baseline mean | Recent mean | Change | PSI | Verdict |", "|---|---|---|---|---|---|"]
    worst = 0.0
    for k in bs[0]:
        x, y = np.array([s[k] for s in bs]), np.array([s[k] for s in rs])
        v = psi(x, y)
        worst = max(worst, v)
        change = (y.mean() - x.mean()) / x.mean() * 100 if x.mean() else 0
        lines.append(f"| {k} | {x.mean():.3f} | {y.mean():.3f} | {change:+.1f}% | {v:.3f} | {verdict(v)} |")
    if a.model:
        from ultralytics import YOLO

        m = YOLO(str(a.model), task="detect")
        bf, bc = detect(m, base)
        rf, rc = detect(m, recent)
        lines += ["", "| Detector | Baseline | Recent |", "|---|---|---|",
                  f"| parts per frame (mean) | {statistics.mean(bf):.2f} | {statistics.mean(rf):.2f} |",
                  f"| mean confidence | {statistics.mean(bc) if bc else 0:.3f} | {statistics.mean(rc) if rc else 0:.3f} |",
                  f"| confidence PSI | {psi(np.array(bc), np.array(rc)) if bc and rc else 0:.3f} | |"]
    lines += ["", f"**Overall: {verdict(worst)}** (largest input PSI {worst:.3f}). "
              "PSI < 0.1 stable, 0.1-0.25 watch, > 0.25 drifted: re-learn the empty table, check the light, "
              "and retrain if the detector's confidence fell."]
    text = "\n".join(lines) + "\n"
    print(text)
    if a.out:
        a.out.write_text(text)


if __name__ == "__main__":
    main()
