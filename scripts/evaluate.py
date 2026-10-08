"""Score a trained run on val/test at several input sizes, and annotate real webcam captures.

    .venv/Scripts/python.exe scripts/evaluate.py --run yolo26n --sizes 640 480 --images captures
"""
import argparse
from pathlib import Path

import cv2
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="yolo26n")
    ap.add_argument("--sizes", type=int, nargs="+", default=[640, 480])
    ap.add_argument("--images", type=Path, help="folder of captures to annotate (optional)")
    ap.add_argument("--conf", type=float, default=0.4)
    args = ap.parse_args()

    model = YOLO(ROOT / "runs" / args.run / "weights" / "best.pt")
    webcam_test = ROOT / "data" / "webcam" / "test" / "test.yaml"  # held-out real webcam scenes
    for sz in args.sizes:
        runs = [("val", {"split": "val"}), ("test", {"split": "test"})]
        if webcam_test.exists():
            runs.append(("webcam", {"data": str(webcam_test), "split": "val"}))
        for label, kw in runs:
            m = model.val(imgsz=sz, plots=False, verbose=False, **kw)
            # class_result() is indexed by position among the classes present, not by class id
            recall = {model.names[int(c)]: m.box.class_result(k)[1] for k, c in enumerate(m.box.ap_class_index)}
            print(f"{label:6s} @ {sz}: mAP50 {m.box.map50:.3f}  mAP50-95 {m.box.map:.3f}  "
                  + "  ".join(f"{n} recall {r:.3f}" for n, r in recall.items()), flush=True)

    if args.images:
        out = ROOT / "runs" / args.run / "captures_annotated"
        out.mkdir(parents=True, exist_ok=True)
        for path in sorted(args.images.glob("*.jpg")):
            for sz in args.sizes:
                r = model.predict(path, imgsz=sz, conf=args.conf, verbose=False)[0]
                found = [(model.names[int(c)], round(float(s), 2)) for c, s in zip(r.boxes.cls, r.boxes.conf)]
                print(f"{path.name} @ {sz}: {found}", flush=True)
                cv2.imwrite(str(out / f"{path.stem}_{sz}.jpg"), r.plot(line_width=2))
        print(f"annotated images in {out}")


if __name__ == "__main__":  # required on Windows: dataloader workers re-import this module
    main()
