"""Downloads and checks the public temperature datasets from the Numenta Anomaly Benchmark (NAB).

    python datasets.py           # download what is missing, then check every file
    python datasets.py --force   # download everything again

Files go to data/public/. A file only counts as downloaded once it parses completely and has the
expected number of rows; manifest.json records where each file came from and its SHA-256.

These are public industrial and office recordings, not readings from the Vizion DHT11. They are
for building and testing the software; the detector still has to be checked on the real sensor.
"""
import argparse
import csv
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC = HERE / "data" / "public"

# raw.githubusercontent.com first; jsDelivr mirrors the same GitHub files if GitHub is timing out.
MIRRORS = ("https://raw.githubusercontent.com/numenta/NAB/master/{path}",
           "https://cdn.jsdelivr.net/gh/numenta/NAB@master/{path}")

DATASETS = {
    "machine": {
        "path": "data/realKnownCause/machine_temperature_system_failure.csv",
        "rows": 22695,
        "interval_s": 300,
        "title": "Industrial machine temperature",
        # NAB states no unit, and 2–108 fits °F and °C alike. °F is assumed, to match the office
        # data from the same NAB collection; change "unit" here if the real unit becomes known.
        "unit": "°F",
        "unit_basis": "assumed",
        "unit_note": "Shown in °C, converted from °F. °F is assumed: NAB does not state the unit, and "
                     "the values (2–108) would fit °F or °C; °F matches the office data from the same NAB "
                     "collection.",
        # NAB's own description (data/README.md in the NAB repository):
        "about": "Temperature sensor data of an internal component of a large industrial machine. "
                 "The first anomaly is a planned shutdown. The second is difficult to detect and led "
                 "directly to the third, a catastrophic failure of the machine.",
    },
    "ambient": {
        "path": "data/realKnownCause/ambient_temperature_system_failure.csv",
        "rows": 7267,
        "interval_s": 3600,
        "title": "Office ambient temperature",
        "about": "The ambient temperature in an office setting, recorded hourly, with gaps.",
        # NAB states no unit; 57–86 can only be an office in °F (14–30 °C), so °F is inferred.
        "unit": "°F",
        "unit_basis": "inferred",
        "unit_note": "Shown in °C, converted from °F. °F is inferred: NAB does not state the unit, but "
                     "57–86 only makes sense as an office temperature in °F (14–30 °C).",
    },
}
EXTRA = {
    "combined_windows.json": "labels/combined_windows.json",  # labelled anomaly windows
    "combined_labels.json": "labels/combined_labels.json",  # labelled anomaly points
    "NAB_LICENSE.txt": "LICENSE.txt",  # MIT
}


def local(name):
    return PUBLIC / Path(DATASETS[name]["path"]).name if name in DATASETS else PUBLIC / name


def label_key(name):
    return DATASETS[name]["path"].removeprefix("data/")


def fetch(path, dest):
    errors = []
    for mirror in MIRRORS:
        url = mirror.format(path=path)
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                body = r.read()
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(body)
            tmp.replace(dest)
            return url
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            errors.append(f"{url}: {e}")
    raise RuntimeError("Download failed:\n  " + "\n  ".join(errors))


def f_to_c(value):
    return (value - 32) * 5 / 9


def load_celsius(name):
    """The series in °C, converted from the dataset's unit (°F for both; see "unit_basis")."""
    rows = load_series(name)
    if DATASETS[name]["unit"] != "°F":
        raise ValueError(f"{name}: no conversion to °C from {DATASETS[name]['unit']!r}")
    return [(t, f_to_c(v)) for t, v in rows]


def load_series(name):
    """-> [(datetime, value)] in file order. Raises ValueError if the file is not as expected."""
    path = local(name)
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != ["timestamp", "value"]:
            raise ValueError(f"{path.name}: expected the header timestamp,value, got {header}")
        rows = [(datetime.fromisoformat(t), float(v)) for t, v in reader]
    expected = DATASETS[name]["rows"]
    if len(rows) != expected:
        raise ValueError(f"{path.name}: {len(rows)} rows, expected {expected}")
    return rows


def load_windows(name):
    """Labelled anomaly windows -> [(start, end)] as datetimes."""
    windows = json.loads(local("combined_windows.json").read_text())[label_key(name)]
    return [(datetime.fromisoformat(a[:19]), datetime.fromisoformat(b[:19])) for a, b in windows]


def load_points(name):
    points = json.loads(local("combined_labels.json").read_text())[label_key(name)]
    return [datetime.fromisoformat(p[:19]) for p in points]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe(name):
    rows = load_series(name)
    values = [v for _, v in rows]
    steps = {}
    for (a, _), (b, _) in zip(rows, rows[1:]):
        s = int((b - a).total_seconds())
        steps[s] = steps.get(s, 0) + 1
    usual = DATASETS[name]["interval_s"]
    irregular = sum(n for s, n in steps.items() if s != usual)
    return (f"{len(rows)} rows, {rows[0][0]:%Y-%m-%d} to {rows[-1][0]:%Y-%m-%d}, every "
            f"{usual // 60} min, values {min(values):.1f} to {max(values):.1f}, "
            f"{irregular} irregular steps (gaps or clock changes), "
            f"{len(load_windows(name))} labelled anomaly windows")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="download every file again")
    args = ap.parse_args()
    PUBLIC.mkdir(parents=True, exist_ok=True)
    manifest_path = PUBLIC / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    wanted = {local(n).name: d["path"] for n, d in DATASETS.items()} | EXTRA
    for name, path in wanted.items():
        dest = PUBLIC / name
        if dest.exists() and not args.force:
            continue
        print(f"Downloading {name} ...")
        try:
            url = fetch(path, dest)
        except RuntimeError as e:
            print(e)
            return 1
        manifest[name] = {"url": url, "downloaded": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "bytes": dest.stat().st_size, "sha256": sha256(dest)}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    ok = True
    for name in DATASETS:
        try:
            print(f"OK  {name:8s} {describe(name)}")
        except (OSError, ValueError, KeyError) as e:
            ok = False
            print(f"BAD {name:8s} {e}  (run again with --force)")
    for name in EXTRA:
        if not (PUBLIC / name).exists():
            ok = False
            print(f"BAD {name} is missing")
    print("All files are present and complete." if ok else "Some files are missing or damaged.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
