# Product

<!-- impeccable:product-schema 1 -->

Vizion Motor: the product record for `pi/motor_monitor/`. It is app-specific. The root PRODUCT.md and DESIGN.md describe the Vizion camera dashboard (`pi/web/`), and Vizion Sense (`pi/sensor_monitor/`) keeps its decisions in its surface brief. Neither of them is changed by this app.

## Platform

web

## Users

- **Mentor / evaluator at Forge (primary):** reviews the motor anomaly assignment. The user demos it to them at a desk, at arm's length, on the Pi's monitor or a laptop browser. The evaluator may reach out and stop the servo arm themselves to see what happens.
- **The user (builder and presenter):** a learner who built it and explains it during the demo. They start it, set up the camera and servo, run the calibration and reset it after an anomaly.

## Product Purpose

The assignment is to detect anomalies with the motor as the main focus, and to react to them. The motor is an SG90 hobby servo, which has no feedback wire, so the Pi cannot ask it where it is. Vizion Motor closes that loop with the webcam. The Pi commands a known movement, the camera watches the servo arm, and the dashboard compares the two. When the arm does not do what it was told, for example because it is held, blocked or unpowered, Vizion Motor flags an anomaly, says why in plain words and reacts by stopping the servo.

Success: in a live demo, the evaluator stops the arm by hand. Within a couple of seconds the dashboard shows the anomaly and its reason, the servo stops being driven and the red LED flashes. After Restart the arm sweeps again. The event is in the log and can be exported.

## Positioning

Vizion Motor detects anomalies on an open-loop motor without adding any sensor. It compares what the motor was told to do with what the camera saw it do, and every state traces back to one of those two signals. An anomaly means the arm did not follow its command. It is never presented as proof that the motor has failed.

## Operating Context

- Raspberry Pi 5 (4 GB, Debian 13, labwc/Wayland), 1920×1080 monitor; full-screen Chromium kiosk like the other Vizion dashboards, and reachable from a laptop browser.
- Servo: Tower Pro SG90 on GPIO18 (header pin 12), powered from the Pi's 5 V (pin 4), ground pin 20. It turns about 180° in total. The other Vizion dashboards sweep it ±40° (1500 ± 450 µs).
- LEDs: red on GPIO17 (pin 11), yellow on GPIO27 (pin 13).
- Camera: Arkmicro USB webcam (`/dev/video0`), 610×480 usable, about 8.5 fps in the current room light, with auto exposure that cannot be locked. Since 2026-10-10 it points at the servo from the side, at table height, about 15–25 cm away. The arm is a white cross-shaped horn above the blue servo body.
- Shared hardware: only one program can open the camera, so Vizion Motor and the camera dashboard cannot run at the same time. Vizion Sense drives the same servo and LEDs, so it cannot run at the same time as Vizion Motor either.

## Capabilities and Constraints

- **Signals that were measured and do not work:**
  - The Pi's 5 V reading (EXT5V_V) stayed at 5.143 V whether the servo was off, holding or reversing flat out, so it can't show motor load.
  - The webcam microphone's levels in every band from 20 Hz to 8 kHz were the same with the servo quiet and sweeping, at two distances (2026-10-10), so room noise hides the servo.
- **Signal that works:** the camera. During a sweep the only part of the picture that changed was the arm (measured 2026-10-10).
- **Detection approach** (the user left the choice to the builder): compare the commanded movement with the arm's observed movement in the camera, against a baseline learned from a calibration run of normal sweeps. These cases are told apart:
  - the arm doesn't move while commanded to (held, blocked or unpowered);
  - the arm moves while commanded to stay still (pushed);
  - the camera can't see the arm (view blocked, camera moved, too dark). This is reported as not being able to see, not as a motor anomaly.
- **Reaction:**
  - stop driving the servo (no pulses, so the arm goes limp and isn't strained);
  - flash the red LED;
  - keep the yellow LED on while it runs normally;
  - the shutdown is latched until Restart.
- **Record:** an event log of anomalies, with time, type and reason, and readings exportable as CSV.
- **Not decided or not verified yet:**
  - The hold test, which checks whether a hand-held arm is reliably told apart from normal motion with the current side view, has not been run.
  - Whether a coloured marker on the arm or a top-down camera view is needed.
  - The exact time to react.
- **No trained neural model.** Using machine learning was not a requirement, so the baseline is learned from calibration data.

## Brand Commitments

- Name: **Vizion Motor**, chosen by the user on 2026-10-10. It belongs to the same family as Vizion (camera) and Vizion Sense (DHT11). There is no logo.
- Copy says "servo" or "motor" and "arm", and calls a mismatch an "anomaly", never a "failure" or "fault" of the motor.

## Evidence on Hand

- The measurements above: the EXT5V_V test, the microphone recordings at two distances, and the camera motion map showing the arm as the only moving region (all 2026-10-10, from the probe script run on the Pi).
- No recorded anomaly data, results or accuracy figures exist yet. Do not invent detection rates, response times or test results before they are measured on the Pi.

## Product Principles

1. **Command versus camera:** every state on screen traces to what the servo was told or what the camera saw.
2. **A mismatch, not a diagnosis:** say what didn't match and the likely causes, never that the motor is broken.
3. **React first, then explain:** stop driving the servo as soon as the anomaly is confirmed, then show why.
4. **Demo by hand:** the evaluator must be able to cause an anomaly and clear it themselves, at a desk, in under a minute.
5. **Say what it can't see:** a blocked or moved camera, poor light, or a missing calibration is stated plainly and never shown as normal.

## Accessibility & Inclusion

- State is never shown by colour alone: a word plus form.
- Keyboard shortcuts for every control; large touch targets.
- Respect reduced motion.
