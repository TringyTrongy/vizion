"""Where readings come from: the DHT11 on the Pi, a simulated DHT11, or a public dataset replay.

Every source returns a Reading. A reading that failed has `error` set and no values.

DHT11 on a Raspberry Pi 5: the old Adafruit_DHT library does not support the Pi 5, so there are
two ways in, both tried by open_dht11():

- Kernel driver (most reliable): add `dtoverlay=dht11,gpiopin=4` to /boot/firmware/config.txt
  and reboot. The kernel times the pulses and the values appear under /sys/bus/iio/devices.
- lgpio (no setup): the Pi 5's GPIO library. The kernel timestamps every edge of the DHT11's
  reply and this module decodes the pulse widths. A read occasionally fails; the next one is
  2 s later.
"""
import errno
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

DHT11_GPIO = 4  # header pin 7
MIN_READ_INTERVAL_S = 1.0  # the DHT11 needs at least 1 s between reads


@dataclass
class Reading:
    timestamp: datetime
    temperature_c: float | None = None
    humidity_percent: float | None = None
    error: str | None = None  # why the reading failed
    note: str | None = None  # e.g. which simulated event is running


class Dht11Error(Exception):
    pass


def decode_dht11(edges):
    """Decodes one DHT11 reply.

    edges: [(time_ns, level)] in time order, level being the line level after the edge.
    Returns (humidity_percent, temperature_c); raises Dht11Error with the reason.

    The reply is a start pulse and then 40 bits, each a ~50 µs low followed by a high whose length
    is the bit: 26–28 µs means 0, 70 µs means 1. Only the high lengths matter, and only the last
    40, so an edge missed at the very start does not matter.
    """
    highs = []
    rise = None
    for t, level in edges:
        if level == 1:
            rise = t
        elif level == 0 and rise is not None:
            highs.append((t - rise) / 1000)
            rise = None
    if len(highs) == 0:
        raise Dht11Error(f"No reply from the DHT11 on GPIO{DHT11_GPIO} (check the wiring and power)")
    if len(highs) < 40:
        raise Dht11Error(f"Incomplete reply from the DHT11 ({len(highs)} of 40 bits)")
    bits = highs[-40:]
    if max(bits) > 120 or min(bits) < 8:
        raise Dht11Error("Garbled reply from the DHT11 (pulse timing out of range)")
    data = [int("".join("1" if w > 48 else "0" for w in bits[i:i + 8]), 2) for i in range(0, 40, 8)]
    if sum(data[:4]) & 0xFF != data[4]:
        raise Dht11Error("DHT11 checksum mismatch (noise or a loose wire)")
    humidity = data[0] + data[1] / 10
    temperature = data[2] + (data[3] & 0x7F) / 10
    if data[3] & 0x80:  # newer DHT11s report below 0 °C this way
        temperature = -temperature
    return humidity, temperature


def encode_dht11(humidity, temperature, start_ns=0, preamble=True):
    """The edges a DHT11 would produce for these values. For tests and the simulator's self-check."""
    t_int, t_dec = int(abs(temperature)), round((abs(temperature) % 1) * 10)
    data = [int(humidity), round((humidity % 1) * 10), t_int, t_dec | (0x80 if temperature < 0 else 0)]
    data.append(sum(data) & 0xFF)
    t = start_ns
    edges = []
    if preamble:
        edges += [(t, 0), (t + 80_000, 1)]
        t += 160_000
    for byte in data:
        for i in range(7, -1, -1):
            edges.append((t, 0))
            t += 50_000
            edges.append((t, 1))
            t += 70_000 if byte >> i & 1 else 27_000
    edges.append((t, 0))
    edges.append((t + 50_000, 1))
    return edges


class Dht11Kernel:
    """Reads the kernel's dht11 driver (dtoverlay=dht11)."""

    method = "the kernel driver"

    def __init__(self, device):
        self.device = device

    @staticmethod
    def find():
        for d in sorted(Path("/sys/bus/iio/devices").glob("iio:device*")):
            try:
                if (d / "name").read_text().strip() == "dht11":
                    return d
            except OSError:
                pass
        return None

    def read(self):
        now = datetime.now()
        try:
            temperature = int((self.device / "in_temp_input").read_text()) / 1000
            humidity = int((self.device / "in_humidityrelative_input").read_text()) / 1000
        except OSError as e:
            if e.errno == errno.ETIMEDOUT:
                why = f"No reply from the DHT11 on GPIO{DHT11_GPIO} (check the wiring and power)"
            else:
                why = f"DHT11 read failed ({e.strerror or e})"
            return Reading(now, error=why)
        except ValueError:
            return Reading(now, error="DHT11 driver returned no number")
        return Reading(now, round(temperature, 1), round(humidity, 1))

    def close(self):
        pass


