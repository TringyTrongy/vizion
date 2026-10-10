---
name: Vizion Motor
description: A light machine-vision inspection panel that judges a servo arm OK or ANOMALY, frame by frame.
colors:
  panel: "#e7e9ea"
  panel-2: "#d9dee2"
  well: "#ffffff"
  navy: "#1d2a3a"
  navy-raised: "#2c3e53"
  title-keyline: "#6c7d8f"
  title-text: "#c3cdd7"
  ink-2: "#3b4a5b"
  ink-3: "#56626f"
  rule: "#b6bfc7"
  ok: "#2fa84f"
  ok-deep: "#1d8139"
  ok-tint: "#dcf0e1"
  ng: "#d6262b"
  ng-tint: "#f9dedf"
  cyan: "#00a0e9"
  cyan-deep: "#00689a"
  idle: "#56616b"
typography:
  lamp:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "11rem"
    fontWeight: 700
    lineHeight: 0.86
    letterSpacing: "0.01em"
  wordmark:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "1.625rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.12em"
  readout:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "2.5rem"
    fontWeight: 600
    lineHeight: 1
    fontFeature: "tnum"
  key:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.06em"
  pane-name:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.12em"
  field:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.08em"
  column-head:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "0.08em"
  reason:
    fontFamily: "Barlow, Segoe UI, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 500
    lineHeight: 1.35
    fontFeature: "tnum"
  body:
    fontFamily: "Barlow, Segoe UI, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 500
    lineHeight: 1.3
    fontFeature: "tnum"
  note:
    fontFamily: "Barlow, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 500
    lineHeight: 1.35
    fontFeature: "tnum"
rounded:
  none: "0px"
spacing:
  gap: "20px"
  gap-phone: "14px"
  edge: "24px"
  edge-phone: "16px"
  pane-gap: "16px"
  key-gap: "12px"
  cell: "6px 10px"
  title-bar: "64px"
components:
  key:
    backgroundColor: "{colors.well}"
    textColor: "{colors.navy}"
    typography: "{typography.key}"
    rounded: "{rounded.none}"
    padding: "0 22px"
    height: "64px"
  key-hover:
    backgroundColor: "{colors.panel-2}"
  key-pressed:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.well}"
  key-primary:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.well}"
    typography: "{typography.key}"
    rounded: "{rounded.none}"
    padding: "0 22px"
    height: "64px"
  key-primary-hover:
    backgroundColor: "{colors.navy-raised}"
  key-disabled:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
  key-dark:
    backgroundColor: "transparent"
    textColor: "{colors.well}"
    rounded: "{rounded.none}"
    padding: "0 14px"
    height: "40px"
  key-small:
    backgroundColor: "{colors.well}"
    textColor: "{colors.navy}"
    rounded: "{rounded.none}"
    padding: "0 12px"
    height: "40px"
  title-bar:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.well}"
    typography: "{typography.wordmark}"
    padding: "0 24px"
    height: "{spacing.title-bar}"
  mode-on:
    backgroundColor: "{colors.well}"
    textColor: "{colors.navy}"
    typography: "{typography.field}"
    padding: "8px 14px"
  lamp-ok:
    backgroundColor: "{colors.ok-deep}"
    textColor: "{colors.well}"
    typography: "{typography.lamp}"
    rounded: "{rounded.none}"
  lamp-anomaly:
    backgroundColor: "{colors.ng}"
    textColor: "{colors.well}"
    typography: "{typography.lamp}"
    rounded: "{rounded.none}"
  lamp-stopped:
    backgroundColor: "{colors.idle}"
    textColor: "{colors.well}"
  lamp-learning:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.well}"
  lamp-not-learned:
    backgroundColor: "{colors.well}"
    textColor: "{colors.navy}"
  pane-caption:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.well}"
    typography: "{typography.pane-name}"
    padding: "9px 12px 8px"
  tool-tag:
    backgroundColor: "{colors.cyan}"
    textColor: "{colors.well}"
    padding: "3px 7px 2px"
  window-head:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.navy}"
    typography: "{typography.field}"
    padding: "9px 12px 8px"
  judge-ok:
    backgroundColor: "{colors.ok-tint}"
    textColor: "{colors.ok-deep}"
    padding: "4px 8px 3px"
  judge-anomaly:
    backgroundColor: "{colors.ng}"
    textColor: "{colors.well}"
    padding: "4px 8px 3px"
  judge-info:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-2}"
    padding: "4px 8px 3px"
  match-fill:
    backgroundColor: "{colors.navy}"
    height: "28px"
  match-fill-over:
    backgroundColor: "{colors.ng}"
    height: "28px"
