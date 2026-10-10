"""The readings log, and CSV export.

The dashboard appends every live DHT11 reading, normal or not, to data/log/live-YYYY-MM-DD.csv,
and the fan's state every second to data/log/motor-YYYY-MM-DD.csv. Export a range from the terminal:

    python export_csv.py                                   # everything recorded, to data/exports/
    python export_csv.py --from 2026-10-09 --to 2026-10-10 -o my_readings.csv
    python export_csv.py --source motor                    # the fan's log instead

DHT11 columns: timestamp, temperature_c, humidity_percent, anomaly_status, alert_reason, source.
The `source` column tells real readings (dht11) from simulated ones and public dataset replays.
Fan columns: timestamp, humidity_percent, fan, state, mode, on_at, off_at, servo_pulse_us, event.
"""
import argparse
import csv
import io
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "data" / "log"
EXPORTS = HERE / "data" / "exports"
COLUMNS = ["timestamp", "temperature_c", "humidity_percent", "anomaly_status", "alert_reason", "source"]
# Public dataset replays are converted to °C; their exports also keep the dataset's own value and unit.
REPLAY_COLUMNS = ["timestamp", "temperature_c", "dataset_value", "dataset_unit", "anomaly_status",
                  "alert_reason", "source"]
# The fan, once a second: what it was doing, why, and the servo pulse it was given.
MOTOR_COLUMNS = ["timestamp", "humidity_percent", "fan", "state", "mode", "on_at", "off_at",
                 "servo_pulse_us", "event"]
LOG_COLUMNS = {"motor": MOTOR_COLUMNS}


def make_row(reading, assessment, source):
    def num(v):
        return "" if v is None else f"{v:.1f}"

    return {"timestamp": reading.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "temperature_c": num(reading.temperature_c),
            "humidity_percent": num(reading.humidity_percent),
            "anomaly_status": assessment.status,
            "alert_reason": assessment.reason,
            "source": source}


class Recorder:
    """Appends rows to one CSV per day: <folder>/<name>-YYYY-MM-DD.csv."""

    def __init__(self, name, folder=LOG, columns=COLUMNS):
        self.name = name
        self.folder = folder
        self.columns = columns
        self.file = None
        self.day = None
        self.writer = None

    def write(self, row):
        day = row["timestamp"][:10]
        if day != self.day:
            self.close()
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.folder / f"{self.name}-{day}.csv"
            new = not path.exists() or path.stat().st_size == 0
            self.file = open(path, "a", newline="", encoding="utf-8")
            self.writer = csv.DictWriter(self.file, self.columns)
            if new:
                self.writer.writeheader()
            self.day = day
        self.writer.writerow(row)
        self.file.flush()

    def close(self):
        if self.file:
            self.file.close()
        self.file = self.writer = self.day = None


def read_log(name, start=None, end=None, folder=LOG):
    """Rows from the daily logs between start and end (datetimes, either may be None)."""
    for path in sorted(folder.glob(f"{name}-????-??-??.csv")):
        day = date.fromisoformat(path.stem[-10:])
        if start and day < start.date() or end and day > end.date():
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = datetime.fromisoformat(row["timestamp"])
                if (start is None or t >= start) and (end is None or t < end):
                    yield row


def to_csv(rows, columns=COLUMNS):
    out = io.StringIO()
    writer = csv.DictWriter(out, columns, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    count = 0
    for row in rows:
        writer.writerow(row)
        count += 1
    return out.getvalue(), count


def save_export(text, name):
    EXPORTS.mkdir(parents=True, exist_ok=True)
    path = EXPORTS / f"vizion-{name}-{datetime.now():%Y%m%d-%H%M%S}.csv"
    path.write_text(text, encoding="utf-8", newline="")
    return path


def day_arg(text):
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a date like 2026-10-09 or 2026-10-09 14:00 (got {text!r})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="live", help="which log: live (default), motor or simulated")
    ap.add_argument("--from", dest="start", type=day_arg, help="first day or time to include")
    ap.add_argument("--to", dest="end", type=day_arg,
                    help="end (not included); a bare date means up to the start of that day")
    ap.add_argument("-o", "--output", type=Path, help="file to write (default: data/exports/...)")
    args = ap.parse_args()
    text, count = to_csv(read_log(args.source, args.start, args.end), LOG_COLUMNS.get(args.source, COLUMNS))
    if count == 0:
        print(f"No {args.source} readings in that range (looked in {LOG}).")
        return 1
    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="")
        path = args.output
    else:
        path = save_export(text, args.source)
    print(f"Wrote {count} readings to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
