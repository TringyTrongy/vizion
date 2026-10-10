"""Explainable anomaly detection for temperature and humidity readings.

Every reading is checked with three simple rules, and each alert says which rule fired:

1. Deviation: the value is more than K standard deviations from the average of the recent normal
   readings (the rolling baseline). Unusual readings are kept out of the baseline, so a fault
   cannot teach the detector that it is normal. A change that lasts longer than `relearn_after`
   readings becomes the new normal: the baseline starts again from the new level.
2. Sudden change: the value moved by more than a set amount within a short time.
3. Limits: the value is outside fixed limits (for the DHT11, its rated range).

A failed or impossible reading is a SENSOR ERROR, never an anomaly. An anomaly only means the
readings are unusual compared with the recent past; it does not prove that anything has failed.
"""
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

NORMAL, ANOMALY, SENSOR_ERROR = "NORMAL", "ANOMALY", "SENSOR ERROR"


@dataclass(frozen=True)
class Channel:
    key: str  # the Reading attribute, e.g. "temperature_c"
    label: str  # "Temperature"
    unit: str  # "°C"; "" when the data does not state one
    window: int  # readings in the rolling baseline
    min_baseline: int  # readings needed before the deviation rule runs
    k: float  # deviation threshold, in standard deviations
    sigma_floor: float  # smallest spread used: the sensor's resolution and noise
    rate_span_s: float = 0.0  # the sudden-change rule looks this far back (0: off)
    rate_limit: float = 0.0  # ... and fires when the value moved more than this
    low: float | None = None  # fixed limits (None: no limit)
    high: float | None = None
    valid_min: float = -math.inf  # outside these the reading is impossible: SENSOR ERROR
    valid_max: float = math.inf
    decimals: int = 1

    def fmt(self, value):
        unit = self.unit if self.unit in ("", "%") else " " + self.unit
        return f"{value:.{self.decimals}f}{unit}"


@dataclass(frozen=True)
class Profile:
    name: str
    interval_s: float  # time between readings
    channels: tuple
    relearn_after: int  # readings: a change lasting this long becomes the new normal
    confirm: int = 1  # unusual readings in a row before an ANOMALY alert opens
    error_confirm: int = 1  # failed readings in a row before a SENSOR ERROR alert opens
    clear_after: int = 1  # normal readings in a row before an alert closes

    def describe(self):
        parts = []
        for ch in self.channels:
            rules = [f"more than {ch.k:g}σ from the average of the last {span(ch.window * self.interval_s)}"]
            if ch.rate_span_s:
                rules.append(f"a change of more than {ch.fmt(ch.rate_limit)} within {span(ch.rate_span_s)}")
            if ch.low is not None or ch.high is not None:
                rules.append(f"outside {limits_text(ch)}")
            parts.append(f"{ch.label}: " + ", ".join(rules))
        return "; ".join(parts)


def span(seconds):
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f} min"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.0f} h"
    return f"{seconds / 86400:.0f} days"


def limits_text(ch):
    unit = "" if ch.unit in ("", "%") else " "
    unit += ch.unit
    if ch.low is not None and ch.high is not None:
        return f"{ch.low:g}–{ch.high:g}{unit}"
    return f"≥ {ch.low:g}{unit}" if ch.low is not None else f"≤ {ch.high:g}{unit}"


# The DHT11 is read every 2 s. Rated range 0–50 °C and 20–90 %RH; resolution 1 %RH and 0.1 °C
# (1 °C on older parts). The floors stop a perfectly steady room from turning every 1 % step
# into an anomaly.
DHT11 = Profile(
    name="dht11",
    interval_s=2.0,
    channels=(
        Channel("temperature_c", "Temperature", "°C", window=300, min_baseline=30, k=4.0,
                sigma_floor=0.25, rate_span_s=30, rate_limit=2.0, low=0, high=50,
                valid_min=-20, valid_max=80),
        Channel("humidity_percent", "Humidity", "%", window=300, min_baseline=30, k=4.0,
                sigma_floor=1.0, rate_span_s=30, rate_limit=8.0, low=20, high=90,
                valid_min=1, valid_max=100, decimals=0),
    ),
    relearn_after=300,  # 10 minutes
    confirm=2,  # 4 s: one odd reading is noted in the log but does not raise an alert
    error_confirm=3,  # one failed read is normal for a DHT11; three in a row (6 s) is a fault
    clear_after=5,  # 10 s
)