def open_header_chip(lgpio):
    """The gpiochip of the 40-pin header (gpiochip0 on current Pi 5 kernels, gpiochip4 on older ones)."""
    for n in (0, 4, 1, 2, 3, 5):
        try:
            handle = lgpio.gpiochip_open(n)
        except lgpio.error:
            continue
        try:
            label = lgpio.gpio_get_chip_info(handle)[3]
        except lgpio.error:
            label = ""
        if "rp1" in label or "bcm2835" in label or "bcm2711" in label:
            return handle
        lgpio.gpiochip_close(handle)
    raise RuntimeError("Could not find the GPIO chip for the 40-pin header")


class Dht11Gpio:
    """Reads the DHT11 from user space with lgpio. Works on the Pi 5 without any setup."""

    method = "lgpio"

    def __init__(self, gpio=DHT11_GPIO):
        import lgpio  # only on the Pi

        self.lg = lgpio
        self.gpio = gpio
        self.chip = open_header_chip(lgpio)
        self.edges = []
        self.last = 0.0

    def _edge(self, _chip, _gpio, level, tick):
        if level in (0, 1):  # 2 would be a watchdog timeout
            self.edges.append((tick, level))

    def read(self):
        lg = self.lg
        wait = self.last + MIN_READ_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.edges = []
        callback = None
        try:
            # Start signal: hold the line low for 20 ms, then let the pull-up raise it and listen.
            lg.gpio_claim_output(self.chip, self.gpio, 0)
            time.sleep(0.02)
            callback = lg.callback(self.chip, self.gpio, lg.BOTH_EDGES, self._edge)
            lg.gpio_claim_alert(self.chip, self.gpio, lg.BOTH_EDGES, lg.SET_PULL_UP)
            time.sleep(0.03)  # the reply takes about 5 ms; edges reach Python a little later
            count = -1
            for _ in range(20):
                if len(self.edges) == count:
                    break
                count = len(self.edges)
                time.sleep(0.005)
        except lg.error as e:
            return Reading(datetime.now(), error=f"GPIO{self.gpio} is not available ({e})")
        finally:
            self.last = time.monotonic()
            if callback is not None:
                callback.cancel()
            try:
                lg.gpio_free(self.chip, self.gpio)
            except lg.error:
                pass
        now = datetime.now()
        try:
            humidity, temperature = decode_dht11(sorted(self.edges))
        except Dht11Error as e:
            return Reading(now, error=str(e))
        return Reading(now, round(temperature, 1), round(humidity, 1))

    def close(self):
        try:
            self.lg.gpiochip_close(self.chip)
        except self.lg.error:
            pass


def open_dht11(gpio=DHT11_GPIO, method="auto"):
    """The kernel driver if it is set up, else lgpio."""
    if method in ("auto", "kernel"):
        device = Dht11Kernel.find()
        if device:
            return Dht11Kernel(device)
        if method == "kernel":
            raise RuntimeError("The dht11 kernel driver is not loaded (dtoverlay=dht11,gpiopin=4)")
    return Dht11Gpio(gpio)


# --- Simulated DHT11 -------------------------------------------------------------------------

SIM_EVENTS = {
    # kind: (label, duration in s, what to expect)
    "heat": ("Heat spike", 220, "warm air: temperature up 7 °C, humidity down"),
    "humidity": ("Humidity surge", 170, "humidity up 22 % within 15 s, like breath or steam"),
    "drift": ("Slow drift", 420, "temperature creeps up 3.5 °C over 6 minutes. A rolling baseline follows "
              "slow changes, so this is the hard case: expect little or no alert until it ends"),
    "fault": ("Sensor fault", 14, "the sensor stops answering for 14 s"),
}


