"""Vizion Motor's detector: does the servo arm look the way it normally does right now?

The SG90 has no feedback wire, so the Pi cannot ask it where it is. The webcam closes the loop.

Learn normal:
1. The arm holds still in the middle for 2 s, then sweeps for 30 s.
2. The camera records it the whole time. The pictures from the sweep are the master images, each
   tagged with the position the arm was told to be at and the way it was moving.
3. The parts of the picture that moved while it swept, and not while it held still, are the arm's
   region. Only that region is compared from then on.
4. How much normal sweeps differ from each other sets the limit.

Inspecting:
- Each new camera frame is compared with the master images taken at the same commanded position,
  moving the same way. The smallest difference is the mismatch.
- A mismatch over the limit for 3 frames in a row (about a third of a second) is an anomaly. The
  motor stops being driven and stays stopped until Restart.
- While the motor is stopped, the frame is compared with the still master images instead, so a push
  on the arm is caught too.

An anomaly means the arm did not look the way it normally does at that moment. Something holding or
blocking it, a servo with no power, or a hand in front of the camera all cause one. It is never proof
that the motor is broken.

Pure numpy: no camera or GPIO here. motor_dashboard.py feeds it frames and drives the servo; the tests
feed it drawn frames on a made-up clock.
"""
import math
from collections import deque
from datetime import datetime

import numpy as np

MIDDLE_US = 1500
SWEEP_US = 450  # the sweep swings ±450 µs around the middle, about ±40°
DEG_PER_US = 0.09  # SG90: about 180° across 500–2500 µs
PERIOD_S = 3.0  # one sweep, there and back
SETTLE_S = 2.0  # Learn normal first holds the arm still in the middle...
STILL_FROM_S = 0.7  # ...and keeps the still frames from this point on, once the arm has arrived
LEARN_S = 30.0  # ...then watches it sweep for this long
PARK_S = 0.8  # after Stop, hold the middle this long, then stop the pulses (no hum, no jitter)
GRACE_S = 1.2  # no anomaly this soon after the arm starts moving or parks (it is catching up)
CONFIRM = 3  # frames in a row over the limit before it counts: about 0.35 s at 8.5 frames a second
NEAR_US = 80  # master images taken within this many µs of the command are the ones compared
SAME_PASS_S = 0.6  # when judging normal, a frame is never compared with its own neighbours
LIMIT_FLOOR = 0.15
LIMIT_FACTOR = 4.0  # the limit is this many times the 99th percentile of normal, but never under the floor
UNSTEADY = 0.30  # learning fails when normal sweeps differ from each other this much
MIN_SWEEP_FRAMES = 60
MIN_STILL_FRAMES = 3
MIN_MOTION_PX = 60  # the arm's region must have at least this many moving pixels
MAX_REGION = 0.6  # ...and must not be most of the picture (that means a hand or the camera moved)
CAMERA_TIMEOUT_S = 2.0
STUCK_DEG = 5  # for the reason sentence: the arm barely moved while it was told to move...
TOLD_DEG = 15  # ...this much
TRACE = 1200  # inspected frames kept for the page: over 2 minutes at 8.5 a second
SIZE = (240, 305)  # frames are inspected grey at half the camera's 480×610 (after its padded edge)

NOT_LEARNED, LEARNING, WATCHING, STOPPED, ANOMALY, NO_CAMERA = (
    "NOT LEARNED", "LEARNING", "WATCHING", "STOPPED", "ANOMALY", "NO CAMERA")
STATE_CODE = {NOT_LEARNED: "N", LEARNING: "L", WATCHING: "W", STOPPED: "S", ANOMALY: "A", NO_CAMERA: "C"}


def sweep_us(t):
    """The pulse width the arm is told to be at, t seconds into the sweep."""
    return MIDDLE_US + SWEEP_US * math.sin(2 * math.pi * t / PERIOD_S)


def sweep_direction(t):
    """+1 turning one way, -1 the other, 0 near the ends where it turns round."""
    c = math.cos(2 * math.pi * t / PERIOD_S)
    return 0 if abs(c) < 0.15 else (1 if c > 0 else -1)


def degrees(us):
    return None if us is None else round((us - MIDDLE_US) * DEG_PER_US, 1)


