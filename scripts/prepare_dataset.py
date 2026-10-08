"""Merge the raw datasets into one 2-class YOLO dataset: 0 = resistor, 1 = capacitor.

    python -I scripts/prepare_dataset.py            (after scripts/download_data.sh + unzip)

Sources (data/raw/<name>/x/ = extracted zip):
  electrocom61  640x640, 61 classes, own train/valid/test split. Its boxes include the leads,
                unlike the other sources (body only). Images containing resistors are left
                out; capacitor boxes are shrunk to the body (GrabCut, then an opening removes
                the thin legs), and images where that fails are left out. Images without
                resistors/capacitors are kept as negatives when they hold look-alike parts.
  kaggle_rdci   4000px phone photos of breadboards, darknet labels drawn on the EXIF-rotated
                view. Rotated, then cut into overlapping tiles so parts are ~60 px at 640.
  kaggle_resseg resistor polygons (VGG Image Annotator) -> bounding boxes.
"""
import json
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "vizion"
NAMES = ["resistor", "capacitor"]
SPLITS = ("train", "val", "test")
SEED = 0

# ElectroCom61 class ids (from its data.yaml).
EC_RESISTOR = 50
EC_CAPACITORS = {13, 14, 20, 26, 38, 39}  # 10uF, 470uF, film, HV ceramic, LV ceramic, MLCC
# Parts that closely resemble resistors (banded inductors, axial diodes, fuses) or ceramic
# capacitors (NTC thermistors); images with them make useful hard negatives.
EC_LOOKALIKES = {16, 21, 33, 43, 60}  # diode, fuse, inductor, NTC thermistor, zener
EC_RANDOM_NEGATIVES = {"train": 60, "val": 15, "test": 10}

RDCI_MAP = {0: 0, 1: 1, 4: 1}  # resistor, ceramic capacitor, electrolytic capacitor
TILE, STRIDE, MIN_VISIBLE = 1600, 1200, 0.6
SAVE_MAX = 1280  # longest side of re-encoded images; training runs at 640

stats = defaultdict(Counter)


