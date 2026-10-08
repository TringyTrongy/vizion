"""Export a trained run to NCNN (fastest on the Pi's CPU) and copy it to pi/models/.

    .venv/Scripts/python.exe scripts/export.py --run yolo26n
"""
import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="yolo26n", help="training run name under runs/")
    # 480 matches the webcam's 480 rows, scores like 640 on the test set and halves Pi CPU load.
    ap.add_argument("--imgsz", type=int, default=480)
    ap.add_argument("--name", default="vizion_ncnn_model", help="folder name under pi/models/")
    args = ap.parse_args()

    best = ROOT / "runs" / args.run / "weights" / "best.pt"
    exported = Path(YOLO(best).export(format="ncnn", imgsz=args.imgsz))
    dest = ROOT / "pi" / "models" / args.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(exported, dest)
    print(f"Exported {best} -> {dest}")


if __name__ == "__main__":
    main()
