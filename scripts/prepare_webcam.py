"""Add the Pi webcam's own images to data/vizion (run after prepare_dataset.py).

    python -I scripts/prepare_webcam.py

The first model learned from phone photos and missed parts on the 610x480 webcam (small,
soft, noisy, blue-tinted frames; capacitors lying on their side). This adds:
  1. the hand-labelled webcam frames (data/webcam/labels.json), oversampled; scenes listed in
     "test_scenes" go to data/webcam/test/ instead, for an honest real-camera check;
  2. synthetic webcam scenes: the labelled parts (and parts from the public data) cut out with
     GrabCut and pasted at random angles/sizes onto the empty webcam table;
  3. a webcam look for half of the public training images (blur, noise, colour cast, JPEG).
"""
import json
import random
import shutil
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WEBCAM, OUT = ROOT / "data" / "webcam", ROOT / "data" / "vizion"
MARKER = OUT / ".webcam_added"
SEED = 0
N_SYNTH = 600
REAL_REPEATS = 6  # copies of each single-frame training scene; scene s4 already has 12 frames
PUBLIC_STYLED = 0.5  # fraction of public training images given the webcam look
PUBLIC_PARTS = 400  # parts cut from the public data for the synthetic scenes
# Long side in webcam pixels, from the labelled frames (resistors 33-56, capacitors 46-90).
SIZE_RANGE = {0: (24, 70), 1: (36, 110)}


def webcam_style(img, rng):
    """Make a sharp photo look like the 610x480 USB webcam: soft, noisy, colour-cast, JPEG."""
    h, w = img.shape[:2]
    s = 640 / max(h, w)
    if s < 1:
        img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    f = rng.uniform(0.45, 0.8)
    small = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    img = cv2.resize(small, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    img *= rng.uniform(0.85, 1.15, size=3)
    img = (img - 128) * rng.uniform(0.8, 1.2) + 128 + rng.uniform(-25, 25)
    img += rng.normal(0, rng.uniform(2, 7), img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(rng.uniform(45, 85))])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)


def to_yolo_lines(boxes, w, h):
    return "".join(f"{c} {(x0 + x1) / 2 / w:.6f} {(y0 + y1) / 2 / h:.6f} {(x1 - x0) / w:.6f} {(y1 - y0) / h:.6f}\n"
                   for c, x0, y0, x1, y1 in boxes)


