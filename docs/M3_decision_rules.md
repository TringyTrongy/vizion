# M3 · Decision rule sheet

What Vizion decides, from which input, at what threshold, what it does, and what it does when something fails. Every value is taken from the code it names.

## Rules

| # | Input | Condition (threshold) | Debounce | Action | Code |
|---|---|---|---|---|---|
| R1 | Detector box, class *resistor* | tracked confidence ≥ **0.25** (`--conf`) | shown only after it is seen in **2 frames** (1 if ≥ 0.60); hidden below **0.15** or after **5 missed frames** | **Red LED D1 ON** (GPIO17, pin 11) while ≥ 1 resistor is shown | `pi/tracker.py`, `pi/leds.py`, `pi/dashboard.py` `_publish` |
| R2 | Detector box, class *capacitor* | same as R1 | same as R1 | **Yellow LED D2 ON** (GPIO27, pin 13) while ≥ 1 capacitor is shown | same |
| R3 | Counts on the table vs the expected kit (`--expect resistor=2,capacitor=2`) | counts equal the kit and no unrecognised object | follows R1/R2 (already debounced) | **PASS** on the station page, `KIT_PASS = 1` on the PLC, published on `vizion/detections` | `pi/station.py` `verdict` |
| R4 | Same | a part missing or extra, or an unrecognised object on the table | same | **FAIL** with the reason (e.g. `resistor 1/2`) | `pi/station.py` |
| R5 | Motor camera mismatch score (Vizion Motor) | score > learned limit | **3 frames in a row** | motor **stopped**, red LED, `ANOMALY` on `vizion/motor/score` | `pi/motor_monitor/motor_watch.py` |
| R6 | MPU6050 vibration window score | > threshold (normal p99.5 × 1.5) | **3 windows in a row** (1.5 s) | `ALERT` | `pi/mpu6050/mpu_anomaly.py` |

## Safe state when something fails

The rule: **without a fresh picture and a working model, nothing is ever reported as present or PASS.**

| Failure | Detected by | What the actuator does | Why |
|---|---|---|---|
| Camera unplugged / dead | `FrameGrabber` reports the camera dead; `Camera.poll` | **Both LEDs OFF**, parts list cleared, verdict **NO VERDICT**, PLC `VISION_OK = 0`, page shows "CAMERA LOST" | `_live_counts()` returns `None` when the camera state is not `ok`, and `leds.show(None)` turns every LED off |
| Camera frozen (no new picture for **3 s**) | `CAMERA_STALL_S = 3.0` | same as above (state `stalled`) | an old picture must not keep an LED lit |
| Camera recovers | reopened every **2 s** (`CAMERA_RETRY_S`) | LEDs follow detections again | automatic, no restart needed |
| Detector process crashes | `Model.poll` sees the process dead | LEDs OFF, NO VERDICT; restarted up to **3 times in 10 min**, then "failed" | `_live_counts()` needs `model.state == "ready"` |
| Detection switched off (S1 / key D) | operator | LEDs OFF | the operator asked for no decisions |
| MQTT broker down | `MqttLink` disconnect | detection and LEDs carry on locally; PLC bridge sets `VISION_OK = 0` after **3 s** of silence | the line must not trust a stale "present" |
| Whole service crashes | systemd `Restart=always` | back after about 2 s plus model load (measure with `pi/system/crash_test.sh`) | `pi/system/vizion-dashboard.service` |

## How to show it ("Break the camera" / "Send one bad frame")

1. **Break the camera:** with parts on the table (LEDs on), pull the webcam's USB. Within 3 s both LEDs go dark, the station page shows `CAMERA … · LEDs off (safe state)` and NO VERDICT. Plug it back in: within about 2 s detection resumes.
2. **One bad frame does not trigger:** `pi/test_tracker.py::test_single_frame_false_positive_not_shown` proves a box seen in a single frame is never shown. Live: flick a part through the view; the LED does not flash. Leave it for 2 frames (about 0.15 s at 15 fps) and the LED lights.
