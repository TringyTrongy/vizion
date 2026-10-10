"""The fan: the SG90 servo on GPIO18, switched on and off by humidity, with safety checks that shut
it down.

The SG90 turns about 180° and cannot spin round, so "running" means it sweeps back and forth like
an oscillating desk fan.

Control. In Auto, humidity at or above the ON level starts the fan, and at or below the OFF level
stops it. The gap between the two (hysteresis) stops the fan flicking on and off around one value.
Hand runs the fan whatever the humidity and Off keeps it stopped, like the Hand-Off-Auto switch on
an industrial motor starter.

Safety checks. When one fails the fan shuts down: it stops, the red LED flashes, and it stays
stopped until someone presses Restart on the dashboard.

1. Sensor lost (Auto): the DHT11 stopped answering (its SENSOR ERROR alert: three failed reads in
   a row). The humidity is unknown, so the fan can't be controlled.
2. No effect (Auto): the fan has run for 60 s and the humidity has not come down at all. A fan
   that is blocked or broken, or a moisture source too big for it, looks like this.
3. Short cycling (Auto): the fan was about to start for the 4th time within 3 minutes. Starting
   that often wears a motor out; the humidity is hovering at the ON level or the readings are noisy.
4. Pi power: the Pi reports under-voltage while the fan runs. The servo shares the Pi's 5 V, and
   a jammed motor on a weak supply can make the Pi crash.
5. Emergency stop, pressed on the dashboard.

What it cannot see: the SG90 reports nothing back, neither its position nor its current, so a hand
holding or turning the shaft goes unnoticed. Measured on 10 Oct: the Pi's 5 V reading stayed at
5.143 V with the servo off, holding, or reversing flat out. Seeing that needs a current sensor or
a servo with a feedback wire (README).

LEDs: yellow (GPIO27, pin 13) is lit while the fan runs; red (GPIO17, pin 11) flashes while it is
shut down.
"""
import json
import math
import subprocess
import threading
import time
from collections import deque
from datetime import datetime

SERVO_GPIO = 18  # header pin 12
RED_LED_GPIO = 17  # header pin 11
YELLOW_LED_GPIO = 27  # header pin 13

MIDDLE_US = 1500
SWEEP_US = 450  # the sweep swings ±450 µs around the middle
DEG_PER_US = 0.09  # SG90: about 180° across 500–2500 µs, so the sweep is about ±40°
SWEEP_PERIOD_S = 3.0  # there and back
PARK_S = 0.8  # after stopping, hold the middle this long, then stop the pulses (no hum, no jitter)
TICK_S = 0.04  # the servo and LEDs are updated 25 times a second

DEFAULT_ON, DEFAULT_OFF = 75, 70  # % humidity; the room sits around 65 %, a cupped hand passes 80 %
ON_RANGE = (30, 95)
OFF_MIN = 25
MIN_GAP = 2  # the DHT11 reads whole percent: a smaller gap lets one count flip the fan
NO_EFFECT_S = 60
CYCLE_STARTS, CYCLE_WINDOW_S = 4, 180
MODES = {"auto": "Auto", "hand": "Hand", "off": "Off"}


# --- Outputs: the servo and the LEDs ---------------------------------------------------------