def write(folder, name, img, boxes):
    (folder / "images").mkdir(parents=True, exist_ok=True)
    (folder / "labels").mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(folder / "images" / f"{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    (folder / "labels" / f"{name}.txt").write_text(to_yolo_lines(boxes, img.shape[1], img.shape[0]))


def cut_out(img, box, pad=6, strict=False):
    """RGBA patch of the part inside box, background removed with GrabCut.

    If GrabCut fails (keeps almost nothing, or almost the whole rectangle), strict returns
    None; otherwise the plain box is used."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    H, W = img.shape[:2]
    cx0, cy0, cx1, cy1 = max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad, W), min(y1 + pad, H)
    crop = img[cy0:cy1, cx0:cx1]
    mask = np.zeros(crop.shape[:2], np.uint8)
    rect = (x0 - cx0, y0 - cy0, max(x1 - x0, 2), max(y1 - y0, 2))
    try:
        cv2.grabCut(crop, mask, rect, np.zeros((1, 65)), np.zeros((1, 65)), 4, cv2.GC_INIT_WITH_RECT)
        alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    except cv2.error:
        alpha = np.zeros(crop.shape[:2], np.uint8)
    fg = (alpha > 0).sum() / (rect[2] * rect[3])
    if fg < 0.25 or fg > 0.9:  # GrabCut gave up, or kept the background too
        if strict:
            return None
        alpha[:] = 0
        alpha[rect[1]:rect[1] + rect[3], rect[0]:rect[0] + rect[2]] = 255
    return np.dstack([crop, alpha])


def paste(bg, patch, cls, rng, placed):
    """Rotate/scale patch, paste it somewhere free on bg. Returns the box or None."""
    long_side = rng.uniform(*SIZE_RANGE[cls])
    s = long_side / max(patch.shape[:2])
    p = cv2.resize(patch, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    if rng.random() < 0.5:
        p = p[:, ::-1]
    angle = rng.uniform(0, 360)
    h, w = p.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    p = cv2.warpAffine(np.ascontiguousarray(p), m, (nw, nh), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    a = cv2.GaussianBlur(p[..., 3], (3, 3), 0).astype(np.float32)[..., None] / 255
    ys, xs = np.nonzero(p[..., 3] > 127)
    if len(xs) < 20:
        return None
    H, W = bg.shape[:2]
    for _ in range(20):
        x, y = int(rng.uniform(0, W - nw)), int(rng.uniform(0, H - nh))
        box = (x + xs.min(), y + ys.min(), x + xs.max() + 1, y + ys.max() + 1)
        if all(_iou(box, b) < 0.05 for b in placed):
            roi = bg[y:y + nh, x:x + nw].astype(np.float32)
            bg[y:y + nh, x:x + nw] = (a * p[..., :3] + (1 - a) * roi).astype(np.uint8)
            return box
    return None


def _iou(a, b):
    ix, iy = max(0, min(a[2], b[2]) - max(a[0], b[0])), max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / union if union else 0


def public_parts(rng):
    """Cut resistors/capacitors out of the public training images (webcam-styled first)."""
    labels = [p for p in sorted((OUT / "train" / "labels").glob("*.txt")) if p.stat().st_size]
    rng.shuffle(labels)
    parts = []
    for lbl in labels:
        if len(parts) >= PUBLIC_PARTS:
            break
        img = webcam_style(cv2.imread(str(next((OUT / "train" / "images").glob(f"{lbl.stem}.*")))), rng)
        H, W = img.shape[:2]
        for line in lbl.read_text().splitlines():
            c, x, y, w, h = line.split()
            c, (x, y, w, h) = int(c), (float(x) * W, float(y) * H, float(w) * W, float(h) * H)
            if min(w, h) >= 16 and len(parts) < PUBLIC_PARTS:
                patch = cut_out(img, (x - w / 2, y - h / 2, x + w / 2, y + h / 2), strict=True)
                if patch is not None:
                    parts.append((c, patch))
    return parts


def main():
    if not OUT.exists() or MARKER.exists():
        raise SystemExit("Run scripts/prepare_dataset.py first (this script must run once on a fresh build).")
    rng = np.random.default_rng(SEED)
    doc = json.loads((WEBCAM / "labels.json").read_text())
    test_scenes = set(doc["test_scenes"])

    # 1. Real webcam frames.
    test_dir = WEBCAM / "test"
    shutil.rmtree(test_dir, ignore_errors=True)
    scenes, n_real = {}, 0
    for name, entry in doc["images"].items():
        img = cv2.imread(str(WEBCAM / "raw" / name))
        boxes = [tuple(b) for b in entry["boxes"]]
        if entry["scene"] in test_scenes:
            write(test_dir, Path(name).stem, img, boxes)
            continue
        scenes.setdefault(entry["scene"], []).append((name, img, boxes))
    for scene, frames in scenes.items():
        repeats = REAL_REPEATS if len(frames) == 1 else 1
        for name, img, boxes in frames:
            for r in range(repeats):
                write(OUT / "train", f"webcam_{Path(name).stem}_{r}", img, boxes)
                n_real += 1
    (test_dir / "test.yaml").write_text(f"path: {test_dir.as_posix()}\ntrain: images\nval: images\n"
                                        "names:\n  0: resistor\n  1: capacitor\n")

    # 2. Synthetic scenes: empty-table backgrounds + cut-out parts.
    backgrounds, webcam_parts = [], []
    for frames in scenes.values():
        name, img, boxes = frames[0]
        mask = np.zeros(img.shape[:2], np.uint8)
        for c, x0, y0, x1, y1 in boxes:
            cv2.rectangle(mask, (x0 - 4, y0 - 4), (x1 + 4, y1 + 4), 255, -1)
            webcam_parts.append((c, cut_out(img, (x0, y0, x1, y1))))
        backgrounds.append(cv2.inpaint(img, mask, 7, cv2.INPAINT_TELEA))
    other_parts = public_parts(np.random.default_rng(SEED + 1))
    for i in range(N_SYNTH):
        bg = backgrounds[int(rng.integers(len(backgrounds)))].copy()
        if rng.random() < 0.5:
            bg = bg[:, ::-1].copy()
        bg = np.clip(bg.astype(np.float32) * rng.uniform(0.7, 1.3), 0, 255).astype(np.uint8)  # auto-exposure swing
        placed, boxes = [], []
        for _ in range(int(rng.integers(1, 7))):
            pool = webcam_parts if rng.random() < 0.6 else other_parts
            c, patch = pool[int(rng.integers(len(pool)))]
            box = paste(bg, patch, c, rng, placed)
            if box:
                placed.append(box)
                boxes.append((c, *box))
        img = cv2.GaussianBlur(bg, (3, 3), rng.uniform(0.3, 0.9))
        img = np.clip(img + rng.normal(0, rng.uniform(1, 4), img.shape), 0, 255).astype(np.uint8)
        write(OUT / "train", f"synth_{i:04d}", img, boxes)

    # 3. Webcam look for half of the public training images (in place; labels are normalised).
    public = [p for p in sorted((OUT / "train" / "images").iterdir())
              if not p.name.startswith(("webcam_", "synth_"))]
    styled = 0
    for p in public:
        if rng.random() < PUBLIC_STYLED:
            img = webcam_style(cv2.imread(str(p)), rng)
            p.unlink()
            cv2.imwrite(str(p.with_suffix(".jpg")), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            styled += 1
    for cache in OUT.glob("*/labels.cache"):
        cache.unlink()
    MARKER.write_text("")
    print(f"real webcam frames: {n_real} train (+{len(list((test_dir / 'images').glob('*')))} test) | "
          f"synthetic: {N_SYNTH} ({len(webcam_parts)} webcam parts, {len(other_parts)} public parts) | "
          f"public images webcam-styled: {styled}/{len(public)}")


if __name__ == "__main__":
    main()
