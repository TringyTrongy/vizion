"""Train the resistor/capacitor detector on data/vizion (see prepare_dataset.py).

    .venv/Scripts/python.exe scripts/train.py --model yolo26n.pt --epochs 120
    .venv/Scripts/python.exe scripts/train.py --model runs/yolo26n/weights/best.pt --epochs 60 --name yolo26n_v2
"""
import argparse
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo26n.pt",
                    help="pretrained weights in models/pretrained/, or a path (e.g. a previous run's best.pt)")
    ap.add_argument("--epochs", type=int, default=120)
    ap.add_argument("--patience", type=int, default=30)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--name", default=None)
    args = ap.parse_args()

    weights = ROOT / args.model if (ROOT / args.model).is_file() else ROOT / "models" / "pretrained" / args.model
    model = YOLO(weights if weights.is_file() else args.model)  # a bare name like yolo26n.pt is downloaded
    model.train(
        data=str(ROOT / "data" / "vizion" / "data.yaml"),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=args.patience,
        cache="ram",
        workers=4,
        project=str(ROOT / "runs"),
        name=args.name or Path(args.model).stem,
        exist_ok=True,
        seed=0,
        # Parts lie at any angle on the bench and the webcam's auto-exposure swings
        # brightness, so add vertical flips and mild rotation; default hsv_v=0.4 covers brightness.
        flipud=0.5,
        degrees=10,
        plots=True,
    )
    metrics = model.val(split="test")
    print(f"TEST mAP50={metrics.box.map50:.3f} mAP50-95={metrics.box.map:.3f}")
    for i, name in model.names.items():
        p, r, ap50, ap = metrics.box.class_result(i)
        print(f"TEST {name:10s} P={p:.3f} R={r:.3f} mAP50={ap50:.3f} mAP50-95={ap:.3f}")


if __name__ == "__main__":  # required on Windows: dataloader workers re-import this module
    main()