def grey_small(frame):
    """A camera frame (BGR or grey, 480×610) as the half-size grey picture the detector compares."""
    a = np.asarray(frame, dtype=np.float32)
    if a.ndim == 3:
        a = a[..., 0] * 0.114 + a[..., 1] * 0.587 + a[..., 2] * 0.299
    h, w = a.shape
    a = a[: h // 2 * 2, : w // 2 * 2]
    return a.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))


class LearnFailed(Exception):
    pass


class Master:
    """What normal looks like: the arm's region and its pictures at many commanded positions."""

    def __init__(self, box, step, vectors, us, dirs, still, limit, normal_p50, normal_p99, learned_at,
                 keeps=None, still_keeps=None):
        self.box = tuple(int(v) for v in box)  # x0, y0, x1, y1 in the half-size picture
        self.step = int(step)
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.us = np.asarray(us, dtype=np.float32)
        self.dirs = np.asarray(dirs, dtype=np.int8)
        self.still = np.asarray(still, dtype=np.float32)
        self.limit = float(limit)
        self.normal_p50 = float(normal_p50)
        self.normal_p99 = float(normal_p99)
        self.learned_at = learned_at
        self.keeps = list(keeps) if keeps is not None else [None] * len(self.us)
        self.still_keeps = list(still_keeps) if still_keeps is not None else [None] * len(self.still)

    def vector(self, small):
        x0, y0, x1, y1 = self.box
        r = small[y0:y1, x0:x1]
        if self.step == 2:
            h, w = r.shape[0] // 2 * 2, r.shape[1] // 2 * 2
            r = r[:h, :w].reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
        v = r.ravel()
        return ((v - v.mean()) / (v.std() + 1e-6)).astype(np.float32)

    def inspect(self, v, us, direction):
        """(mismatch, index of the closest master image at this command, where the arm seems to be in µs).

        "Where it seems to be" is the command of the best-matching master image moving the same way,
        and None when nothing matches well (a hand, a covered camera).
        """
        d = ((self.vectors - v) ** 2).mean(axis=1)
        same = self.dirs == direction if direction else np.ones(len(d), bool)
        if not same.any():
            same = np.ones(len(d), bool)
        near = same & (np.abs(self.us - us) < NEAR_US)
        if not near.any():
            near = same & (np.abs(self.us - us) < 2 * NEAR_US)
        if not near.any():
            near = np.abs(self.us - us) < 2 * NEAR_US
        if not near.any():
            near = np.ones(len(d), bool)
        i = int(np.flatnonzero(near)[d[near].argmin()])
        j = int(np.flatnonzero(same)[d[same].argmin()])
        seen = float(self.us[j]) if d[j] < self.limit else None
        return float(d[i]), i, seen

    def inspect_still(self, v):
        d = ((self.still - v) ** 2).mean(axis=1)
        i = int(d.argmin())
        return float(d[i]), i

    def to_arrays(self):
        return {"box": np.array(self.box), "step": np.array(self.step), "vectors": self.vectors, "us": self.us,
                "dirs": self.dirs, "still": self.still,
                "stats": np.array([self.limit, self.normal_p50, self.normal_p99]),
                "learned_at": np.array(self.learned_at),
                "keeps": np.array(self.keeps, dtype=object), "still_keeps": np.array(self.still_keeps, dtype=object)}

    @classmethod
    def from_arrays(cls, a):
        limit, p50, p99 = (float(x) for x in a["stats"])
        return cls(a["box"], int(a["step"]), a["vectors"], a["us"], a["dirs"], a["still"], limit, p50, p99,
                   str(a["learned_at"]), list(a["keeps"]), list(a["still_keeps"]))