---

# Design System: Vizion Motor

> **Scope.** This system covers the Vizion Motor dashboard only (`pi/motor_monitor/web/`). The root `DESIGN.md` belongs to the camera dashboard ("Schematic Sheet") and does not apply here; neither does this file apply there.

## Overview

**Creative North Star: "The Vision Inspection Station"**

Vizion Motor reads like the operator panel of an industrial machine-vision sensor: a light grey panel, navy title bars, white image wells, and one judgement lamp. Every camera frame is an inspection of the servo arm against its master image, and the screen is arranged so the verdict, the evidence that decided it, and the score sit side by side. It is legible from across a desk: the lamp word is set as large as ANOMALY fits its column, the keys are 64px rectangles, and every number uses tabular figures.

The panel is flat and square. Depth comes only from navy keylines and the change from panel grey to white wells; there are no shadows, no radius, no blur. Colour is rationed: navy carries structure and ink, cyan marks what the inspection tool is looking at, and green and red appear only where a judgement is being shown. That rationing is what lets a trip read instantly: when the arm is grabbed, the lamp, the region box, both pane frames and the HELD FRAME stamp go red in the same frame, and nothing else on the screen is red to compete.

It behaves like hardware. State changes are instant; only live data (the match bar, the trends, the clock) moves. The kiosk view fits one 1920×1080 screen without scrolling.

**Key Characteristics:**
- Light panel grey ground, navy title bars and ink, white image wells with 1px navy keylines.
- Square corners everywhere (0px); flat, no shadows.
- Green and red reserved for judgements; cyan for inspection overlays, selection and focus.
- Barlow Condensed for the lamp, keys, field names and readouts; Barlow for sentences; tabular figures throughout.
- Rectangular HMI keys that invert to navy when pressed.
- Instant state changes; only live data moves.

## Colors

A cool, low-chroma instrument palette of greys and navy, with three saturated signal colours that each have one job.

### Primary
- **Panel Navy** (`navy`): title bars, pane captions, keylines around wells and windows, primary key fill, the match bar below the limit, the limit line and limit tick, and all primary ink. It is the structure of the panel.
- **Raised Navy** (`navy-raised`): hover on navy keys (primary key, title-bar keys). Hover only.

### Secondary
- **Judgement Green** (`ok`): the region box when OK, the OK judgement-cell border. **Deep Judgement Green** (`ok-deep`): the OK lamp face (white lettering at 4.6:1), the OK tool tag, OK cell text. **Green Tint** (`ok-tint`): the OK cell fill.
- **Anomaly Red** (`ng`): the ANOMALY lamp face, the region box and tool tag on a trip, the 3px pane frames while held, the HELD FRAME stamp border and label, the ANOMALY judgement cell and history chip, the match bar once it passes the limit, and trip marks on the trends (line plus a 12% red band). **Red Tint** (`ng-tint`) is defined for anomaly fills.

### Tertiary
- **Inspection Cyan** (`cyan`): the region box at rest (no judgement yet), the tool tag at rest, the learning progress segments, the "seen by the camera" trace, `:focus-visible` outlines (3px, 2px offset), text selection (25% cyan), and the dashed SIMULATED RIG tag in the title bar. **Deep Cyan** (`cyan-deep`): cyan used as text on white.

### Neutral
- **Panel Grey** (`panel`): page ground, the empty match-bar track, INFO cells.
- **Window Strip Grey** (`panel-2`): window title strips (Inspection tools, trends, history), key hover.
- **Well White** (`well`): image wells, tables, keys, the lamp bezel, and all lettering on navy, red and green.
- **Secondary Ink** (`ink-2`): field names, column heads, notes, times (8:1 on the panel).
- **Quiet Ink** (`ink-3`): empty-state text, disabled keys, axis labels (5:1 on the panel).
- **Rule Grey** (`rule`): table row rules, chart gridlines, the idle frame-strip border, scrollbars.
- **Idle Slate** (`idle`): the STOPPED lamp face.
- **Title Keyline** (`title-keyline`) and **Title Lettering** (`title-text`): borders of keys and the mode switch on the navy bar, and quiet lettering on navy (pane notes, subject line, learning text).

