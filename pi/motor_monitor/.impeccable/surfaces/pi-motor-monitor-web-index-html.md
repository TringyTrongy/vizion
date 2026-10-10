---
version: 1
slug: "pi-motor-monitor-web-index-html"
primary_target: "pi/motor_monitor/web/index.html"
related_targets: ["pi/motor_monitor/web/motor.css","pi/motor_monitor/web/motor.js","pi/motor_monitor/motor_dashboard.py"]
---

## Scope

Vizion Motor: the servo-arm anomaly dashboard (`pi/motor_monitor/web/index.html`, served by `pi/motor_monitor/motor_dashboard.py` on port 8767). Shown full screen in Chromium kiosk on the Pi's 1920×1080 monitor (`?kiosk`), and in a laptop browser (`--host 0.0.0.0`). Visitor mode: Operate. A separate surface from the camera dashboard (`pi/web/`, Schematic Sheet, root DESIGN.md) and Vizion Sense (`pi/sensor_monitor/web/`, Portfolio Monochrome); it shares neither design system.

## Audience, task, content, constraints

- A mentor or evaluator at Forge, with the user demoing at a desk; the evaluator may stop the arm by hand. The user is a learner who starts it, runs Learn normal, and restarts it after a trip.
- Content: run state (NOT LEARNED / LEARNING / WATCHING / ANOMALY / STOPPED / NO CAMERA), the reason sentence, the expected (master) and live pictures of the arm, the mismatch score against its learned limit, the commanded versus seen arm angle, the frame rate, counts, a trend of the mismatch, and the history of anomalies with their held frames. Controls: Learn normal, Start / Stop, Restart, Export CSV, hold to exit in kiosk.
- The user approved this first-view content on 2026-10-10: the big status, the live camera next to the picture it expected at that moment, the mismatch with its limit, and the controls.
- Offline, no build step, stdlib server, self-hosted fonts. The Pi 5 also runs the camera loop and the matching, so the page stays light: no blur, no canvas animation beyond the trend chart.

## Direction contract

THESIS: Every camera frame is an inspection of the servo arm against its master images. One judgement lamp says OK or ANOMALY, beside the box and the score that decided it. It refuses the category default of a dark grid of monitoring panels with KPI tiles.

OWN-WORLD: A light machine-vision panel:
- **Ground and ink:** panel grey #e7e9ea; navy #1d2a3a title bars and ink; white image wells with a 1px navy keyline; square corners; flat.
- **State colours:** green #2fa84f and red #d6262b appear only where a judgement is shown: the lamp, the region box and its tool tag, the judgement cells and history chips, the match bar once it passes the limit (navy below it), and the anomaly evidence (the held panes' frames, the HELD FRAME stamp, and trip marks on the trends). Cyan #00a0e9 marks inspection overlays and selection.
- **Type:** Barlow. Condensed for the lamp, the keys and the field names, regular for text, tabular figures throughout.
- **Keys:** rectangular HMI keys, which invert to navy when pressed.

STORY:
1. From across the desk, the lamp reads OK in green while the arm sweeps, and the EXPECTED and LIVE panes match frame by frame.
2. The evaluator grabs the arm. Within a third of a second the lamp turns red and reads ANOMALY, the box turns red, both panes freeze on the frame that tripped it, the servo goes limp and the red LED flashes.
3. The presenter points at the score that crossed the limit and presses Restart.

FIRST VIEWPORT (1920×1080, no scroll):
- **Title bar (navy):** the name, the RUN / SETUP mode, the clock, Export CSV, and exit.
- **Left 62%:** two image panes side by side, EXPECTED (the master at the commanded angle) and LIVE, with the arm region boxed and a tool tag "01 ARM MATCH".
- **Right 38%:**
  - the judgement lamp, its word set as large as ANOMALY fits the 38% column (11rem, about 125px cap height);
  - the reason sentence;
  - the match bar, with a limit tick and numbers;
  - the keys: LEARN NORMAL, START / STOP, RESTART.
- **Under the panes:** a one-line frame strip (the frame being inspected) that becomes the HELD FRAME stamp after a trip, in a reserved slot so nothing moves.
- **Bottom band:** the tool results table with the counts as a ruled table row, a 60 s trend of the mismatch with its limit line, and the inspection history.
- **Laptop and phone:** on laptops the tools table moves under the panes; in one column the order is the lamp, the two panes, the reason, the meter, the keys, then the results.
- **Signature:** the trip. The lamp, the box and the panes switch in the same frame, and the panes hold the evidence under a HELD FRAME stamp.
- **Motion grammar:** state changes are instant, like a real panel. Only live data moves: the bar and the trend update at the frame rate. Learning fills a segmented bar.

FORM: Vision Inspection Station. It was my own top-ranked grounded candidate (1 of 7), and the user chose it as IMPECCABLE'S PICK over the rolled Bench Oscilloscope. Seed key 4f995c05.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

## Unresolved

- The limit (a floor of 0.15 and 4× the 99th percentile of normal) held on the Pi's first Learn normal (normal p99 0.0043, 10 Oct 2026), but a hand on the arm has not yet been tried through the dashboard on real hardware.
- Finished 10 Oct 2026: the finish review shipped after two fix rounds and a recapture, and this surface's system is recorded in its own `pi/motor_monitor/DESIGN.md` (the root DESIGN.md stays the camera dashboard's).