class GpioOutputs:
    """The servo and the two LEDs, through lgpio. An LED whose pin is busy is left out."""

    def __init__(self, servo=SERVO_GPIO, leds=(("red", RED_LED_GPIO), ("yellow", YELLOW_LED_GPIO))):
        import lgpio  # only on the Pi

        from sensor_reader import open_header_chip

        self.lg = lgpio
        self.chip = open_header_chip(lgpio)
        self.servo_gpio = servo
        try:
            lgpio.gpio_claim_output(self.chip, servo, 0)
        except lgpio.error as e:
            lgpio.gpiochip_close(self.chip)
            raise RuntimeError(f"GPIO{servo} is busy ({e})") from e
        self.leds, self.lit = {}, {}
        self.note = None
        for name, gpio in leds:
            try:
                lgpio.gpio_claim_output(self.chip, gpio, 0)
                self.leds[name], self.lit[name] = gpio, False
            except lgpio.error:
                self.note = f"GPIO{gpio} is busy, so the LEDs are off. Is the camera dashboard running?"
        self.pulse = 0
        self.method = f"lgpio on GPIO{servo}"

    def servo(self, us):
        """Pulse width in µs, or 0 to stop the pulses (the servo goes limp and quiet)."""
        us = int(us or 0)
        if us == self.pulse:
            return
        if us:
            self.lg.tx_servo(self.chip, self.servo_gpio, us, 50)
        else:
            try:
                self.lg.tx_servo(self.chip, self.servo_gpio, 0)
            except self.lg.error:  # lgpio refuses 0 when no pulses are running
                pass
        self.pulse = us

    def led(self, name, on):
        if name in self.leds and self.lit[name] != bool(on):
            self.lg.gpio_write(self.chip, self.leds[name], 1 if on else 0)
            self.lit[name] = bool(on)

    def close(self):
        self.servo(0)
        time.sleep(0.05)
        for name in list(self.leds):
            self.led(name, False)
        for gpio in [self.servo_gpio, *self.leds.values()]:
            try:
                self.lg.gpio_free(self.chip, gpio)
            except self.lg.error:
                pass
        self.lg.gpiochip_close(self.chip)


class NoOutputs:
    """Stands in for the GPIO on a computer without it, and in the tests: it remembers what it was told."""

    method = None

    def __init__(self, note="No GPIO here: the servo and LEDs are not driven"):
        self.note = note
        self.pulse = 0
        self.leds = {}  # no real LEDs
        self.lit = {"red": False, "yellow": False}

    def servo(self, us):
        self.pulse = int(us or 0)

    def led(self, name, on):
        self.lit[name] = bool(on)

    def close(self):
        self.pulse = 0


def open_outputs(servo=SERVO_GPIO, leds=True):
    led_pins = (("red", RED_LED_GPIO), ("yellow", YELLOW_LED_GPIO)) if leds else ()
    try:
        return GpioOutputs(servo, led_pins)
    except ImportError:
        return NoOutputs()
    except Exception as e:  # no GPIO chip, pin busy...
        return NoOutputs(f"Servo not available: {e}")


def read_power():
    """(5 V supply in volts, under-voltage now) from the Pi's power chip; (None, None) off a Pi."""
    try:
        volts = subprocess.run(["vcgencmd", "pmic_read_adc", "EXT5V_V"], capture_output=True,
                               text=True, timeout=2).stdout
        flags = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
        return float(volts.strip().split("=")[-1].rstrip("V")), bool(int(flags.strip().split("=")[-1], 16) & 1)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None, None


