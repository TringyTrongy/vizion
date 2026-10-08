---
version: 1
slug: "pi-web-index-html"
primary_target: "pi/web/index.html"
related_targets: ["pi/web/dashboard.css","pi/web/dashboard.js","pi/dashboard.py"]
---

## Scope

Full-screen Vizion dashboard (`pi/web/index.html`, served by `pi/dashboard.py`), shown in Chromium kiosk mode on the Pi's 27" 1920×1080 monitor; must also scale to a 1280×720 touchscreen. Visitor mode: **Operate** (an exhibit visitor reads state at a glance; an operator switches detection and learns the empty table).

## Audience, task, content, constraints

- Exhibit visitors 2–3 m away, seconds at a time; operator at arm's length with mouse, keyboard or touch.
- Live camera (610×480) with a box per tracked part; per part: designator, smoothed detector confidence, 3×3 zone (A1–C3 plus Top-Left … Bottom-Right); counts per class and total; PRESENT / NOT PRESENT per class; unrecognised-object state from the learned empty table; camera, detection and model status; time; detection switch; learn empty table; hold-to-exit.
- Offline, no build step, stdlib Python server; self-hosted font.

## Direction contract

THESIS: The dashboard is an electronics drawing sheet. Every part the camera finds is annotated like a schematic (R1, R2, C1), the camera is the drawing area with sheet zones A–C / 1–3, the pipeline is a block diagram whose switch S1 really is the detection control, and the title block carries time and status. It refuses the dark computer-vision HUD with neon boxes and glowing cards.

OWN-WORLD: Drafting film #f1f4f3 with a faint non-repro blue dot grid; navy drafting ink #1b2747 at ISO pen widths (0.25/0.35/0.5/0.7 mm become 1/1.5/2/3 px strokes); non-repro blue #a9c4d6 for construction lines; resistor ink #c2410c, capacitor ink #0f766e, red pen #9f1239 only for faults. All lettering in ISO 3098 (osifont) at pen weights; ruled tables, net-label flags, real schematic symbols (zigzag resistor, two-plate capacitor, SPST switch). No shadows, gradients, rounded cards or glows.

STORY: A visitor sees the camera picture with parts labelled R1 / C1 and big counts beside it, and understands at a glance what the machine sees, how many, where and how sure it is. Closer up, the block diagram shows the camera feeding the model through switch S1, and the notes state what it cannot do. The operator taps S1 to stop or start detection and teaches the empty table.

FIRST VIEWPORT: Whole sheet at 1920×1080. Left: zone rulers (1 2 3 across, A B C down) framing the camera at exactly 2× (1220×960), dashed non-repro thirds, boxes with keylines and flag labels. Under the camera: the NOTES line. Right column (600 px): block diagram CAMERA —S1— MODEL with S1 as the largest control (ON/OFF at 40 px); the parts list (BOM) with 96 px quantities, class symbols, PRESENT / NOT PRESENT and designators, the unrecognised row with Learn empty table, and TOTAL; the per-part table (REF, CONF, ZONE, LOCATION); the title block bottom-right with VIZION, the time at 48 px, date, model, threshold and hold-to-exit. Primary action: S1.

FORM: Schematic Sheet, rank 1 on my ordered list (shown as Impeccable's pick and chosen by the user); seed key c0d78278. Signature interaction: S1's lever swings closed or open and the wires downstream go live or fall back to dashed non-repro blue; each detection result sends one pulse along the live wire, so the pulse rate is the true detection rate.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved

- Touchscreen model not chosen yet; layout scales down to 1280×720 and stacks in portrait.