def learn(still, sweep, wall=None):
    """Build the master from the still frames and the sweep frames.

    still: [(small, keep)], sweep: [(small, keep, t, us, direction)]. Raises LearnFailed with a
    sentence saying what to do.
    """
    if len(sweep) < MIN_SWEEP_FRAMES or len(still) < MIN_STILL_FRAMES:
        raise LearnFailed(f"The camera sent only {len(sweep) + len(still)} pictures while learning. "
                          "It may be too dark: add light and learn again.")
    S = np.stack([s for s, _ in still])
    W = np.stack([f[0] for f in sweep])
    moving = np.abs(np.diff(W, axis=0)).mean(axis=0) - np.abs(np.diff(S, axis=0)).mean(axis=0)
    moving = np.clip(moving, 0, None)
    strong = moving > max(6.0, float(np.percentile(moving, 98)))
    ys, xs = np.nonzero(strong)
    if len(xs) < MIN_MOTION_PX:
        raise LearnFailed("The camera didn't see the arm move. Point it at the servo, check the servo "
                          "is plugged in, and learn again.")
    h, w = S.shape[1:]
    x0, x1 = np.percentile(xs, [5, 95])
    y0, y1 = np.percentile(ys, [5, 95])
    x0, y0, x1, y1 = int(x0) - 8, int(y0) - 8, int(x1) + 9, int(y1) + 9
    if x1 - x0 < 32:
        x0, x1 = (x0 + x1) // 2 - 16, (x0 + x1) // 2 + 16
    if y1 - y0 < 20:
        y0, y1 = (y0 + y1) // 2 - 10, (y0 + y1) // 2 + 10
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    if (x1 - x0) * (y1 - y0) > MAX_REGION * w * h:
        raise LearnFailed("Too much of the picture moved while learning. Keep hands away and the camera "
                          "still, then learn again.")
    step = 2 if (x1 - x0) * (y1 - y0) > 4000 else 1
    probe = Master((x0, y0, x1, y1), step, np.zeros((1, 1)), [0], [0], np.zeros((1, 1)), 1, 0, 0, "")
    vectors = np.stack([probe.vector(f[0]) for f in sweep])
    stills = np.stack([probe.vector(s) for s, _ in still])
    us = np.array([f[3] for f in sweep], dtype=np.float32)
    dirs = np.array([f[4] for f in sweep], dtype=np.int8)
    times = np.array([f[2] for f in sweep])

    normal = []
    for i in range(len(sweep)):
        ok = (np.abs(us - us[i]) < NEAR_US) & (np.abs(times - times[i]) > SAME_PASS_S)
        if dirs[i]:
            ok &= dirs == dirs[i]
        if ok.any():
            normal.append(float(((vectors[ok] - vectors[i]) ** 2).mean(axis=1).min()))
    if len(normal) < MIN_SWEEP_FRAMES // 2:
        raise LearnFailed("The sweep was too short to compare. Learn again.")
    p50, p99 = (float(v) for v in np.percentile(normal, [50, 99]))
    if p99 > UNSTEADY:
        raise LearnFailed("The arm didn't look the same on every sweep, so something moved while "
                          "learning. Keep hands away and learn again.")
    limit = max(LIMIT_FLOOR, LIMIT_FACTOR * p99)
    learned_at = (wall or datetime.now)().strftime("%Y-%m-%d %H:%M:%S")
    return Master((x0, y0, x1, y1), step, vectors, us, dirs, stills, limit, p50, p99, learned_at,
                  [f[1] for f in sweep], [k for _, k in still])


