"""The hardware Vizion Motor drives and watches: the SG90 servo, the two LEDs and the USB webcam.

On the Pi: lgpio for the servo (GPIO18, header pin 12) and the LEDs (red GPIO17 pin 11, yellow
GPIO27 pin 13), OpenCV for the webcam (/dev/video0). On a computer without them, or with
`--rig sim`, SimRig draws a servo arm that follows the commands, so the whole dashboard can be tried
and tested without the hardware. It is always labelled as simulated.
"""
import io
import math
import threading
import time

import numpy as np

SERVO_GPIO = 18  # header pin 12
RED_LED_GPIO = 17  # header pin 11
YELLOW_LED_GPIO = 27  # header pin 13
FRAME_W, FRAME_H = 610, 480  # the webcam pads columns 610–639 with green; they are cut off


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


# --- JPEG ----------------------------------------------------------------------------------------

try:
    import cv2
except ImportError:  # a computer without OpenCV: Pillow encodes instead
    cv2 = None


def encode_jpeg(bgr, quality=82):
    if cv2 is not None:
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes() if ok else None
    from PIL import Image
    out = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(bgr[..., ::-1])).save(out, "JPEG", quality=quality)
    return out.getvalue()


def decode_jpeg(data):
    if cv2 is not None:
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    from PIL import Image
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))[..., ::-1].copy()


def resize(bgr, w, h):
    if cv2 is not None:
        return cv2.resize(bgr, (w, h), interpolation=cv2.INTER_AREA)
    from PIL import Image
    return np.asarray(Image.fromarray(bgr[..., ::-1]).resize((w, h)))[..., ::-1].copy()


# --- Servo and LEDs ------------------------------------------------------------------------------

class GpioOutputs:
    """The servo and the two LEDs, through lgpio. An LED whose pin is busy is left out, with a note."""

    simulated = False

    def __init__(self, servo=SERVO_GPIO, leds=(("red", RED_LED_GPIO), ("yellow", YELLOW_LED_GPIO))):
        import lgpio  # only on the Pi

        self.lg = lgpio
        self.chip = open_header_chip(lgpio)
        self.servo_gpio = servo
        try:
            lgpio.gpio_claim_output(self.chip, servo, 0)
        except lgpio.error as e:
            lgpio.gpiochip_close(self.chip)
            raise RuntimeError(f"GPIO{servo} (the servo) is busy: is Vizion Sense running? ({e})") from e
        self.leds, self.lit = {}, {}
        self.note = None
        for name, gpio in leds:
            try:
                lgpio.gpio_claim_output(self.chip, gpio, 0)
                self.leds[name], self.lit[name] = gpio, False
            except lgpio.error:
                self.note = f"GPIO{gpio} is busy, so the LEDs are off. Is another Vizion dashboard running?"
        self.pulse = 0
        self.description = f"SG90 servo on GPIO{servo}"

    def servo(self, us):
        """Pulse width in µs, or 0 to stop the pulses (the arm goes limp and quiet)."""
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
    """Stands in for the GPIO where there is none: it remembers what it was told."""

    simulated = True

    def __init__(self, note="No GPIO here: the servo and LEDs are not driven"):
        self.note = note
        self.pulse = 0
        self.leds = {}
        self.lit = {"red": False, "yellow": False}
        self.description = "no servo"

    def servo(self, us):
        self.pulse = int(us or 0)

    def led(self, name, on):
        self.lit[name] = bool(on)

    def close(self):
        self.pulse = 0


def open_outputs(leds=True):
    led_pins = (("red", RED_LED_GPIO), ("yellow", YELLOW_LED_GPIO)) if leds else ()
    try:
        return GpioOutputs(SERVO_GPIO, led_pins)
    except ImportError:
        return NoOutputs()
    except Exception as e:  # no GPIO chip, pin busy...
        return NoOutputs(f"Servo not available: {e}")


# --- Camera --------------------------------------------------------------------------------------