### Named Rules
**The Judgement-Only Rule.** Green and red appear only where a judgement is shown: the lamp, the region box and its tool tag, judgement cells and history chips, the match bar past its limit, and the anomaly evidence (held pane frames, HELD FRAME stamp, trend trip marks). Never as decoration, branding, or a generic success/error colour for UI chrome.

**The Navy-Below-Limit Rule.** A measurement is navy until it crosses its limit. The match bar fills navy and turns red only past the limit; it is never green, because a value is not a judgement.

**The Cyan-Looks Rule.** Cyan means "the tool is looking here": overlays, selection, focus, and what the camera saw. It never carries a verdict.

## Typography

**Display Font:** Barlow Condensed (with Arial Narrow, sans-serif), weights 500/600/700, self-hosted woff2, `font-display: block`.
**Body Font:** Barlow (with Segoe UI, sans-serif), weights 400/500/600, self-hosted woff2.

**Character:** An industrial grotesque pair. The condensed cut does the machine's speaking (the lamp, keys, field names, readouts) in uppercase with open tracking; the regular cut carries the plain sentences a person reads. `font-variant-numeric: tabular-nums` is set on the body so every figure in the panel holds its column.

### Hierarchy
- **Lamp** (Condensed 700, 11rem kiosk / 8.5rem laptop / 5.5rem phone, line-height 0.86, uppercase): the judgement word only. Steps down for longer words (`m` 8.25rem, `s` 6.5rem at kiosk; LEARNING 7rem) so the word never wraps.
- **Readout** (Condensed 600, 2.5rem): the live mismatch value. The clock uses Condensed 600 at 1.625rem.
- **Wordmark** (Condensed 700, 1.625rem, 0.12em, uppercase): the product name on the title bar.
- **Key** (Condensed 600, 1.375rem, 0.06em, uppercase): HMI key labels; 1.0625rem on title-bar keys, 1rem/0.9375rem on small simulator keys.
- **Pane name** (Condensed 700, 1.25rem, 0.12em, uppercase): EXPECTED / LIVE. The frame-strip label (FRAME / HELD FRAME) is Condensed 700 at 1.125rem, 0.1em.
- **Field** (Condensed 600, 0.9375rem, 0.08em, uppercase): field names and window titles (Mismatch, Inspection tools, Inspection history, Simulator).
- **Column head** (Condensed 600, 0.8125rem, 0.08em, uppercase): table headers, counts headers.
- **Reason** (Barlow 500, 1.25rem, 1.35, max 60ch, reserved 4.05em height): the sentence that explains the current state.
- **Body** (Barlow 500, 1.0625rem, 1.3): table cells, frame-strip text, empty wells.
- **Note** (Barlow 500, 0.9375rem, 1.35): rule notes, learned line, history text, match note.

### Named Rules
**The Two-Voice Rule.** Condensed uppercase is the machine labelling and judging; regular sentence case is the machine explaining to a person. Sentences are never set in condensed caps, and labels are never set in sentence case.

**The Tabular Rule.** Every figure is tabular. Numbers that update at the frame rate must not shift their neighbours.

## Layout

A fixed inspection-station grid with a 20px gap (`gap`) and 24px edges (`edge`), under a 64px navy title bar.

- **Kiosk (≥1600px wide and ≥900px tall):** one screen, no scroll (`body` is 100vh, overflow hidden). A four-column grid (31fr 31fr 10fr 28fr) with areas `images images judge judge` over `tools trends trends history`, so the image panes take 62% and the judgement column 38%; below, tools 31%, trends 41%, history 28%. The two panes sit side by side (16px gap) with the frame strip spanning under both. Trends stretch to fill the remaining height.
- **Laptop (<1600px wide or <900px tall):** two self-flowing columns, 62fr / 38fr. Left: panes, frame strip, tools table, trends. Right: lamp, reason, meter, keys, simulator, then the history filling the rest of the column (min 320px) so neither side leaves a hole. The page scrolls; the subject line in the title bar is dropped.
- **Single column (≤1180px):** in order: lamp, the two panes (still side by side) and strip, reason, meter, keys, key error, simulator, tools, trends, history.
- **Phone (≤700px):** gap 14px, edges 16px; the title bar wraps with the mode switch on its own row; keys stack one per row at 56px; the simulator is three across; pane captions stack name over note; the frame strip wraps to two lines; the tool tag drops to 0.75rem with no truncation.