class Monitor:
    """The run state, the servo command and the inspection of every frame.

    Not thread-safe: the dashboard calls it under one lock. Times are seconds on a steady clock
    (time.monotonic on the Pi, a made-up clock in the tests).
    """

    def __init__(self, master=None, record=None, wall=None, keep=None):
        self.master = master
        self.record = record or (lambda row: None)  # receives one dict per inspected frame
        self.wall = wall or datetime.now
        self.keep = keep or (lambda frame: None)  # stores a frame for the page (a JPEG on the Pi)
        self.state = STOPPED if master else NOT_LEARNED
        self.reason = (f"Normal was learned at {master.learned_at}. Press Start to watch the arm."
                       if master else "Press Learn normal: the arm sweeps for 30 s while the camera "
                                      "learns what normal looks like.")
        self.sweep_t0 = None  # when the current sweep started
        self.moved_t = None  # when the arm last started moving or parking (for the grace period)
        # While stopped, a push on the arm counts only once the arm has been parked in the middle
        # (not straight after the dashboard starts: the arm may have been left anywhere).
        self.still_watch = False
        self.park_until = 0.0
        self.learn_t0 = None
        self.learn_still, self.learn_sweep = [], []
        self.streak, self.evidence = 0, None
        self.trip = None  # the anomaly or camera stop that is being shown
        self.trace = deque(maxlen=TRACE)
        self.events = deque(maxlen=200)
        self.seq = 0
        self.event_seq = 0
        self.last_frame_t = None
        self.frame_times = deque(maxlen=20)
        self.counts = {"inspected": 0, "over_limit": 0, "anomalies": 0, "sweeps": 0, "learned": 0}
        self.latest = None  # (mismatch, expected keep, seen degrees) of the last inspected frame
        self.expected_ref = None  # ("sweep" | "still", index) of the master image shown as EXPECTED
        self._sweeps_counted = 0

    # --- What the servo and LEDs are told -----------------------------------------------------

    def command(self, t):
        """(pulse in µs, or 0 for no pulses; direction) at time t."""
        if self.state == LEARNING:
            if t - self.learn_t0 < SETTLE_S:
                return MIDDLE_US, 0
            return int(sweep_us(t - self.sweep_t0)), sweep_direction(t - self.sweep_t0)
        if self.state == WATCHING:
            return int(sweep_us(t - self.sweep_t0)), sweep_direction(t - self.sweep_t0)
        if self.state in (STOPPED, NOT_LEARNED) and t < self.park_until:
            return MIDDLE_US, 0
        return 0, 0  # stopped, or after an anomaly: no pulses, so the arm is limp and not straining

    def leds(self, t):
        if self.state == WATCHING:
            return {"yellow": True, "red": False}
        if self.state == LEARNING:
            return {"yellow": (t % 1.0) < 0.5, "red": False}
        if self.state in (ANOMALY, NO_CAMERA):
            return {"yellow": False, "red": (t % 0.6) < 0.3}
        return {"yellow": False, "red": False}

    def check_camera(self, t):
        """Stop the motor when the camera has gone quiet: it cannot be watched."""
        if self.state not in (WATCHING, LEARNING):
            return
        since = self.learn_t0 if self.state == LEARNING else self.moved_t
        if self.last_frame_t is not None:
            since = max(since, self.last_frame_t)
        if t - since > CAMERA_TIMEOUT_S:
            if self.state == LEARNING:
                self._learn_failed(t, "The camera stopped sending pictures, so learning was cancelled.")
                return
            self.state = NO_CAMERA
            self.reason = "The camera stopped sending pictures, so the motor was stopped: it can't be watched."
            self.trip = {"kind": "camera", "time": self._stamp(), "text": self.reason}
            self._event("camera", self.reason)

    # --- Buttons ------------------------------------------------------------------------------

    def learn(self, t):
        self.state = LEARNING
        self.learn_t0 = t
        self.sweep_t0 = t + SETTLE_S
        self.learn_still, self.learn_sweep = [], []
        self.streak, self.evidence, self.trip = 0, None, None
        self.reason = "Learning normal: keep hands away from the arm. It holds still, then sweeps for 30 s."
        self._event("learn", "Learn normal started")

    def start(self, t, restart=False):
        if not self.master:
            raise ValueError("Learn normal first: there is nothing to compare with yet.")
        if self.last_frame_t is None or t - self.last_frame_t > CAMERA_TIMEOUT_S:
            raise ValueError("The camera isn't sending pictures, so the arm can't be watched.")
        self.state = WATCHING
        self.sweep_t0 = t
        self.moved_t = t
        self._sweeps_counted = 0
        self.streak, self.evidence, self.trip = 0, None, None
        self.reason = "Watching: every camera frame is compared with the master images."
        self._event("start", "Restarted after the anomaly" if restart else "Started watching")

    def restart(self, t):
        if self.state not in (ANOMALY, NO_CAMERA):
            raise ValueError("There is nothing to restart from.")
        self.start(t, restart=True)

    def stop(self, t):
        if self.state == LEARNING:
            self.learn_still, self.learn_sweep = [], []
            self.state = STOPPED if self.master else NOT_LEARNED
            self.reason = ("Learning was cancelled; the earlier normal is still in use." if self.master
                           else "Learning was cancelled. Press Learn normal to try again.")
            self._event("stop", "Learning cancelled")
        else:
            moving = self.state == WATCHING
            self.state = STOPPED if self.master else NOT_LEARNED
            self.reason = "Stopped. The camera still watches: a push on the arm counts as an anomaly."
            self._event("stop", "Stopped by hand" if moving else "Anomaly acknowledged, arm parked")
        self.park_until = t + PARK_S
        self.moved_t = t
        self.still_watch = self.master is not None
        self.streak, self.evidence, self.trip = 0, None, None

    # --- Each camera frame --------------------------------------------------------------------

    def on_frame(self, small, t, frame=None):
        """Inspect one camera frame (half-size grey picture, its time, the full frame for keeping)."""
        self.last_frame_t = t
        self.frame_times.append(t)
        if self.state == LEARNING:
            self._learning_frame(small, t, frame)
            return
        if not self.master:
            return
        us, direction = self.command(t)
        v = self.master.vector(small)
        seen = None
        if self.state == WATCHING:
            score, ref, seen = self.master.inspect(v, us, direction)
            self.expected_ref = ("sweep", ref)
            self._count_sweeps(t)
            watching = t - self.moved_t >= GRACE_S
            trace_us = us
        elif self.state == STOPPED:
            score, ref = self.master.inspect_still(v)
            self.expected_ref = ("still", ref)
            us = trace_us = MIDDLE_US  # where the arm should stay
            watching = self.still_watch and t - self.moved_t >= PARK_S + GRACE_S
        else:  # ANOMALY or NO CAMERA: nothing is judged until Restart, and nothing is plotted
            score, watching, trace_us = None, False, None
        limit = self.master.limit
        self.latest = (score, seen)
        event = ""
        if watching and score is not None:
            self.counts["inspected"] += 1
            if score > limit:
                self.counts["over_limit"] += 1
                self.streak += 1
                if self.streak == 1:
                    self.evidence = {"t": t, "time": self._stamp(), "score": score, "live": self.keep(frame),
                                     "expected": self.expected_ref, "command_deg": degrees(us),
                                     "seen_deg": degrees(seen)}
                else:
                    self.evidence["score"] = max(self.evidence["score"], score)
                if self.streak >= CONFIRM:
                    event = self._trip(t, us)
            else:
                self.streak, self.evidence = 0, None
        self._trace(t, trace_us, seen, score, event)

    def _count_sweeps(self, t):
        done = int((t - self.sweep_t0) // PERIOD_S)
        if done > self._sweeps_counted:
            self.counts["sweeps"] += done - self._sweeps_counted
            self._sweeps_counted = done

    def _trip(self, t, us):
        ev = self.evidence
        was = self.state
        cmd, seen = degrees(us), ev["seen_deg"]
        limit = self.master.limit
        numbers = f"(mismatch {ev['score']:.2f}, limit {limit:.2f})"
        if was == STOPPED:
            text = f"The arm moved while the motor was stopped {numbers}."
        else:
            recent = [s for s in self.trace if s[0] > self.seq - 6]
            seens = [s[3] for s in recent if s[3] is not None]
            cmds = [s[2] for s in recent if s[2] is not None]
            if (len(seens) >= 3 and max(seens) - min(seens) < STUCK_DEG and cmds
                    and max(cmds) - min(cmds) > TOLD_DEG):
                text = (f"The arm stopped moving while it was told to move {numbers}. Something may be "
                        "holding or blocking it, or the servo lost power.")
            elif seen is not None and cmd is not None and abs(seen - cmd) > TOLD_DEG:
                text = f"The arm was at about {seen:+.0f}° when it was told {cmd:+.0f}° {numbers}."
            else:
                text = (f"The arm didn't look the way it normally does at {cmd:+.0f}° {numbers}. Something "
                        "may be holding it or in front of the camera.")
        self.state = ANOMALY
        self.reason = text + (" Press Restart to sweep again." if was == STOPPED
                              else " The motor was stopped; press Restart to carry on.")
        self.counts["anomalies"] += 1
        self.trip = {"kind": "anomaly", "time": ev["time"], "text": text, "score": round(ev["score"], 3),
                     "limit": round(limit, 3), "command_deg": cmd, "seen_deg": seen,
                     "while": "stopped" if was == STOPPED else "sweeping", "live": ev["live"],
                     "expected": ev["expected"]}
        self._event("anomaly", text, score=round(ev["score"], 3), limit=round(limit, 3))
        self.trip["id"] = self.event_seq
        self.streak, self.evidence = 0, None
        return "anomaly"

    def _learning_frame(self, small, t, frame):
        if t - self.learn_t0 < SETTLE_S:
            if t - self.learn_t0 >= STILL_FROM_S:
                self.learn_still.append((small, self.keep(frame)))
            self._trace(t, MIDDLE_US, None, None, "")
            return
        st = t - self.sweep_t0
        if st < LEARN_S:
            us, direction = int(sweep_us(st)), sweep_direction(st)
            self.learn_sweep.append((small, self.keep(frame), t, us, direction))
            self._trace(t, us, None, None, "")
            return
        try:
            self.master = learn(self.learn_still, self.learn_sweep, self.wall)
        except LearnFailed as e:
            self._learn_failed(t, str(e))
            return
        finally:
            self.learn_still, self.learn_sweep = [], []
        m = self.master
        self.counts["learned"] += 1
        self._event("learned", f"Learned normal from {len(m.us)} master images; limit {m.limit:.2f} "
                               f"(normal frames differ by {m.normal_p50:.3f}, at most {m.normal_p99:.3f} "
                               "for 99 in 100)", limit=round(m.limit, 3))
        # Carry straight on watching the sweep that is already running.
        self.state = WATCHING
        self.moved_t = t
        self._sweeps_counted = int((t - self.sweep_t0) // PERIOD_S)
        self.streak, self.evidence, self.trip = 0, None, None
        self.reason = "Watching: every camera frame is compared with the master images."

    def _learn_failed(self, t, text):
        self.learn_still, self.learn_sweep = [], []
        self.state = STOPPED if self.master else NOT_LEARNED
        self.reason = text + (" The earlier normal is still in use." if self.master else "")
        self.park_until = t + PARK_S
        self.moved_t = t
        self._event("learn_failed", text)

    # --- Records ------------------------------------------------------------------------------

    def _stamp(self):
        return self.wall().strftime("%Y-%m-%d %H:%M:%S")

    def _event(self, kind, text, **extra):
        self.event_seq += 1
        self.events.append({"id": self.event_seq, "time": self._stamp(), "kind": kind, "text": text, **extra})

    def _trace(self, t, us, seen_us, score, event):
        self.seq += 1
        limit = self.master.limit if self.master else None
        cmd = degrees(us) if us else None
        seen = degrees(seen_us)
        self.trace.append((self.seq, round(t, 3), cmd, seen, None if score is None else round(score, 4),
                           STATE_CODE[self.state]))
        self.record({"timestamp": self._stamp(), "state": self.state, "command_us": us or "",
                     "command_deg": "" if cmd is None else cmd, "seen_deg": "" if seen is None else seen,
                     "mismatch": "" if score is None else f"{score:.4f}",
                     "limit": "" if limit is None else f"{limit:.4f}", "event": event})

    def fps(self):
        if len(self.frame_times) < 2:
            return None
        span = self.frame_times[-1] - self.frame_times[0]
        return round((len(self.frame_times) - 1) / span, 1) if span > 0 else None

    def learn_progress(self, t):
        if self.state != LEARNING:
            return None
        done = t - self.learn_t0
        total = SETTLE_S + LEARN_S
        return {"progress": round(min(1.0, done / total), 3), "phase": "still" if done < SETTLE_S else "sweep",
                "remaining_s": max(0, round(total - done)), "pictures": len(self.learn_still) + len(self.learn_sweep)}

    def snapshot(self, t, after=0):
        us, direction = self.command(t)
        m = self.master
        score, seen = self.latest if self.latest else (None, None)
        trip = None
        if self.trip:
            trip = {k: v for k, v in self.trip.items() if k not in ("live", "expected")}
        return {
            "state": self.state,
            "reason": self.reason,
            "mode": "SETUP" if self.state in (LEARNING, NOT_LEARNED) else "RUN",
            "learn": self.learn_progress(t),
            "master": None if not m else {"learned_at": m.learned_at, "limit": round(m.limit, 3),
                                          "normal_p50": round(m.normal_p50, 4), "normal_p99": round(m.normal_p99, 4),
                                          "images": int(len(m.us)), "still_images": int(len(m.still))},
            "now": {"pulse_us": us, "command_deg": degrees(us) if us else None, "direction": direction,
                    "seen_deg": degrees(seen), "mismatch": None if score is None else round(score, 4),
                    "limit": round(m.limit, 3) if m else None, "fps": self.fps(),
                    "camera_age_s": None if self.last_frame_t is None else round(t - self.last_frame_t, 1)},
            "trip": trip,
            "counts": dict(self.counts),
            "seq": self.seq,
            "trace": [list(s) for s in self.trace if s[0] > after],
            "events": list(self.events)[-40:],
        }