# Public NAB datasets, calibrated in evaluate.py on the series converted to °C. NAB does not state
# the unit: the office data can only be °F, and the machine data is assumed to be °F too (see
# datasets.py). The fixed amounts were chosen in °F and are converted, so the results do not change.
F = 5 / 9  # one °F step in °C
NAB_MACHINE = Profile(
    name="nab_machine",
    interval_s=300.0,
    channels=(Channel("temperature_c", "Machine temperature", "°C", window=576, min_baseline=144,
                      k=4.0, sigma_floor=1.0 * F, rate_span_s=3600, rate_limit=20.0 * F),),
    relearn_after=576,  # 48 h
    confirm=3,  # 15 min
    clear_after=12,  # 1 h
)
NAB_AMBIENT = Profile(
    name="nab_ambient",
    interval_s=3600.0,
    channels=(Channel("temperature_c", "Ambient temperature", "°C", window=336, min_baseline=84,
                      k=3.0, sigma_floor=0.5 * F),),
    relearn_after=336,  # 2 weeks
    clear_after=6,
)
PROFILES = {p.name: p for p in (DHT11, NAB_MACHINE, NAB_AMBIENT)}


@dataclass
class Assessment:
    status: str  # NORMAL, ANOMALY or SENSOR ERROR
    reasons: list = field(default_factory=list)
    channels: dict = field(default_factory=dict)  # key -> baseline details for the dashboard
    learning: bool = False  # True while a baseline is still being built

    @property
    def reason(self):
        return "; ".join(self.reasons)


class _Baseline:
    """Running mean and spread of the last `size` normal values."""

    def __init__(self, size):
        self.values = deque()
        self.size = size
        self.total = self.squares = 0.0

    def add(self, value):
        self.values.append(value)
        self.total += value
        self.squares += value * value
        if len(self.values) > self.size:
            old = self.values.popleft()
            self.total -= old
            self.squares -= old * old

    def clear(self):
        self.values.clear()
        self.total = self.squares = 0.0

    def __len__(self):
        return len(self.values)

    def stats(self):
        n = len(self.values)
        mean = self.total / n
        return mean, math.sqrt(max(self.squares / n - mean * mean, 0.0))


class _ChannelState:
    def __init__(self, ch, relearn_after):
        self.ch = ch
        self.relearn_after = relearn_after
        self.baseline = _Baseline(ch.window)
        self.recent = deque()  # (time, value) of every valid reading within the rate span
        self.unusual_run = 0

    def check(self, t, value):
        """-> (reasons, details). Does not change the state; see commit()."""
        ch = self.ch
        reasons = []
        details = {"value": value, "n": len(self.baseline), "needed": ch.min_baseline}
        if len(self.baseline) >= ch.min_baseline:
            mean, std = self.baseline.stats()
            sigma = max(std, ch.sigma_floor)
            z = (value - mean) / sigma
            details.update(mean=mean, sigma=sigma, z=z, k=ch.k,
                           band=(mean - ch.k * sigma, mean + ch.k * sigma))
            if abs(z) > ch.k:
                side = "above" if z > 0 else "below"
                reasons.append(f"{ch.label} {ch.fmt(value)} is {abs(z):.1f}σ {side} the recent average "
                               f"of {ch.fmt(mean)}")
        if ch.rate_span_s:
            old = self._value_ago(t)
            if old is not None and abs(value - old) > ch.rate_limit:
                verb = "rose" if value > old else "fell"
                reasons.append(f"{ch.label} {verb} {ch.fmt(abs(value - old))} in "
                               f"{span(ch.rate_span_s)}")
        if ch.high is not None and value > ch.high:
            reasons.append(f"{ch.label} {ch.fmt(value)} is above the {ch.fmt(ch.high)} limit")
        elif ch.low is not None and value < ch.low:
            reasons.append(f"{ch.label} {ch.fmt(value)} is below the {ch.fmt(ch.low)} limit")
        return reasons, details

    def _value_ago(self, t):
        """The oldest value within the rate span, if one is old enough to compare with."""
        while self.recent and (t - self.recent[0][0]).total_seconds() > self.ch.rate_span_s * 1.5:
            self.recent.popleft()
        if self.recent and (t - self.recent[0][0]).total_seconds() >= self.ch.rate_span_s * 0.75:
            return self.recent[0][1]
        return None

    def commit(self, t, value, unusual):
        """Record the reading. Returns a note when a lasting change became the new baseline."""
        self.recent.append((t, value))
        if not unusual:
            self.unusual_run = 0
            self.baseline.add(value)
            return None
        self.unusual_run += 1
        if self.unusual_run >= self.relearn_after:
            self.baseline.clear()
            self.baseline.add(value)
            self.unusual_run = 0
            return f"{self.ch.label} stayed at the new level, so the baseline starts again from it"
        return None


