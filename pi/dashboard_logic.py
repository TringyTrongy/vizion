"""What the dashboard says about the tracked parts: their zone, their designator, and whether
anything else is on the table.

No camera, model or web server in here, so it is tested on any machine (test_dashboard_logic.py).
"""
import itertools
import time
from pathlib import Path

import cv2
import numpy as np

ROWS, COLS = "ABC", "123"  # sheet zones, as on a drawing: letters top to bottom, numbers left to right
ROW_NAMES, COL_NAMES = ("Top", "Center", "Bottom"), ("Left", "Center", "Right")
PREFIXES = {"resistor": "R", "capacitor": "C"}
L_OFFSET = 16 * 255 / 100  # the "-16" of CIE L*, in OpenCV's 0-255 lightness scale


def zone(box, width, height):
    """Zone of a box's centre in a 3x3 grid over the frame: ("B3", "Center-Right")."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    col = min(2, max(0, int(3 * cx / width)))
    row = min(2, max(0, int(3 * cy / height)))
    name = "Center" if row == col == 1 else f"{ROW_NAMES[row]}-{COL_NAMES[col]}"
    return f"{ROWS[row]}{COLS[col]}", name


class Designators:
    """Reference designators, as on a schematic: R1, R2, C1.

    A part keeps its designator while it is tracked. When it leaves, its number is free again and
    the next new part of that class takes the lowest free number, so the labels stay short.
    """

    def __init__(self, names):
        self.prefix = {c: PREFIXES.get(n, "X") for c, n in names.items()}
        self.assigned = {}  # track id -> (class id, number)

    def reset(self):
        self.assigned = {}

    def update(self, tracks):
        """tracks: [(track id, class id, ...)]. Returns {track id: "R1", ...}."""
        live = {t[0]: t[1] for t in tracks}
        # A part whose majority class flipped gets a designator of its new class.
        self.assigned = {tid: cn for tid, cn in self.assigned.items() if live.get(tid) == cn[0]}
        taken = {}
        for c, n in self.assigned.values():
            taken.setdefault(c, set()).add(n)
        for tid in sorted(live):  # older tracks first, so they get the lower numbers
            if tid not in self.assigned:
                c = live[tid]
                used = taken.setdefault(c, set())
                n = next(i for i in itertools.count(1) if i not in used)
                used.add(n)
                self.assigned[tid] = (c, n)
        return {tid: f"{self.prefix.get(c, 'X')}{n}" for tid, (c, n) in self.assigned.items()}


def describe_parts(tracks, names, refs, width, height):
    """One dict per visible part, ordered R1, R2 ... C1, C2 ... for the dashboard."""
    parts = []
    for tid, c, conf, x1, y1, x2, y2 in tracks:
        code, where = zone((x1, y1, x2, y2), width, height)
        parts.append({"ref": refs[tid], "cls": names[c], "conf": round(conf, 3),
                      "box": [x1, y1, x2, y2], "zone": code, "where": where})
    order = {n: i for i, n in enumerate(PREFIXES)}
    parts.sort(key=lambda p: (order.get(p["cls"], 99), int(p["ref"][1:])))
    return parts


def count_parts(parts, names):
    counts = {n: 0 for n in names.values()}
    for p in parts:
        counts[p["cls"]] += 1
    counts["total"] = len(parts)
    return counts


class EmptyTable:
    """Notices things on the table that are neither a detected resistor nor a detected capacitor.

    The operator teaches it a picture of the empty table. Each check compares the frame with that
    picture, after matching brightness and colour cast (the webcam's auto-exposure and white balance
    can't be locked). Whatever still differs, outside the detected parts (widened to cover their
    leads), is an unrecognised object if it is big enough. The object is never named: the model only
    knows resistors and capacitors. If most of the view differs, the camera or lighting changed and
    the picture must be learned again.

    States: not_learned, none, present, relearn.
    """

    SCALE = 4  # compare at 1/4 size: fast, and sensor noise averages out
    L_DIFF, C_DIFF = 24.0, 16.0  # lightness / colour difference (OpenCV 8-bit Lab units) that counts
    MIN_AREA = 30  # pixels at 1/4 size (about 22x22 at full size); smaller is noise, a lead or a shadow edge
    RELEARN_FRACTION = 0.35  # more of the view than this differs: the camera moved or the light changed
    LEAD_MARGIN = 0.5  # widen each part's body box by this share of its long side to cover leads and legs
    CONFIRM = 3  # identical results in a row before the state changes, so it doesn't flicker
    SATURATED = 248  # Lab lightness at which the webcam has clipped to white
    TEXTURE_SPREAD = 30  # lightness spread (10th to 90th percentile) above which an offset can be fitted

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.ref = self.ref_shape = self.learned_at = None
        self.state, self.boxes = "not_learned", []
        self._pending, self._streak, self.gain = None, 0, 1.0
        if self.path and self.path.exists():
            frame = cv2.imread(str(self.path))
            if frame is not None:
                self._set_reference(frame, self.path.stat().st_mtime)

    def _prep(self, frame):
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (w // self.SCALE, h // self.SCALE), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (3, 3), 0)
        return cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)

    def _set_reference(self, frame, when):
        self.ref, self.ref_shape, self.learned_at = self._prep(frame), frame.shape[:2], when
        self.state, self.boxes, self._pending, self._streak = "none", [], None, 0

    def learn(self, frame):
        self._set_reference(frame, time.time())
        if self.path:
            cv2.imwrite(str(self.path), frame)

    def forget(self):
        self.ref = self.ref_shape = self.learned_at = None
        self.state, self.boxes, self._pending, self._streak = "not_learned", [], None, 0
        if self.path and self.path.exists():
            self.path.unlink()

    def _match_exposure(self, L, Lr):
        """Maps the frame's lightness onto the reference's with one gain and one offset.

        An exposure change multiplies the light, which scales Lab lightness (+16) by about its cube
        root, so the gain comes first, as the median ratio over the view. On a textured table an
        offset is fitted too, by least squares that drop the worst-matching pixels (objects) each
        round. Only two numbers are fitted, so an object can never be fitted away, as it would be
        by a free-form tone curve; on a plain table the offset is left out, since it can't be told
        apart from a gain there.
        """
        ok = (L < self.SATURATED) & (Lr < self.SATURATED)
        if ok.sum() < 100:
            self.gain = 1.0
            return L
        x, y = L[ok] + L_OFFSET, Lr[ok] + L_OFFSET
        gain = self.gain = float(np.median(y / x))
        offset = 0.0
        if np.subtract(*np.percentile(x, (90, 10))) >= self.TEXTURE_SPREAD:
            for _ in range(3):
                res = np.abs(y - (gain * x + offset))
                keep = res <= max(3.0 * float(np.median(res)), 4.0)
                gain, offset = np.polyfit(x[keep], y[keep], 1)
            gain = float(np.clip(gain, 0.5, 2.0))
        return (L + L_OFFSET) * gain + offset - L_OFFSET

    def difference_mask(self, frame):
        """Pixels (at 1/4 size) that differ from the empty table after matching exposure and colour."""
        cur, ref = self._prep(frame), self.ref
        Lr, L = ref[..., 0], cur[..., 0]
        L = self._match_exposure(L, Lr)
        da = cur[..., 1] - ref[..., 1] - float(np.median(cur[..., 1] - ref[..., 1]))
        db = cur[..., 2] - ref[..., 2] - float(np.median(cur[..., 2] - ref[..., 2]))
        score = np.maximum(np.abs(L - Lr) / self.L_DIFF, np.hypot(da, db) / self.C_DIFF)
        # Where the frame is blown out to white, its texture is gone and nothing can be compared.
        mask = ((score > 1.0) & (cur[..., 0] < self.SATURATED)).astype(np.uint8)
        # Opening removes thin things (leads, noise); closing joins the pieces of one object.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    def check(self, frame, part_boxes):
        """Updates state and boxes from one frame and the boxes of the detected parts (full size)."""
        if self.ref is None:
            self.state, self.boxes = "not_learned", []
            return self.state
        if frame.shape[:2] != self.ref_shape:
            raw, boxes = "relearn", []
        else:
            mask = self.difference_mask(frame)
            # Far more or less light than the camera can make up for (lights off, lens covered).
            if mask.mean() > self.RELEARN_FRACTION or not 0.5 <= self.gain <= 2.0:
                raw, boxes = "relearn", []
            else:
                s = self.SCALE
                for x1, y1, x2, y2 in part_boxes:
                    m = self.LEAD_MARGIN * max(x2 - x1, y2 - y1)
                    mask[max(0, int((y1 - m) / s)):int((y2 + m) / s) + 1,
                         max(0, int((x1 - m) / s)):int((x2 + m) / s) + 1] = 0
                n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
                boxes = [[int(x * s), int(y * s), int((x + w) * s), int((y + h) * s)]
                         for x, y, w, h, area in stats[1:] if area >= self.MIN_AREA]
                raw = "present" if boxes else "none"
        self._streak = self._streak + 1 if raw == self._pending else 1
        self._pending = raw
        if raw != self.state and self._streak >= self.CONFIRM:
            self.state = raw
        # While "present" is confirmed, keep the last outlines through a frame or two without any.
        self.boxes = (boxes or self.boxes) if self.state == "present" else []
        return self.state