def _envelope(e, rise, hold, fall):
    """0 → 1 over `rise` s, 1 for `hold` s, back to 0 over `fall` s."""
    if e < 0:
        return 0.0
    if e < rise:
        return e / rise
    if e < rise + hold:
        return 1.0
    return max(0.0, 1 - (e - rise - hold) / fall)


class SimulatedDht11:
    """DHT11-like readings for building and testing without the sensor. Never real data.

    A quiet room around 26 °C and 55 %RH with slow wander and sensor noise, rounded like a DHT11.
    inject() adds an event; with auto_events one starts by itself every 5–9 minutes.
    """

    method = "simulation"

    def __init__(self, seed=None, auto_events=True, clock=time.time):
        self.rng = random.Random(seed)
        self.clock = clock
        self.t0 = clock()
        self.auto_events = auto_events
        self.events = []  # (kind, start)
        self.next_auto = self.t0 + self.rng.uniform(150, 300)

    def inject(self, kind, at=None):
        if kind not in SIM_EVENTS:
            raise ValueError(f"unknown event {kind!r}")
        self.events.append((kind, self.clock() if at is None else at))

    def active(self, now=None):
        now = self.clock() if now is None else now
        return [k for k, s in self.events if 0 <= now - s < SIM_EVENTS[k][1]]

    def read(self, now=None):
        now = self.clock() if now is None else now
        if self.auto_events and now >= self.next_auto:
            if not self.active(now):
                self.inject(self.rng.choice(["heat", "humidity", "drift", "fault"]), now)
            self.next_auto = now + self.rng.uniform(300, 540)
        self.events = [(k, s) for k, s in self.events if now - s < SIM_EVENTS[k][1]]
        stamp = datetime.fromtimestamp(now)
        active = self.active(now)
        note = ", ".join(SIM_EVENTS[k][0] for k in active) or None
        if "fault" in active:
            return Reading(stamp, error="No reply from the DHT11 (simulated fault)", note=note)
        e = now - self.t0
        temperature = 26.0 + 0.4 * math.sin(2 * math.pi * e / 1200) + 0.2 * math.sin(2 * math.pi * e / 337)
        humidity = 55.0 + 1.5 * math.sin(2 * math.pi * e / 1500 + 1.0)
        temperature += self.rng.gauss(0, 0.08)
        humidity += self.rng.gauss(0, 0.4)
        for kind, start in self.events:
            el = now - start
            if kind == "heat":  # warm air: temperature up, relative humidity down
                env = _envelope(el, 40, 60, 120)
                temperature += 7.0 * env
                humidity -= 8.0 * env
            elif kind == "humidity":  # someone breathes on it, or a kettle nearby
                env = _envelope(el, 15, 35, 120)
                humidity += 22.0 * env
                temperature += 0.4 * env
            elif kind == "drift":
                temperature += 3.5 * _envelope(el, 360, 0, 60)
        return Reading(stamp, round(temperature, 1), float(round(humidity)), note=note)

    def close(self):
        pass


# --- Public dataset replay --------------------------------------------------------------------

class ReplaySource:
    """Plays back a public dataset, one row per read(). The values keep the dataset's own units."""

    method = "replay"

    def __init__(self, rows, start=0):
        self.rows = rows  # [(datetime, value)]
        self.index = start

    def read(self):
        if self.index >= len(self.rows):
            return None
        t, value = self.rows[self.index]
        self.index += 1
        return Reading(t, value, None)

    @property
    def progress(self):
        return self.index / max(len(self.rows), 1)

    def close(self):
        pass


if __name__ == "__main__":
    # Quick check on the Pi:  .venv/bin/python sensor_monitor/sensor_reader.py
    import sys

    method = sys.argv[1] if len(sys.argv) > 1 else "auto"
    sensor = open_dht11(method=method)
    print(f"Reading the DHT11 on GPIO{DHT11_GPIO} with {sensor.method}. Ctrl+C to stop.")
    ok = failed = 0
    try:
        while True:
            r = sensor.read()
            if r.error:
                failed += 1
                print(f"{r.timestamp:%H:%M:%S}  failed: {r.error}")
            else:
                ok += 1
                print(f"{r.timestamp:%H:%M:%S}  {r.temperature_c:5.1f} °C  {r.humidity_percent:5.1f} %")
            time.sleep(2)
    except KeyboardInterrupt:
        print(f"\n{ok} good readings, {failed} failed")
    finally:
        sensor.close()
