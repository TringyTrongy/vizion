"""Checks the anomaly detector against labelled anomalies, or against your own recorded readings.

    python evaluate.py                 # both NAB datasets: windows found, false alerts, plots
    python evaluate.py --sweep         # try many settings on NAB (how the profiles were chosen)
    python evaluate.py --log data/log/live-2026-10-09.csv   # alerts on readings you recorded

NAB marks each known anomaly with a window around it. A window counts as found when an alert
starts inside it, or is already open when it starts. An alert that starts outside every window
counts as a false alert, although some of those may be real events that NAB did not label.
Results on public machine data say nothing certain about the DHT11; record normal readings with
the real sensor and check those with --log.
"""
import argparse
import csv
import itertools
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import datasets
from anomaly_detector import ANOMALY, PROFILES, AlertLog, AnomalyDetector
from sensor_reader import Reading

HERE = Path(__file__).resolve().parent
REPORTS = HERE / "reports"
PROFILE_FOR = {"machine": "nab_machine", "ambient": "nab_ambient"}


def run(profile, rows):
    """-> (alerts, statuses) for [(datetime, value)] rows."""
    detector, log = AnomalyDetector(profile), AlertLog(profile, keep=100000)
    statuses = []
    for t, value in rows:
        a = detector.update(Reading(t, value))
        statuses.append(a.status)
        log.update(t, a)
    if log.open:
        log.open.end = rows[-1][0]
    return list(log.alerts), statuses


def score(alerts, windows, rows, points=()):
    """A window is found when an alert starts inside it. `points` are NAB's labelled anomaly times;
    the timing is the first alert in the window relative to that point (negative: before it)."""
    found, timing = [], []
    for i, (start, end) in enumerate(windows):
        hits = [a for a in alerts if start <= a.start <= end]
        found.append(bool(hits))
        if hits and i < len(points):
            timing.append((hits[0].start - points[i]).total_seconds() / 3600)
        else:
            timing.append(None)
    false = [a for a in alerts if not any(s <= a.start <= e for s, e in windows)]
    days = (rows[-1][0] - rows[0][0]).total_seconds() / 86400
    return {"found": sum(found), "windows": len(windows), "per_window": found, "timing_h": timing,
            "false": len(false), "false_per_week": len(false) / days * 7, "alerts": len(alerts)}


def sweep(name):
    rows, windows = datasets.load_celsius(name), datasets.load_windows(name)
    points = datasets.load_points(name)
    base = PROFILES[PROFILE_FOR[name]]
    ch = base.channels[0]
    step = base.interval_s
    if name == "machine":
        grid = dict(window=[288, 576], k=[4, 5, 6], rate=[0, 10, 20], confirm=[1, 3], clear=[1, 12])
    else:
        grid = dict(window=[168, 336], k=[3, 4], rate=[0, 5, 8], confirm=[1, 2], clear=[1, 6])
    results = []
    for window, k, rate, confirm, clear in itertools.product(*grid.values()):
        c = replace(ch, window=window, min_baseline=window // 4, k=k, rate_limit=rate * 5 / 9,  # grid in °F
                    rate_span_s=ch.rate_span_s if rate else 0)
        p = replace(base, channels=(c,), relearn_after=window, confirm=confirm, clear_after=clear)
        s = score(run(p, rows)[0], windows, rows, points)
        results.append((s["found"], -s["false"], window, k, rate, confirm, clear, s))
    results.sort(key=lambda r: r[:2], reverse=True)
    print(f"\n{name}: {len(rows)} readings, {len(windows)} labelled windows. Best settings first.")
    print(f"{'window':>8} {'k':>3} {'rate':>5} {'confirm':>7} {'clear':>5}  found  false  "
          f"first alert vs labelled point (h)")
    for found, _, window, k, rate, confirm, clear, s in results[:14]:
        delays = ", ".join("—" if d is None else f"{d:+.1f}" for d in s["timing_h"])
        print(f"{window * step / 3600:>6.0f} h {k:>3} {rate or 'off':>5} {confirm:>7} {clear:>5}  "
              f"{found}/{s['windows']}  {s['false']:>5}  {delays}")


