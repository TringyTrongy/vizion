"""Temporal smoothing for per-frame detections, so boxes neither jitter nor blink."""
import itertools

import numpy as np

MERGE_IOU = 0.6  # same-frame boxes this similar are one part the model was unsure how to classify
MOVED_IOU = 0.6  # below this overlap the part moved, so the box catches up faster


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


_ids = itertools.count(1)


class _Track:
    def __init__(self, box, scores):
        self.id = next(_ids)  # stable for the life of the track, so a part keeps its label
        self.box = box
        self.conf = scores.max()  # how sure we are a part is there, whatever its class
        self.class_scores = scores  # running vote on which class it is
        self.hits, self.misses, self.visible = 1, 0, False


class Tracker:
    """Matches each frame's detections to tracks by box overlap (ignoring class).

    A track keeps exponential averages of its box, its confidence (class-agnostic) and its
    per-class scores, so the box stops jittering and a part whose class flickers stays one
    box with the majority label. It is shown once its confidence reaches show_conf (and it was seen twice, unless sure_conf) and
    hidden when the confidence falls below hide_conf or after hide_misses missed detections
    in a row. Misses decay the confidence, so a part survives a few dropped frames instead
    of blinking, but a removed part vanishes within ~0.4 s.
    """

    def __init__(self, n_classes, show_conf=0.4, hide_conf=0.25, sure_conf=0.6, match_iou=0.3,
                 box_alpha=0.5, score_alpha=0.4, miss_decay=0.85, hide_misses=5, max_misses=8):
        self.n = n_classes
        self.show, self.hide, self.sure, self.match_iou = show_conf, hide_conf, sure_conf, match_iou
        self.box_alpha, self.score_alpha, self.decay = box_alpha, score_alpha, miss_decay
        self.hide_misses, self.max_misses = hide_misses, max_misses
        self.tracks = []

    def reset(self):
        self.tracks = []

    def _candidates(self, dets):
        """One (box, per-class scores) per part; merges overlapping boxes of different classes."""
        cands = []
        for c, conf, *box in sorted(dets, key=lambda d: -d[1]):
            box = np.asarray(box, float)
            for cb, cs in cands:
                if iou(cb, box) > MERGE_IOU:
                    cs[c] = max(cs[c], conf)
                    break
            else:
                scores = np.zeros(self.n)
                scores[c] = conf
                cands.append((box, scores))
        return cands

    def update(self, dets):
        """dets: [(class_id, confidence, x1, y1, x2, y2), ...] from one frame."""
        cands = self._candidates(dets)
        pairs = sorted(((iou(t.box, cb), ti, ci) for ti, t in enumerate(self.tracks)
                        for ci, (cb, _) in enumerate(cands)), reverse=True)
        used_t, used_c = set(), set()
        for overlap, ti, ci in pairs:
            if overlap < self.match_iou:
                break
            if ti in used_t or ci in used_c:
                continue
            used_t.add(ti)
            used_c.add(ci)
            t, (cb, cs) = self.tracks[ti], cands[ci]
            a = self.box_alpha if overlap >= MOVED_IOU else max(self.box_alpha, 0.8)
            sa = self.score_alpha
            t.box = (1 - a) * t.box + a * cb
            t.conf = (1 - sa) * t.conf + sa * cs.max()
            t.class_scores = (1 - sa) * t.class_scores + sa * cs
            t.hits, t.misses = t.hits + 1, 0
        for ti, t in enumerate(self.tracks):
            if ti not in used_t:
                t.conf *= self.decay
                t.misses += 1
        self.tracks += [_Track(cb, cs) for ci, (cb, cs) in enumerate(cands) if ci not in used_c]

        for t in self.tracks:
            if not t.visible and t.conf >= self.show and (t.hits >= 2 or t.conf >= self.sure):
                t.visible = True
            elif t.visible and (t.conf < self.hide or t.misses >= self.hide_misses):
                t.visible = False
        self.tracks = [t for t in self.tracks if t.misses <= self.max_misses and t.conf >= 0.05]

    def visible(self):
        """[(class_id, smoothed confidence, x1, y1, x2, y2), ...] for the parts to draw."""
        return [row[1:] for row in self.visible_tracks()]

    def visible_tracks(self):
        """Like visible(), with each part's track id first: [(id, class_id, conf, x1, y1, x2, y2), ...]."""
        return [(t.id, int(t.class_scores.argmax()), float(t.conf), *(int(round(v)) for v in t.box))
                for t in self.tracks if t.visible]