class Webcam:
    """The USB webcam, read on its own thread. Reconnects every 2 s when it drops out."""

    simulated = False
    description = "USB webcam /dev/video0"

    def __init__(self, index=0):
        self.index = index
        self.cap = None
        self.note = None

    def _open(self):
        cap = cv2.VideoCapture(self.index, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if not cap.isOpened():
            cap.release()
            return None
        return cap

    def read(self):
        """The next frame (BGR, 480×610), or None when the camera is not there."""
        if self.cap is None:
            self.cap = self._open()
            if self.cap is None:
                self.note = "The webcam isn't answering. Is it plugged in, and is the camera dashboard closed?"
                time.sleep(2)
                return None
        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.cap.release()
            self.cap = None
            self.note = "The webcam stopped sending pictures; reconnecting."
            time.sleep(2)
            return None
        self.note = None
        return frame[:FRAME_H, :FRAME_W]

    def close(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None


# --- A simulated servo and camera ----------------------------------------------------------------

class SimRig:
    """A drawn servo arm that follows the pulses it is sent, seen by a drawn camera at about 8.5 fps.

    It is both the outputs (servo, LEDs) and the camera, so the dashboard and the tests run anywhere.
    Disturbances to try the detector: hold (a hand stops the arm), freeze (the arm stops with no hand,
    like a servo with no power), cover (something in front of the camera), nudge (push the arm 25°).
    """

    simulated = True
    description = "simulated servo and camera"
    note = "Simulated rig: a drawn arm, not the real servo"

    def __init__(self, fps=8.5, clock=time.monotonic, realtime=True, seed=1):
        self.fps = fps
        self.clock = clock
        self.realtime = realtime
        self.rng = np.random.default_rng(seed)
        self.pulse = 0
        self.leds = {"red": None, "yellow": None}
        self.lit = {"red": False, "yellow": False}
        self.angle = 0.0  # degrees, 0 = middle
        self.held = self.frozen = self.covered = False
        self.camera_off = False
        self._t = None
        self._next = None
        self.lock = threading.Lock()
        yy, xx = np.mgrid[0:FRAME_H, 0:FRAME_W]
        self._yy, self._xx = yy.astype(np.float32), xx.astype(np.float32)
        base = 200 - (yy / FRAME_H) * 40 + (xx / FRAME_W) * 12
        self._base = np.stack([base * 0.98, base, base * 1.02], axis=-1).astype(np.float32)
        self._noise = [self.rng.normal(0, 2.0, self._base.shape).astype(np.float32) for _ in range(7)]
        self._frames = 0

    # outputs
    def servo(self, us):
        self.pulse = int(us or 0)

    def led(self, name, on):
        self.lit[name] = bool(on)

    def close(self):
        self.pulse = 0

    # disturbances
    def disturb(self, action):
        with self.lock:
            if action == "hold":
                self.held = True
            elif action == "release":
                self.held = self.frozen = False
            elif action == "freeze":
                self.frozen = True
            elif action == "cover":
                self.covered = True
            elif action == "uncover":
                self.covered = False
            elif action == "nudge":
                self.angle = max(-80.0, min(80.0, self.angle + 25.0))
            else:
                raise ValueError(f"unknown disturbance {action!r}")

    def _move(self, t):
        if self._t is None:
            self._t = t
        dt, self._t = t - self._t, t
        if self.pulse and not (self.held or self.frozen):
            target = (self.pulse - 1500) * 0.09
            step = (target - self.angle) * (1 - math.exp(-dt / 0.12))
            limit = 450.0 * dt  # the SG90 turns about 60° in 0.1 s unloaded
            self.angle += max(-limit, min(limit, step))

    def frame_at(self, t):
        """Draw the camera's view at time t (BGR uint8, 480×610)."""
        with self.lock:
            self._move(t)
            img = self._base.copy()
            # servo body
            img[300:420, 230:380] = (190, 90, 20)
            img[280:300, 280:330] = (200, 110, 40)
            # the arm, seen from above: a cross-shaped horn turning about (305, 260)
            cx, cy = 305.0, 260.0
            for offset, length, width in ((0, 95, 13), (90, 40, 11)):
                a = math.radians(self.angle + offset)
                dx, dy = math.cos(a), math.sin(a)
                px, py = self._xx - cx, self._yy - cy
                along = px * dx + py * dy
                across = np.abs(-px * dy + py * dx)
                mask = (np.abs(along) <= length) & (across <= width / 2)
                img[mask] = (245, 245, 245)
            if self.held:  # a hand over the arm
                hand = ((self._xx - (cx + 70)) / 120) ** 2 + ((self._yy - (cy - 10)) / 70) ** 2 < 1
                img[hand] = (95, 120, 170)
            if self.covered:  # a hand over the lens: the arm is gone, only a dark smudge is left
                img[:] = (40, 52, 70)
            img += self._noise[self._frames % len(self._noise)]  # camera noise
            self._frames += 1
            return np.clip(img, 0, 255).astype(np.uint8)

    def read(self):
        """Like Webcam.read: the next frame, paced at the rig's frame rate when realtime."""
        if self.camera_off:
            time.sleep(0.2)
            return None
        if self.realtime:
            now = self.clock()
            if self._next is None:
                self._next = now
            self._next += 1.0 / self.fps
            wait = self._next - now
            if wait > 0:
                time.sleep(wait)
            else:
                self._next = now
        return self.frame_at(self.clock())
