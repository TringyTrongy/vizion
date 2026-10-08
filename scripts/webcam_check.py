"""Count how many hand-labelled webcam parts a model finds (IoU >= 0.5, right class).

    .venv/Scripts/python.exe scripts/webcam_check.py runs/yolo26n/weights/best.pt [--imgsz 480] [--conf 0.4]
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent


def iou(a, b):
    ix, iy = max(0, min(a[2], b[2]) - max(a[0], b[0])), max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("weights")
    ap.add_argument("--imgsz", type=int, default=480)
    ap.add_argument("--conf", type=float, default=0.4)
    args = ap.parse_args()
    model = YOLO(ROOT / args.weights)
    doc = json.loads((ROOT / "data" / "webcam" / "labels.json").read_text())
    per_scene = {}
    for name, entry in doc["images"].items():
        r = model.predict(ROOT / "data" / "webcam" / "raw" / name, imgsz=args.imgsz, conf=args.conf, verbose=False)[0]
        preds = [(int(c), *b) for c, b in zip(r.boxes.cls.tolist(), r.boxes.xyxy.tolist())]
        s = per_scene.setdefault(entry["scene"], Counter())
        used = set()
        for c, *box in entry["boxes"]:
            hit = next((i for i, (pc, *pb) in enumerate(preds) if i not in used and pc == c and iou(box, pb) >= 0.5), None)
            s[f"{model.names[c]} found" if hit is not None else f"{model.names[c]} missed"] += 1
            if hit is not None:
                used.add(hit)
        s["false boxes"] += len(preds) - len(used)
    for scene, s in sorted(per_scene.items()):
        tag = " (held-out test)" if scene in doc["test_scenes"] else " (in training data)"
        print(f"{scene}{tag}: {dict(s)}")
    total = sum(per_scene.values(), Counter())
    found = sum(v for k, v in total.items() if k.endswith("found"))
    labelled = found + sum(v for k, v in total.items() if k.endswith("missed"))
    print(f"TOTAL found {found}/{labelled}, false boxes {total['false boxes']}")


if __name__ == "__main__":
    main()
