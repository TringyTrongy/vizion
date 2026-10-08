# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated: plain HTML, CSS and JavaScript served by a small Python server that uses only the standard library, shown full-screen in Chromium kiosk mode on the Raspberry Pi's own monitor. No new Python packages, no build step, no CDN at runtime (the Pi must work offline). Chosen because the Pi already runs the camera, detector and tracker in Python, and the user asked for no unnecessary dependencies.

## Users

- **Exhibit visitors (primary):** people who walk up to the Vizion stand and watch it identify resistors and capacitors. They read the screen from 2–3 m away, for seconds at a time, often without anyone explaining it.
- **Operator:** the person running the stand. Launches it with `./run_dashboard.sh`, places parts under the camera, turns detection on and off, and teaches it the empty table. Uses a mouse, keyboard or touchscreen; never a terminal during normal use.

## Product Purpose

Vizion is a Raspberry Pi 5 with a USB webcam that finds resistors and capacitors on a table in real time, using a YOLO26n model trained for this camera and exported to NCNN. The dashboard makes that visible: the live camera with a box around each part, how many of each are present, where they are, and how confident the model is. Success: a visitor understands within seconds what the machine is seeing and how sure it is, and the operator never has to touch a terminal.

## Positioning

Everything runs on the Pi's CPU: no cloud, no AI accelerator. The model was trained on public datasets plus frames from this exact webcam, and only knows two classes. The dashboard reports what that model actually measures (detector confidence, box position, tracked counts) and never invents a value or names an object it cannot recognise.

## Operating Context

- Raspberry Pi 5 (4 GB), Debian 13, labwc/Wayland desktop, BenQ EW2775ZH 27" monitor at 1920×1080 over HDMI (not a touchscreen today; a touchscreen may be added).
- Camera: Arkmicro USB webcam, 610×480 usable after cropping its padded edge, about 8–17 fps depending on light (its auto-exposure cannot be locked).
- Pipeline (existing, reused): camera grabber thread → detector in a separate process (NCNN, about 50 ms per frame on 3 cores) → tracker that smooths boxes and counts each physical part once.
- The table and lighting change between venues; very bright light lowers detection confidence, so the display threshold is 0.25 by default and configurable.

## Capabilities and Constraints

- Classes: resistor and capacitor only (all capacitor types are one class). Boxes cover the part's body, not its leads.
- Per part: smoothed detector confidence (0–100%), box in pixels, and its cell in a 3×3 grid (Top-Left … Bottom-Right).
- Counts per class and in total, from tracked parts, not per-frame boxes.
- Presence per class: PRESENT / NOT PRESENT.
- Unrecognised objects: compared against a learned picture of the empty table. Anything that differs from it and is not a detected resistor or capacitor counts as an unrecognised object. It is never named, needs re-learning when the camera, table or lighting changes, and is shown as unavailable until learned.
- Status: camera connected or lost, detection on or off, model loading, ready or failed, and a lost connection to the Vizion service. Failures show on screen and recover automatically where possible.
- Detection can be switched off without stopping the camera.
- The NCNN model files are never edited; no retraining as part of the dashboard.
- Performance: the detector process keeps its own cores; the UI must not block or add jitter.

## Brand Commitments

- Name: Vizion (header wordmark). No logo exists.
- Copy says "resistor" and "capacitor" exactly, and "confidence" for the detector score.

## Evidence on Hand

- Model card with measured results: `captures/model/README.md` (public test mAP50 0.938 at 480 px; 52 of 52 labelled webcam parts found; 0 false boxes on 11 empty room frames).
- Real webcam frames: `captures/capture_*.jpg`, `data/webcam/raw/`.
- No customers, testimonials or benchmarks beyond the model card. Do not invent any.

## Product Principles

1. Show what the model measured, never more: every number on screen traces to the detector, tracker or camera.
2. Legible from 3 m: the important state (what is there, how many) reads at a glance; detail is secondary.
3. The camera never stops for the UI: detection, failures and the dashboard all degrade without freezing the picture.
4. Say what it cannot do: limits (unknown objects, untrained lighting) are stated plainly on screen, not hidden.

## Accessibility & Inclusion

- Readable at 2–3 m: large type, high contrast, status never conveyed by colour alone.
- Touch-ready controls (large targets) even on a mouse-driven monitor; keyboard shortcuts for every control.
- Respect reduced motion.