**The Reserved Slot Rule.** Anything that changes on a trip occupies a slot that already exists. The frame strip is always one line under the panes and becomes HELD FRAME in place; the reason keeps a reserved 4.05em height; the lamp word steps down a size instead of wrapping. Nothing moves when the station trips.

## Elevation & Depth

Flat. There are no shadows anywhere. Depth is conveyed by tone and line: panel grey ground, white wells and windows, a 1px navy keyline around each well and window, a `panel-2` strip heading each window, and a 2px navy bezel with 6px inset around the lamp face. The only overlay, the lost-connection screen, is a 94% panel-grey veil over the page, not a floating card.

**The Keyline Rule.** Separation is drawn with a line, never cast with a shadow: 1px navy for wells and windows, 1px rule-grey inside tables, 2px navy for keys and the lamp bezel, 3px red for held panes.

## Shapes

Square corners throughout (0px). Rectangles only: wells at 4:3, keys, cells, the lamp face. Borders carry meaning by weight and style: solid for live and active things, **dashed** for not-yet or unavailable things (disabled keys, the NOT LEARNED lamp's inset outline, the "learned" history chip, the key-error box, the simulator divider, the SIMULATED RIG tag, the commanded-angle trace and the limit line). Hatching (a 45° stripe) marks absence: empty wells and the NO CAMERA lamp face.

## Components

### Keys (HMI buttons)
Rectangular, confident, and physical.
- **Shape:** square (0px), 2px navy border, 64px min height, 22px side padding, Condensed 600 uppercase. A keyboard shortcut sits inside in a 1px `currentColor` box at 70% opacity.
- **Default:** white face, navy lettering. **Primary** (the action the state calls for, e.g. RESTART after a trip): navy face, white lettering.
- **Hover:** `panel-2` (primary: `navy-raised`). **Pressed:** inverts to navy with white lettering (`:active`, and a 160ms `.pressed` flash when triggered from the keyboard). Background and colour transition over 150ms ease-out; no transition under reduced motion.
- **Disabled:** transparent, dashed `ink-3` border, `ink-3` lettering.
- **Title-bar keys:** 40px, transparent with a 1px `title-keyline` border and white lettering; hover `navy-raised`, pressed inverts to white. **Small keys** (simulator): 40px, 1px border.
- **Hold to exit (kiosk):** a title-bar key whose white fill scales left to right over 1000ms linear while held, with the label in `mix-blend-mode: difference`; releasing early cancels and snaps back.

### Title bar
Navy, 64px. Wordmark, subject line, a RUN / SETUP segmented mode switch (1px `title-keyline` frame; the active mode is a white cell with navy lettering, the inactive one `#8fa1b3` lettering), a dashed cyan SIMULATED RIG tag when the rig is simulated, then the clock, Export CSV (with a square white drop menu, 2px navy border, rule-separated rows), and hold-to-exit in kiosk.

### Judgement lamp (signature)
A 2px navy bezel with 6px white inset around a solid face. One word, white, Condensed 700.
- **WATCHING → OK:** `ok-deep` face. **ANOMALY:** `ng` face. **STOPPED:** `idle` face. **LEARNING:** navy face with a 32-segment progress bar (cyan segments over 18% white) and a progress line. **NOT LEARNED:** white face, navy word, 2px dashed navy outline inset 8px. **NO CAMERA:** dark slate with white hatching.
- Changes instantly. The lamp word steps through three sizes by word length so it never wraps.

### Image panes, ROI box and tool tag
Two figures, EXPECTED and LIVE: a navy caption strip (pane name left, quiet note right) over a 4:3 white well with a 1px navy keyline. Empty wells show hatching and a centred quiet sentence.
- **ROI box:** 2px cyan with a 1px white outline for contrast on any picture; 2px `ok` when judged OK; 3px `ng` on a trip.
- **Tool tag:** a solid label sitting on the box's top edge ("01 ARM MATCH 0.00 / 0.15 OK"), Condensed 600 0.875rem uppercase on cyan, `ok-deep` or `ng` to match the box; flips under the top edge when the box is near the top of the frame. Truncates at 280px on large screens; short and untruncated on phones.
- **On a trip:** both pane frames become 3px red and the panes hold the frame that tripped.

### Frame strip / HELD FRAME
One line under the panes, always present: a white strip with a 2px rule border, a Condensed label (FRAME 473) and a sentence. After a trip the border and label turn red and the label reads HELD FRAME, in the same slot.

### Match bar (meter)
A white window with 1px navy keyline: "Mismatch" field name and the live value (Condensed 2.5rem) with "limit 0.150" beside it; a 28px track (panel grey, navy border) whose fill is navy below the limit and red past it; the limit tick is a 2px navy line at the track's midpoint (the scale runs to twice the limit) labelled LIMIT; a quiet note underneath. While re-learning, no old limit is shown.

### Results table
A ruled table in a white window with a `panel-2` caption strip: No. / Tool / Measured / Against / Judgement. Rows are separated by 1px rule lines; the number column is Condensed. Judgement cells are fixed-width chips (min 5.6em, Condensed 700 uppercase): OK (green tint, green border, deep-green text), ANOMALY (solid red, white text), INFO (panel grey, rule border), and a dashed-navy variant for low confidence.

### Counts table
Not KPI tiles: a single ruled row inside the tools window (fixed layout, 1px rule frame and dividers) with small Condensed column heads (Inspected, Over limit, Anomalies, Sweeps) over Barlow 600 tabular values.

### Trends
Two stacked charts in one window (mismatch on a log scale, then arm angle), each with a `panel-2` caption strip. Rule-grey gridlines; a dashed navy limit line labelled LIMIT; the mismatch trace in 1.5px navy; points over the limit in red; trips as a red line over a 12% red band; the commanded angle as a dashed navy trace and the seen angle as a 2.5px cyan trace; a faint navy band marks idle time. Inline SVG, redrawn at the frame rate.

### Inspection history
A window with a scrolling list: each entry is time (Condensed, `ink-2`), a judgement chip, and a sentence; anomalies carry two 4:3 thumbnails (EXPECTED, LIVE) of the held frames with 1px navy keylines.

### Simulator row
Shown only on the simulated rig, below a dashed rule: a Simulator field name and five small keys (Hand on arm, Arm stuck, Push arm, Cover lens, Clear).

### Offline overlay
Full-screen 94% panel-grey veil; a white plate with a 3px navy border reading "Lost the connection to Vizion Motor" in Condensed 700 uppercase, and a plain sentence with the restart command in a ruled code chip.

## Do's and Don'ts

### Do:
- **Do** keep every corner square (0px) and every surface flat; separate with navy keylines.
- **Do** reserve green and red for judgements and anomaly evidence, and keep measurements navy until they cross their limit.
- **Do** use cyan only for what the inspection is looking at: ROI boxes at rest, the tool tag, the camera's trace, selection and focus.
- **Do** switch state instantly; let only live data (bar, trends, clock) move. The only timed transitions are the 150ms key background/colour change and the 1000ms hold-to-exit fill.
- **Do** reserve a slot for anything that changes on a trip, so the layout never shifts.
- **Do** set labels in Barlow Condensed uppercase and sentences in Barlow sentence case, with tabular figures everywhere.
- **Do** use dashed borders for not-yet or unavailable states and hatching for absence.

### Don't:
- **Don't** use KPI tiles or big-number cards for counts; counts are a ruled table row.
- **Don't** add shadows, rounded corners, tonal gradients, or blur; the 45° hatching for absence is the only patterned fill.
- **Don't** colour the match bar green; below the limit it is navy.
- **Don't** let the lamp word wrap; step its size down instead.
- **Don't** show a stale limit while the system is re-learning.
- **Don't** animate state changes (no fades, slides or pulses on the lamp, box or panes).