def write(split, name, image, boxes, src_path=None):
    """Save an image (PIL or a file to copy) and its YOLO label file."""
    img_dir, lbl_dir = OUT / split / "images", OUT / split / "labels"
    if src_path is not None:
        shutil.copyfile(src_path, img_dir / name)
    else:
        image = image.convert("RGB")
        image.thumbnail((SAVE_MAX, SAVE_MAX))  # labels are normalised, so resizing is free
        image.save(img_dir / name, quality=95)
    stem = Path(name).stem
    (lbl_dir / f"{stem}.txt").write_text("".join(f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}\n" for c, x, y, w, h in boxes))
    stats[split]["images"] += 1
    stats[split]["negatives"] += not boxes
    for b in boxes:
        stats[split][NAMES[b[0]]] += 1


def read_yolo(path):
    return [(int(p[0]), *map(float, p[1:5])) for p in (l.split() for l in open(path)) if len(p) == 5]


def split_of(i, n):
    """Deterministic 80/10/10 split of n shuffled items."""
    return "train" if i < 0.8 * n else "val" if i < 0.9 * n else "test"


def body_box(img, box, pad=4):
    """Shrink a leads-included box to the part's body. Returns pixel (x0, y0, x1, y1) or None.

    GrabCut separates the part from the desk; the legs are thin, so an opening with a disc
    ~45% of the body's thickness removes them and the largest remaining blob is the body."""
    x0, y0, x1, y1 = box
    H, W = img.shape[:2]
    cx0, cy0, cx1, cy1 = max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad, W), min(y1 + pad, H)
    crop = img[cy0:cy1, cx0:cx1]
    mask = np.zeros(crop.shape[:2], np.uint8)
    rect = (x0 - cx0, y0 - cy0, max(x1 - x0, 2), max(y1 - y0, 2))
    try:
        cv2.grabCut(crop, mask, rect, np.zeros((1, 65)), np.zeros((1, 65)), 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    thickness = 2 * cv2.distanceTransform(fg, cv2.DIST_L2, 5).max()
    k = max(3, int(thickness * 0.45)) | 1
    body = cv2.morphologyEx(fg, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, _, st, _ = cv2.connectedComponentsWithStats(body)
    if n < 2:
        return None
    bx, by, bw, bh, _ = st[1 + int(np.argmax(st[1:, 4]))]
    if bw * bh < 0.05 * (x1 - x0) * (y1 - y0):
        return None
    return cx0 + bx, cy0 + by, cx0 + bx + bw, cy0 + by + bh


def electrocom61():
    base = next((RAW / "electrocom61" / "x").glob("*/ElectroCom-61_v2"))
    rng = random.Random(SEED)
    for src_split, split in (("train", "train"), ("valid", "val"), ("test", "test")):
        negatives = []
        for lbl in sorted((base / src_split / "labels").glob("*.txt")):
            labels = read_yolo(lbl)
            classes = {c for c, *_ in labels}
            img = base / src_split / "images" / f"{lbl.stem}.jpg"
            if EC_RESISTOR in classes:
                stats[split]["ec61 resistor images skipped"] += 1
                continue
            boxes = [(1, x, y, w, h) for c, x, y, w, h in labels if c in EC_CAPACITORS]
            if boxes:
                boxes = capacitor_bodies(img, boxes)
                if boxes is None:
                    stats[split]["ec61 capacitor images skipped (body not found)"] += 1
                    continue
            if boxes or classes & EC_LOOKALIKES:
                write(split, f"ec61_{lbl.stem}.jpg", None, boxes, src_path=img)
            else:
                negatives.append(img)
        for img in rng.sample(negatives, min(EC_RANDOM_NEGATIVES[split], len(negatives))):
            write(split, f"ec61_{img.stem}.jpg", None, [], src_path=img)


def capacitor_bodies(img_path, boxes):
    """Normalised leads-included boxes -> body boxes, or None if any body can't be found."""
    img = cv2.imread(str(img_path))
    H, W = img.shape[:2]
    out = []
    for c, x, y, w, h in boxes:
        b = body_box(img, (int((x - w / 2) * W), int((y - h / 2) * H), int((x + w / 2) * W), int((y + h / 2) * H)))
        if b is None:
            return None
        out.append((c, (b[0] + b[2]) / 2 / W, (b[1] + b[3]) / 2 / H, (b[2] - b[0]) / W, (b[3] - b[1]) / H))
    return out


def tile_starts(size):
    if size <= TILE:
        return [0]
    starts = list(range(0, size - TILE + 1, STRIDE))
    last = size - TILE
    if last - starts[-1] < STRIDE // 2:
        starts[-1] = last
    elif starts[-1] != last:
        starts.append(last)
    return starts


def kaggle_rdci():
    folder = RAW / "kaggle_rdci" / "x" / "CompDataset" / "Labeled"
    images = sorted(folder.glob("*.jpg"))
    random.Random(SEED).shuffle(images)
    for i, path in enumerate(images):
        split = split_of(i, len(images))
        im = ImageOps.exif_transpose(Image.open(path))  # labels were drawn on the rotated view
        W, H = im.size
        # Absolute pixel boxes. Diodes and ICs are not labelled; tiles holding them become negatives.
        boxes, others = [], []
        for c, x, y, w, h in read_yolo(path.with_suffix(".txt")):
            box = (RDCI_MAP.get(c), (x - w / 2) * W, (y - h / 2) * H, (x + w / 2) * W, (y + h / 2) * H)
            (boxes if c in RDCI_MAP else others).append(box)

        # Whole photo (parts end up small, ~25 px at 640) for scale variety.
        write(split, f"rdci_{path.stem}_full.jpg", im, to_yolo(boxes, 0, 0, W, H, W, H, min_visible=0))
        if W <= TILE and H <= TILE:
            continue
        # Overlapping tiles keep parts large enough to see colour bands.
        for ty in tile_starts(H):
            for tx in tile_starts(W):
                tw, th = min(TILE, W), min(TILE, H)
                tb = to_yolo(boxes, tx, ty, tx + tw, ty + th, tw, th)
                if tb is None:
                    stats[split]["rdci tiles cutting a part skipped"] += 1
                    continue
                if not tb and not any(_overlap(b, tx, ty, tx + tw, ty + th) for b in others):
                    stats[split]["rdci empty tiles skipped"] += 1
                    continue
                write(split, f"rdci_{path.stem}_{tx}_{ty}.jpg", im.crop((tx, ty, tx + tw, ty + th)), tb)


def _overlap(b, x0, y0, x1, y1):
    return min(b[3], x1) > max(b[1], x0) and min(b[4], y1) > max(b[2], y0)


def to_yolo(boxes, x0, y0, x1, y1, tw, th, min_visible=MIN_VISIBLE):
    """Clip absolute boxes to a window. Returns None if a box is less than min_visible inside."""
    out = []
    for c, bx0, by0, bx1, by1 in boxes:
        if not _overlap((c, bx0, by0, bx1, by1), x0, y0, x1, y1):
            continue
        cx0, cy0, cx1, cy1 = max(bx0, x0), max(by0, y0), min(bx1, x1), min(by1, y1)
        visible = (cx1 - cx0) * (cy1 - cy0) / max((bx1 - bx0) * (by1 - by0), 1e-9)
        if visible < min_visible:
            return None
        out.append((c, ((cx0 + cx1) / 2 - x0) / tw, ((cy0 + cy1) / 2 - y0) / th,
                    (cx1 - cx0) / tw, (cy1 - cy0) / th))
    return out


def kaggle_resseg():
    folder = RAW / "kaggle_resseg" / "x" / "train"
    entries = sorted(json.load(open(folder.parent / "train.json")).values(), key=lambda e: e["filename"])
    random.Random(SEED).shuffle(entries)
    for i, e in enumerate(entries):
        path = folder / e["filename"]
        W, H = Image.open(path).size
        boxes = []
        for r in e["regions"]:
            xs, ys = r["shape_attributes"]["all_points_x"], r["shape_attributes"]["all_points_y"]
            boxes.append((0, max(min(xs), 0), max(min(ys), 0), min(max(xs), W), min(max(ys), H)))
        write(split_of(i, len(entries)), f"resseg_{path.stem}{path.suffix.lower()}", None,
              to_yolo(boxes, 0, 0, W, H, W, H, min_visible=0), src_path=path)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    for split in SPLITS:
        (OUT / split / "images").mkdir(parents=True)
        (OUT / split / "labels").mkdir(parents=True)
    electrocom61()
    kaggle_rdci()
    kaggle_resseg()
    (OUT / "data.yaml").write_text(
        f"path: {OUT.as_posix()}\ntrain: train/images\nval: val/images\ntest: test/images\n"
        f"names:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(NAMES)))
    for split in SPLITS:
        print(split, dict(stats[split]))


if __name__ == "__main__":
    main()