def load_settings(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        return {}


# --- The controller --------------------------------------------------------------------------

def stamp(t):
    return t.strftime("%Y-%m-%d %H:%M:%S")


class FanController:
    """Decides when the fan runs and when it must shut down. update() once a second with the
    newest humidity; the page's buttons call set_mode(), set_levels(), emergency_stop(), restart().
    A thread (start_motion) moves the servo and lights the LEDs from the decisions."""

    def __init__(self, outputs, settings=None, settings_path=None):
        self.out = outputs
        self.settings_path = settings_path
        s = settings or {}
        self.mode = s.get("mode") if s.get("mode") in MODES else "auto"
        try:
            self.on_at, self.off_at = self._check_levels(s.get("on_at", DEFAULT_ON), s.get("off_at", DEFAULT_OFF))
        except ValueError:
            self.on_at, self.off_at = DEFAULT_ON, DEFAULT_OFF
        self.lock = threading.RLock()
        self.running = False
        self.trip = None  # {"check", "reason", "at"} while shut down
        self.run_started = None
        self.effect_t0 = None  # the no-effect check compares with the humidity when Auto started the fan
        self.run_start_humidity = None
        self.starts = deque()  # when Auto started the fan, for the short-cycling check
        self.humidity = None
        self.sensor = "waiting"  # ok, failing (one read failed), error (alert open), paused, waiting, none
        self.sensor_age_s = None
        self.volts = None
        self.under_voltage = None
        self.why = "Starting."
        self.events = deque(maxlen=200)  # the dashboard's timeline: runs, shutdowns and changes
        self.log_lines = []  # the same changes as one line each, for the CSV log (see drain_log)
        self.next_id = 1
        self.open_run = None
        self.open_trip = None
        self.counts = {"starts": 0, "shutdowns": 0}
        self.run_total_s = 0.0
        self.sweep_t0 = time.monotonic()
        self.park_until = 0.0
        self.motion_error = None
        self._stop = threading.Event()
        self._thread = None

    # --- inputs -------------------------------------------------------------------------------
    def update(self, now, humidity, sensor, age_s=None, volts=None, under_voltage=None):
        """humidity: the newest good DHT11 value (None if there is none recent)."""
        with self.lock:
            self.humidity, self.sensor, self.sensor_age_s = humidity, sensor, age_s
            self.volts, self.under_voltage = volts, under_voltage
            self._evaluate(now)

    def _evaluate(self, now):
        if self.trip:
            return
        h = self.humidity
        if self.mode == "auto" and self.sensor == "error":
            return self._shut_down(now, "sensor", "The DHT11 stopped answering (3 failed reads in a row), "
                                                  "so the humidity is unknown")
        if self.running and self.under_voltage:
            return self._shut_down(now, "power", "The Pi reported under-voltage while the fan was running")
        if self.running and self.mode == "auto" and h is not None:
            if self.effect_t0 is None or self.run_start_humidity is None:  # Auto took over a running fan
                self.effect_t0, self.run_start_humidity = now, h
            ran = (now - self.effect_t0).total_seconds()
            if ran >= NO_EFFECT_S and h >= self.run_start_humidity:
                return self._shut_down(now, "effect", f"The fan ran {ran:.0f} s and the humidity did not come "
                                                      f"down ({self.run_start_humidity:.0f}% → {h:.0f}%)")
        want, self.why, cause = self._decide()
        if want and not self.running:
            if self.mode == "auto":
                while self.starts and (now - self.starts[0]).total_seconds() >= CYCLE_WINDOW_S:
                    self.starts.popleft()
                if len(self.starts) + 1 >= CYCLE_STARTS:
                    return self._shut_down(now, "cycling", f"The fan was about to start for the {CYCLE_STARTS}th "
                                                           f"time in {CYCLE_WINDOW_S // 60} minutes")
                self.starts.append(now)
            self._start(now, cause)
        elif not want and self.running:
            self._stop_run(now, cause)

    def _decide(self):
        """-> (should the fan run, the sentence for the dashboard, the cause for the timeline)."""
        on, off = self.on_at, self.off_at
        if self.mode == "off":
            return False, "Off: the fan stays stopped whatever the humidity.", "Switched to Off"
        if self.mode == "hand":
            return True, ("Hand: the fan runs whatever the humidity. The power check and the emergency "
                          "stop still apply."), "Switched to Hand"
        if self.sensor == "paused":
            return False, "DHT11 readings are paused, so Auto waits with the fan off.", "DHT11 readings paused"
        if self.sensor == "none":
            return False, "No DHT11 is set up, so Auto has nothing to go on.", "No DHT11"
        h = self.humidity
        if h is None:
            return False, "Waiting for a humidity reading from the DHT11.", "No recent humidity reading"
        now = f"Humidity {h:.0f}%"
        if h >= on:
            return True, f"{now} has reached the {on}% ON level, so the fan runs until it falls to {off}%.", \
                f"{now} reached the {on}% ON level"
        if h <= off:
            return False, f"{now} is below the {on}% ON level, so the fan is off.", \
                f"{now} fell to the {off}% OFF level"
        if self.running:
            return True, f"{now} is still above the {off}% OFF level, so the fan keeps running.", ""
        return False, f"{now} is between {off}% and {on}%: the fan stays off until {on}%.", ""

    # --- the page's buttons -------------------------------------------------------------------
    def set_mode(self, mode, now=None):
        if mode not in MODES:
            raise ValueError(f"Unknown mode {mode!r}")
        now = now or datetime.now()
        with self.lock:
            if mode != self.mode:
                self.mode = mode
                self.effect_t0 = None  # Auto judges a running fan from now on, not from when Hand started it
                self._note(now, f"Mode: {MODES[mode]}")
                self._save()
                self._evaluate(now)
            return self._mode_message()

    def _mode_message(self):
        text = {"auto": f"Auto: the humidity decides (on at {self.on_at}%, off at {self.off_at}%).",
                "hand": "Hand: the fan runs whatever the humidity.",
                "off": "Off: the fan stays stopped."}[self.mode]
        return text + (" It is still shut down: press Restart." if self.trip else "")

    @staticmethod
    def _check_levels(on_at, off_at):
        on_at, off_at = int(on_at), int(off_at)
        if not ON_RANGE[0] <= on_at <= ON_RANGE[1]:
            raise ValueError(f"The ON level must be between {ON_RANGE[0]} and {ON_RANGE[1]}%")
        if off_at < OFF_MIN:
            raise ValueError(f"The OFF level can't go below {OFF_MIN}%")
        if on_at - off_at < MIN_GAP:
            raise ValueError(f"Keep the OFF level at least {MIN_GAP}% below the ON level")
        return on_at, off_at

    def set_levels(self, on_at, off_at, now=None):
        now = now or datetime.now()
        on_at, off_at = self._check_levels(on_at, off_at)
        with self.lock:
            if (on_at, off_at) != (self.on_at, self.off_at):
                self.on_at, self.off_at = on_at, off_at
                text = f"Levels: on at {on_at}%, off at {off_at}%"
                last = self.events[-1] if self.events else None
                if last and last["kind"] == "NOTE" and last["reasons"][0].startswith("Levels:") \
                        and (now - last["at"]).total_seconds() < 15:
                    last["reasons"][0] = text  # a few taps on + or − make one entry
                    self.log_lines.append(text)
                else:
                    self._note(now, text)
                self._save()
                self._evaluate(now)
            return f"The fan now starts at {on_at}% and stops at {off_at}%."

    def emergency_stop(self, now=None):
        now = now or datetime.now()
        with self.lock:
            if self.trip:
                return "Already shut down."
            self._shut_down(now, "estop", "Emergency stop pressed on the dashboard")
            return "Emergency stop: the fan is shut down until you press Restart."

    def restart(self, now=None):
        """-> (ok, message). Refused while the cause is still there."""
        now = now or datetime.now()
        with self.lock:
            if not self.trip:
                return False, "The fan is not shut down."
            if self.mode == "auto" and self.sensor in ("error", "failing"):
                return False, ("The DHT11 is still not answering. Check its wiring, or switch to Hand "
                               "or Off to restart without it.")
            if self.under_voltage and self.mode != "off":
                return False, "The Pi still reports under-voltage. Check the power supply first."
            self.trip = None
            self.starts.clear()
            if self.open_trip:
                self.open_trip["end"] = now
                self.open_trip["reasons"].append(f"Restarted from the dashboard at {now:%H:%M:%S}")
                self.open_trip = None
            self.log_lines.append("Restarted from the dashboard")
            self._evaluate(now)
            return True, "Restarted. " + self.why

    # --- state changes ------------------------------------------------------------------------
    def _event(self, kind, now, reasons):
        e = {"id": self.next_id, "kind": kind, "at": now, "end": None, "reasons": list(reasons)}
        self.next_id += 1
        self.events.append(e)
        return e

    def _note(self, now, text):
        e = self._event("NOTE", now, [text])
        e["end"] = now
        self.log_lines.append(text)
        return e

    def _start(self, now, cause):
        self.running = True
        self.run_started = self.effect_t0 = now
        self.run_start_humidity = self.humidity
        self.counts["starts"] += 1
        self.sweep_t0 = time.monotonic()
        self.open_run = self._event("RUN", now, [cause or "Started"])
        self.log_lines.append(f"Fan started: {cause or 'Started'}")

    def _stop_run(self, now, cause):
        self.running = False
        self.run_total_s += (now - self.run_started).total_seconds()
        self.park_until = time.monotonic() + PARK_S
        if self.open_run:
            self.open_run["end"] = now
            if cause:
                self.open_run["reasons"].append(cause)
            self.open_run = None
        self.log_lines.append(cause if cause.startswith("Stopped") else f"Fan stopped: {cause}")

    def _shut_down(self, now, check, reason):
        if self.running:
            self._stop_run(now, "Stopped by the shutdown")
        self.trip = {"check": check, "reason": reason, "at": now}
        self.counts["shutdowns"] += 1
        self.open_trip = self._event("SHUTDOWN", now, [reason])
        self.log_lines.append(f"SHUT DOWN: {reason}")
        self.why = reason

    def _save(self):
        if self.settings_path:
            try:
                self.settings_path.parent.mkdir(parents=True, exist_ok=True)
                self.settings_path.write_text(json.dumps({"mode": self.mode, "on_at": self.on_at,
                                                          "off_at": self.off_at}), encoding="utf-8")
            except OSError:
                pass

    # --- what the page shows ------------------------------------------------------------------
    @property
    def state(self):
        if self.trip:
            return "SHUT DOWN"
        if self.running:
            return "RUNNING"
        if self.mode == "off":
            return "OFF"
        if self.mode == "auto" and (self.humidity is None or self.sensor in ("paused", "none")):
            return "WAITING"
        return "STANDBY"

    def run_seconds(self, now):
        return (now - self.run_started).total_seconds() if self.running else None

    def snapshot(self, now):
        with self.lock:
            sweep = None
            if self.running:
                sweep = ((time.monotonic() - self.sweep_t0) / SWEEP_PERIOD_S) % 1
            run_for = self.run_seconds(now)
            return {
                "state": self.state, "mode": self.mode, "on_at": self.on_at, "off_at": self.off_at,
                "running": self.running, "why": self.why,
                "trip": dict(self.trip, at=stamp(self.trip["at"])) if self.trip else None,
                "humidity": self.humidity, "sensor": self.sensor, "sensor_age_s": self.sensor_age_s,
                "run_for_s": run_for, "run_start_humidity": self.run_start_humidity if self.running else None,
                "sweep_phase": sweep, "pulse_us": self.out.pulse,
                "volts": self.volts, "under_voltage": self.under_voltage,
                "leds": {k: self.out.lit.get(k, False) for k in self.out.leds},
                "outputs_note": self.out.note, "motion_error": self.motion_error,
                "checks": self._checks(now),
            }

    def _checks(self, now):
        auto = self.mode == "auto"
        trip = self.trip["check"] if self.trip else None
        out = []

        # 1. Sensor
        if trip == "sensor":
            st, text = "tripped", "Stopped answering"
        elif not auto:
            st, text = "idle", f"Not needed in {MODES[self.mode]}"
        elif self.sensor == "ok":
            age = self.sensor_age_s
            st, text = "ok", "Answering" + (f" · last reading {age:.0f} s ago" if age is not None else "")
        elif self.sensor == "failing":
            st, text = "watch", "The last read failed; trying again"
        elif self.sensor == "error":
            st, text = "watch", "Not answering"
        elif self.sensor == "paused":
            st, text = "idle", "Readings paused"
        else:
            st, text = "idle", "Waiting for a reading"
        out.append({"key": "sensor", "label": "DHT11 answering", "state": st, "now": text,
                    "trips": "3 failed reads in a row"})

        # 2. No effect
        run_for = self.run_seconds(now)
        if trip == "effect":
            st, text = "tripped", "Humidity did not come down"
        elif not auto:
            st, text = "idle", f"Not checked in {MODES[self.mode]}"
        elif run_for is None or self.humidity is None or self.run_start_humidity is None:
            st, text = "idle", "The fan is not running"
        else:
            judged = (now - self.effect_t0).total_seconds() if self.effect_t0 else run_for
            fell = self.humidity < self.run_start_humidity
            st = "ok" if fell or judged < NO_EFFECT_S / 2 else "watch"
            text = (f"Running {min(judged, NO_EFFECT_S):.0f} of {NO_EFFECT_S} s · {self.run_start_humidity:.0f}% → "
                    f"{self.humidity:.0f}%")
        out.append({"key": "effect", "label": "Fan brings humidity down", "state": st, "now": text,
                    "trips": f"No fall after {NO_EFFECT_S} s"})

        # 3. Short cycling
        recent = sum((now - t).total_seconds() < CYCLE_WINDOW_S for t in self.starts)
        if trip == "cycling":
            st, text = "tripped", f"{CYCLE_STARTS} starts in {CYCLE_WINDOW_S // 60} min"
        elif not auto:
            st, text = "idle", f"Not checked in {MODES[self.mode]}"
        else:
            st = "watch" if recent >= CYCLE_STARTS - 1 else "ok"
            text = f"{recent} start{'' if recent == 1 else 's'} in the last {CYCLE_WINDOW_S // 60} min"
        out.append({"key": "cycling", "label": "Not short cycling", "state": st, "now": text,
                    "trips": f"A {CYCLE_STARTS}th start within {CYCLE_WINDOW_S // 60} min"})

        # 4. Power
        if trip == "power":
            st, text = "tripped", "Under-voltage reported"
        elif self.volts is None:
            st, text = "idle", "Not readable on this computer"
        elif self.under_voltage:
            st, text = "watch", f"{self.volts:.2f} V · under-voltage reported"
        else:
            st, text = "ok", f"{self.volts:.2f} V · no under-voltage"
        out.append({"key": "power", "label": "Pi power", "state": st, "now": text,
                    "trips": "Under-voltage while running"})

        if trip == "estop":
            out.append({"key": "estop", "label": "Emergency stop", "state": "tripped",
                        "now": "Pressed on the dashboard", "trips": "Pressed"})
        return out

    def drain_log(self):
        with self.lock:
            lines, self.log_lines = self.log_lines, []
            return lines

    def timeline(self, n=12):
        with self.lock:
            items = list(self.events)[-n:][::-1]
            return [{"id": e["id"], "kind": e["kind"], "start": stamp(e["at"]),
                     "end": stamp(e["end"]) if e["end"] else None, "reasons": list(e["reasons"])} for e in items]

    def totals(self, now):
        with self.lock:
            run = self.run_total_s + (self.run_seconds(now) or 0)
            return dict(self.counts, run_s=round(run))

    # --- the servo and the LEDs ---------------------------------------------------------------
    def start_motion(self):
        if not self._thread:
            self._thread = threading.Thread(target=self._motion, name="fan-motion", daemon=True)
            self._thread.start()

    def pulse_now(self, t):
        """The pulse width the servo should get at monotonic time t."""
        with self.lock:
            if self.running:
                phase = ((t - self.sweep_t0) / SWEEP_PERIOD_S) % 1
                return round((MIDDLE_US + SWEEP_US * math.sin(2 * math.pi * phase)) / 5) * 5
            return MIDDLE_US if t < self.park_until else 0

    def _motion(self):
        while not self._stop.wait(TICK_S):
            t = time.monotonic()
            try:
                self.out.servo(self.pulse_now(t))
                self.out.led("yellow", self.running)
                self.out.led("red", self.trip is not None and t % 0.6 < 0.3)
                self.motion_error = None
            except Exception as e:  # keep trying: a busy pin may come free
                self.motion_error = str(e)

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        try:
            self.out.close()
        except Exception:
            pass
