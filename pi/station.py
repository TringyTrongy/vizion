"""Pass/fail inspection station: the verdict for what is on the table, and a live score of it.

The rule (see docs/M3_decision_rules.md):

    PASS  the camera and model are working, the counts equal the expected kit
          (--expect resistor=2,capacitor=2), and nothing unrecognised is on the table
    FAIL  a part is missing or extra, or an unrecognised object is on the table
    NO VERDICT  camera lost, model not ready or detection off (the safe state: no PASS is ever
          given without a picture)

For the pass/fail test the operator lays out a tray, presses GOOD or DEFECTIVE for what it really
is, and the station records the verdict Vizion gave at that moment. The running confusion matrix,
false-pass rate and "correct out of N" (the headline metric) are shown live and kept in a CSV.
"""
import csv
import time
from pathlib import Path

PASS, FAIL, NONE = "PASS", "FAIL", "NO VERDICT"
FIELDS = ["wall_time", "tray", "truth", "verdict", "correct", "counts", "reason"]


def parse_expect(text):
    """'resistor=2,capacitor=2' -> {'resistor': 2, 'capacitor': 2}."""
    out = {}
    for item in filter(None, (s.strip() for s in text.split(","))):
        name, _, n = item.partition("=")
        if not n.strip().isdigit():
            raise ValueError(f"expected NAME=COUNT, got {item!r}")
        out[name.strip()] = int(n)
    return out


def verdict(counts, expect, unknown_state):
    """(PASS | FAIL | NO VERDICT, reason). counts None means nothing is known about the table."""
    if counts is None:
        return NONE, "No picture or no model: safe state, no verdict"
    if unknown_state == "present":
        return FAIL, "Unrecognised object on the table"
    wrong = [f"{name} {counts.get(name, 0)}/{n}" for name, n in expect.items() if counts.get(name, 0) != n]
    extra = [f"extra {name} {k}" for name, k in counts.items() if name not in expect and name != "total" and k]
    if wrong or extra:
        return FAIL, "; ".join(wrong + extra)
    return PASS, "Kit complete"


class Station:
    """Running score of the operator-labelled trays."""

    def __init__(self, expect, path=None):
        self.expect = dict(expect)
        self.path = Path(path) if path else None
        self.rows = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size:
                with self.path.open(newline="") as f:
                    self.rows = [r for r in csv.DictReader(f) if r.get("truth")]
            else:
                with self.path.open("w", newline="") as f:
                    csv.writer(f).writerow(FIELDS)

    def label(self, truth, current_verdict, counts, reason):
        """truth: 'good' or 'bad'. Records the verdict Vizion shows right now against it."""
        if truth not in ("good", "bad"):
            raise ValueError("truth must be 'good' or 'bad'")
        if current_verdict == NONE:
            raise ValueError("No verdict right now: the camera or model is not ready")
        correct = (truth == "good") == (current_verdict == PASS)
        row = {"wall_time": time.strftime("%Y-%m-%d %H:%M:%S"), "tray": len(self.rows) + 1, "truth": truth,
               "verdict": current_verdict, "correct": "yes" if correct else "no",
               "counts": " ".join(f"{k}={v}" for k, v in sorted((counts or {}).items())), "reason": reason}
        self.rows.append(row)
        if self.path:
            with self.path.open("a", newline="") as f:
                csv.DictWriter(f, FIELDS).writerow(row)
        return row

    def reset(self):
        self.rows = []
        if self.path:
            with self.path.open("w", newline="") as f:
                csv.writer(f).writerow(FIELDS)

    def score(self):
        """Confusion matrix (truth x verdict), accuracy and false-pass rate (bad trays passed / bad trays)."""
        m = {"good_pass": 0, "good_fail": 0, "bad_pass": 0, "bad_fail": 0}
        for r in self.rows:
            m[f"{r['truth']}_{'pass' if r['verdict'] == PASS else 'fail'}"] += 1
        n = sum(m.values())
        bad = m["bad_pass"] + m["bad_fail"]
        good = m["good_pass"] + m["good_fail"]
        correct = m["good_pass"] + m["bad_fail"]
        return {"trays": n, "correct": correct, "matrix": m,
                "accuracy": round(correct / n, 3) if n else None,
                "false_pass_rate": round(m["bad_pass"] / bad, 3) if bad else None,
                "false_fail_rate": round(m["good_fail"] / good, 3) if good else None}