def report(name, plot=True):
    rows, windows = datasets.load_celsius(name), datasets.load_windows(name)
    points = datasets.load_points(name)
    profile = PROFILES[PROFILE_FOR[name]]
    alerts, statuses = run(profile, rows)
    s = score(alerts, windows, rows, points)
    title = datasets.DATASETS[name]["title"]
    lines = [f"### {title} (NAB `{datasets.local(name).name}`)", "",
             f"Settings: {profile.describe()}.", "",
             f"- Labelled windows found: **{s['found']} of {s['windows']}**",
             f"- False alerts (starting outside every window): **{s['false']}** "
             f"({s['false_per_week']:.1f} per week of data)",
             f"- Readings flagged: {statuses.count(ANOMALY)} of {len(rows)}", "",
             "| Window | Labelled anomaly | Window | Found | First alert in the window |",
             "|---|---|---|---|---|"]
    for i, ((a, b), p, hit, d) in enumerate(zip(windows, points, s["per_window"], s["timing_h"]), 1):
        when = "—" if d is None else f"{abs(d):.1f} h {'before' if d < 0 else 'after'} the labelled time"
        lines.append(f"| {i} | {p:%Y-%m-%d %H:%M} | {a:%m-%d %H:%M} – {b:%m-%d %H:%M} | "
                     f"{'yes' if hit else 'no'} | {when} |")
    print("\n".join(lines) + "\n")
    if plot:
        draw(name, rows, windows, alerts, statuses)
    return "\n".join(lines)


def draw(name, rows, windows, alerts, statuses):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib is not installed, so no plot)")
        return
    t = [r[0] for r in rows]
    v = [r[1] for r in rows]
    fig, ax = plt.subplots(figsize=(14, 4.2), dpi=110)
    fig.patch.set_facecolor("#020202")
    ax.set_facecolor("#020202")
    for a, b in windows:
        ax.axvspan(a, b, color="#ffffff", alpha=0.08, lw=0)
    ax.plot(t, v, lw=0.6, color="#bdbdbf")
    flagged = [(ti, vi) for ti, vi, s in zip(t, v, statuses) if s == ANOMALY]
    if flagged:
        ax.scatter(*zip(*flagged), s=6, color="#f59e0b", zorder=3, label="flagged reading")
    for a in alerts:
        ax.axvline(a.start, color="#f59e0b", lw=0.6, alpha=0.6)
    ax.set_title(f"{datasets.DATASETS[name]['title']} — shaded: NAB labelled anomaly windows, "
                 f"amber: detector alerts", color="#ffffff", loc="left", fontsize=10)
    ax.tick_params(colors="#8f8f92", labelsize=8)
    for side in ax.spines.values():
        side.set_color("#2a2a2c")
    fig.tight_layout()
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"nab_{name}.png"
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Plot: {out.relative_to(HERE)}")


def check_log(path):
    """Replays a CSV recorded by the dashboard through the current DHT11 profile."""
    profile = PROFILES["dht11"]
    detector, log = AnomalyDetector(profile), AlertLog(profile, keep=100000)
    n = errors = 0
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t = datetime.fromisoformat(row["timestamp"])
            try:
                r = Reading(t, float(row["temperature_c"]), float(row["humidity_percent"]))
            except ValueError:
                r = Reading(t, error=row.get("alert_reason") or "failed read")
                errors += 1
            n += 1
            log.update(t, detector.update(r))
    alerts = list(log.alerts)
    print(f"{path}: {n} readings, {errors} failed reads, {len(alerts)} alerts")
    for a in alerts:
        print(f"  {a.start:%Y-%m-%d %H:%M:%S}  {a.kind:12s} {a.readings:4d} readings  {'; '.join(a.reasons)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep", action="store_true", help="try a grid of settings on the NAB data")
    ap.add_argument("--log", type=Path, help="check a CSV recorded from the DHT11 instead")
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()
    if args.log:
        check_log(args.log)
        return 0
    if args.sweep:
        for name in datasets.DATASETS:
            sweep(name)
        return 0
    sections = [report(name, plot=not args.no_plot) for name in datasets.DATASETS]
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "nab_evaluation.md").write_text(
        "# Detector check on the NAB temperature datasets\n\nWritten by `python evaluate.py`.\n\n"
        "A window counts as found when an alert starts inside it; any alert that starts outside "
        "every window counts as false, although NAB may simply not have labelled some real events. "
        "The settings were chosen with `python evaluate.py --sweep` on these same files, so the "
        "numbers are optimistic, and they say nothing certain about the DHT11: its profile has to "
        "be checked on readings from the real sensor (`python evaluate.py --log <file>`).\n\n"
        "All values are in °C, converted from °F. NAB does not state the unit of either file: the "
        "office data can only be °F (57–86 °F is 14–30 °C); the machine data is assumed to be °F "
        "as well.\n\n"
        + "\n\n".join(sections) + "\n", encoding="utf-8")
    print(f"Report: {(REPORTS / 'nab_evaluation.md').relative_to(HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