class AnomalyDetector:
    """Feed it readings in time order with update(); it returns an Assessment for each."""

    def __init__(self, profile):
        self.profile = profile
        self.states = {ch.key: _ChannelState(ch, profile.relearn_after) for ch in profile.channels}
        self.notes = []  # baseline restarts, for the alert log

    def update(self, reading):
        if reading.error:
            return Assessment(SENSOR_ERROR, [reading.error])
        values = {}
        for ch in self.profile.channels:
            value = getattr(reading, ch.key, None)
            if value is None or not math.isfinite(value):
                return Assessment(SENSOR_ERROR, [f"No {ch.label.lower()} value in the reading"])
            if not ch.valid_min <= value <= ch.valid_max:
                return Assessment(SENSOR_ERROR, [f"Impossible {ch.label.lower()} reading: {ch.fmt(value)}"])
            values[ch.key] = value
        reasons, details, learning = [], {}, False
        for key, value in values.items():
            r, d = self.states[key].check(reading.timestamp, value)
            reasons += r
            details[key] = d
            learning |= d["n"] < d["needed"]
        unusual = bool(reasons)
        for key, value in values.items():
            # A channel that is fine on its own still keeps out of the baseline while the reading
            # as a whole is unusual: a heater raises the temperature and lowers the humidity.
            note = self.states[key].commit(reading.timestamp, value, unusual)
            if note:
                self.notes.append((reading.timestamp, note))
        return Assessment(ANOMALY if unusual else NORMAL, reasons, details, learning)


@dataclass
class Alert:
    id: int
    kind: str  # ANOMALY or SENSOR ERROR
    start: datetime
    end: datetime | None = None
    reasons: list = field(default_factory=list)  # distinct reasons, first ones first
    readings: int = 0

    def as_dict(self):
        return {"id": self.id, "kind": self.kind, "start": self.start.isoformat(sep=" ", timespec="seconds"),
                "end": self.end.isoformat(sep=" ", timespec="seconds") if self.end else None,
                "reasons": self.reasons, "readings": self.readings}


class AlertLog:
    """Groups consecutive unusual readings into alerts with a start and an end."""

    MAX_REASONS = 4

    def __init__(self, profile, keep=200):
        self.profile = profile
        self.keep = keep
        self.alerts = deque(maxlen=keep)
        self.open = None
        self.next_id = 1
        self.error_run = 0
        self.anomaly_run = 0
        self.normal_run = 0

    @property
    def status(self):
        """The headline status: the kind of the open alert, else NORMAL."""
        return self.open.kind if self.open else NORMAL

    def update(self, t, assessment):
        """-> 'opened', 'closed', 'changed' or None."""
        status = assessment.status
        self.error_run = self.error_run + 1 if status == SENSOR_ERROR else 0
        self.anomaly_run = self.anomaly_run + 1 if status == ANOMALY else 0
        if status == SENSOR_ERROR and self.error_run < self.profile.error_confirm:
            return None  # one failed read: wait for the next before raising an alert
        if status == ANOMALY and self.anomaly_run < self.profile.confirm and not self.open:
            return None
        if status == NORMAL:
            if not self.open:
                return None
            self.normal_run += 1
            if self.normal_run >= self.profile.clear_after:
                self.open.end = t
                self.open = None
                return "closed"
            return None
        self.normal_run = 0
        event = None
        if self.open and self.open.kind != status:
            self.open.end = t
            self.open = None
            event = "changed"
        if not self.open:
            self.open = Alert(self.next_id, status, t)
            self.next_id += 1
            self.alerts.append(self.open)
            event = event or "opened"
        self.open.readings += 1
        for reason in assessment.reasons:
            if reason_kind(reason) not in {reason_kind(r) for r in self.open.reasons} \
                    and len(self.open.reasons) < self.MAX_REASONS:
                self.open.reasons.append(reason)
        return event


def reason_kind(reason):
    """'Temperature 31.0 °C is 4.2σ above ...' -> 'Temperature is σ above': the rule, not the numbers."""
    return " ".join(w for w in reason.split() if not any(c.isdigit() for c in w))
