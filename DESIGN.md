---
name: Vizion
description: Live resistor and capacitor detection, drawn as an electronics drawing sheet.
colors:
  paper: "#f1f4f3"
  paper-hi: "#e3eaec"
  ink: "#1b2747"
  ink-2: "#44526e"
  ink-3: "#627087"
  nonrepro: "#a9c4d6"
  dot: "#cfdbe3"
  res: "#c2410c"
  cap: "#0f766e"
  fault: "#9f1239"
  fault-tint: "#f3dbe2"
typography:
  display:
    fontFamily: "osifont, DejaVu Sans Condensed, sans-serif"
    fontSize: "9.6rem"
    fontWeight: 400
    lineHeight: 1
    fontFeature: "tnum"
  headline:
    fontFamily: "osifont, DejaVu Sans Condensed, sans-serif"
    fontSize: "4.8rem"
    fontWeight: 400
    lineHeight: 1.1
    letterSpacing: "0.04em"
  title:
    fontFamily: "osifont, DejaVu Sans Condensed, sans-serif"
    fontSize: "3.2rem"
    fontWeight: 400
    lineHeight: 1.1
    letterSpacing: "0.06em"
  body:
    fontFamily: "osifont, DejaVu Sans Condensed, sans-serif"
    fontSize: "2rem"
    fontWeight: 400
    lineHeight: 1.3
  label:
    fontFamily: "osifont, DejaVu Sans Condensed, sans-serif"
    fontSize: "max(1.4rem, 11px)"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "0.1em"
rounded:
  none: "0"
spacing:
  hair: "0.4rem"
  cell: "1.2rem"
  gutter: "2.4rem"
  grid: "2rem"
components:
  command:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0.9rem 1.4rem 0.6rem"
    height: "4.4rem"
  command-hover:
    backgroundColor: "{colors.paper-hi}"
  command-active:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  command-disabled:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink-3}"
  block:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    height: "8rem"
    width: "17rem"
  block-fault:
    backgroundColor: "{colors.fault-tint}"
    textColor: "{colors.fault}"
  title-block-cell:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    padding: "0.8rem 1.1rem 0.9rem"
  part-flag-resistor:
    backgroundColor: "{colors.res}"
    textColor: "{colors.paper}"
  part-flag-capacitor:
    backgroundColor: "{colors.cap}"
    textColor: "{colors.paper}"
  part-flag-unrecognised:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  stamp:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    padding: "0.9rem 1.4rem 0.7rem"
  link-banner:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.fault}"
    padding: "3rem 4rem 2.6rem"
    width: "92rem"
---

# Design System: Vizion

## Overview

**Creative North Star: "The Drawing Sheet"**

Vizion's screen is an electronics drawing: drafting film, navy ink laid down at ISO pen widths, non-repro blue construction lines, and ISO 3098 lettering. Every surface is a drafted object with a real counterpart on a sheet: a framed drawing area with zone rulers, net-label flags on detected parts, a block diagram with a working switch, a ruled parts list, a reference table, a notes line and a title block. Nothing floats, glows or lifts; state is shown by changing the ink, the line style or the hatching.

The sheet is laid out once, at 1920×1080, and scales as one drawing. `1rem` is 10px at 1080p (`font-size: min(100vh / 108, 100vw / 192)` on `:root`), so every measurement in this file is a drawing measurement and the whole sheet keeps its proportions on any screen. Small lettering carries pixel floors (`max(1.4rem, 12px)` and similar) so it stays legible when the sheet shrinks.

Density is that of a working drawing: tight ruled cells, generous only where something must read from 3 m (counts, the switch state, the clock, the wordmark).

**Key Characteristics:**
- Flat drafting film with a 2rem non-repro dot grid; no shadows, no rounded containers.
- One typeface (osifont, ISO 3098) at one weight; emphasis is pen weight, drawn with text stroke.
- Strokes come from four ISO pen widths; line style (solid, dashed, hatched) carries state alongside colour.
- Class inks are reserved: orange for resistors, teal for capacitors, red pen for faults only.
- Real schematic symbols (zigzag resistor, two-plate capacitor, SPST switch), drawn as SVG.

## Colors

A cool, near-monochrome drafting palette (navy ink on pale film) with three reserved inks that each mean exactly one thing.

### Primary
- **Drafting Ink** (ink): every frame line, ruled table border, block outline, primary lettering, the S1 lever and wires, and the pressed state of commands (ink fill, paper text). 13.3:1 on film.

### Secondary
- **Resistor Ink** (res): resistor boxes and flags on the camera, the resistor symbol, the resistor PRESENT mark and text, and resistor designators in the reference table. Never used for anything that is not a resistor.
- **Capacitor Ink** (cap): the same roles for capacitors.

### Tertiary
- **Red Pen** (fault): faults and lost connections only: a block in fault, the camera-lost title, the connection banner border and title, error detail lines, the RE-LEARN state. Paired with **Red Pen Wash** (fault-tint) as the hatch colour inside a faulted block.

### Neutral
- **Drafting Film** (paper): the sheet, table and block fills, keylines under part marks, and lettering on inked flags.
- **Pressed Film** (paper-hi): hover and press on commands and the exit cell, and the camera area's empty background.
- **Form Ink** (ink-2): printed form lettering: table headers, title-block field names, notes, secondary status lines and detail text (7.1:1).
- **Idle Ink** (ink-3): not-applicable and idle states: idle block outlines, WAITING / NOT LEARNED / NO CAMERA, unknown counts, disabled commands, the open switch's downstream wire. 4.5:1 on film, so it may letter small idle and status text too.
- **Non-repro Blue** (nonrepro): construction lines only: the dashed thirds over the camera, the busy blink, the tinted zone on the rulers (55% alpha), switch hover (18% alpha), text selection. Never lettering (1.6:1).
- **Grid Dot** (dot): the sheet's dot grid, nothing else.

### Named Rules
**The Reserved Ink Rule.** Resistor ink, capacitor ink and red pen each name one thing. A colour that means "resistor" is never borrowed for emphasis, and red pen never appears unless something has failed.

**The Not By Colour Alone Rule.** Every coloured state also changes form: PRESENT fills the mark square, idle states dash the outline, faults hatch the block, the open switch dashes its wire. Remove the colour and the state still reads.

## Typography

**Display Font:** osifont (with DejaVu Sans Condensed, sans-serif), self-hosted WOFF, `font-display: block`.
**Body Font:** the same face; there is no second family.

**Character:** Engineering-standard ISO 3098 lettering, narrow and mechanical, set mostly in capitals with open tracking, the way a draughtsman letters a sheet.

### Hierarchy
- **Display** (9.6rem, line-height 1, tabular figures, stroke 0.035em): the per-class quantity. The TOTAL uses the same style at 6rem.
- **Headline** (4.4–5.4rem): the wordmark VIZION in the title block (5.4rem, tracking 0.16em, stroke 0.05em), the camera's message title (4.8rem, 0.04em), the clock (4.6rem, tabular), the S1 state ON / OFF (4.4rem, 0.08em).
- **Title** (2.6–3.6rem): part names in the parts list (3.2rem, 0.06em), the PRESENT line (2.8rem), block names and TOTAL (2.6rem, 0.08–0.1em), the connection banner title (3.6rem).
- **Body** (2–2.6rem, line-height 1.25–1.3): camera detail text (2.6rem, max 60ch, balanced), reference table rows, designators and title-block values (2rem).
- **Label** (1.2–1.8rem with pixel floors of 11–12px, tracking 0.06–0.12em): table headers, title-block field names, the S1 reference, ruler letters, the notes line, command lettering.

### Named Rules
**The Pen Weight Rule.** osifont has one weight; never set `font-weight` for emphasis. Emphasis is drawn with `-webkit-text-stroke` in `currentColor`, from 0.02em (block names) through 0.035–0.045em (counts, switch state, PRESENT) to 0.05em (wordmark).

**The Lettering Floor Rule.** Any lettering below 2rem carries a pixel floor (`max(Nrem, 11–14px)`) so the scaled sheet never letters smaller than a reader can resolve. Designators use line-height 1.3, because osifont's capitals rise above the em box and a tighter line clips them.

## Layout

The sheet is a fixed 192×108rem drawing centred on the dot-grid film, framed by a 0.7mm-pen border inset 1.1rem. A six-column, five-row grid places a 2.8rem zone ruler (1 2 3 across, A B C down) around the drawing area (122×96rem, exactly twice the 610×480 camera), a notes strip under it (4.4rem), and a 60rem right column, with 2.4rem gutters throughout.

The right column stacks four fixed blocks with a 1.2rem gap: the block diagram (19rem), the parts list (42.6rem), the reference table (fills the rest, padded with empty ruled rows so the sheet never looks unfinished), and the title block (19.4rem, four columns of ruled cells).

Below 1600×900 (`max-width: 1599px` or `max-height: 899px`) the drawing area gives up 6rem of width and 4.7rem of height, the right column widens to 66rem and the notes strip grows to 9.1rem, so floored small lettering has room to wrap. The sheet itself still scales as one drawing.

Rhythm is ruled rather than spaced: cell padding 1.2rem horizontally in tables, 0.8–1.1rem in title-block cells, 0.4–0.6rem between stacked lines in a cell.

## Elevation & Depth

Completely flat. There are no shadows anywhere. Depth is the drafting kind: a heavier pen for an outer boundary (frame, title block, banner at 0.3rem), a lighter pen for internal rules (0.1rem), and a paper keyline under coloured marks so they separate from the camera picture. Overlays (the connection banner, the camera message, the detection-off stamp) sit on opaque film with an inked border; whatever lies beneath dims to 28–35% opacity instead of blurring.

### Named Rules
**The Pen Hierarchy Rule.** Boundaries are ranked by ISO pen width, never by shadow: pen-1 (0.1rem) for internal rules, pen-2 (0.15rem) for header rules, pen-3 (0.2rem) for drawn objects and controls, pen-4 (0.3rem) for the sheet frame, title block and banners.

## Shapes

Square corners throughout (`border-radius: 0`, set explicitly on the switch). Round forms appear only where the drafted object is round: switch terminals are circles, and wire and lever strokes have round caps. Line style is part of the shape language: solid for live and present, dashed for idle, busy, not applicable and disabled, 45° hatching (1.6–1.8rem pitch for the camera, 0.9–1.2rem for a block) for faults. On the camera overlay, strokes use `vector-effect: non-scaling-stroke` so pen widths hold at any scale.

## Components

### Command (Learn empty table)
A ruled rectangle lettered like a drawing callout.
- **Shape:** square, pen-3 ink border, minimum height 4.4rem; an invisible `::after` extends the touch target to at least 44px when the sheet scales down.
- **States:** hover fills with pressed film; press inverts to ink fill with paper lettering; disabled dashes the border and letters in idle ink. Transitions 150ms on the sheet ease-out.
- **Focus:** a dashed pen-3 ink outline offset 0.4rem, shared by every button on the sheet.

### Block (CAMERA, MODEL)
A block-diagram box with its status lettered beneath it.
- **Busy:** dashed outline blinking between ink and non-repro blue (1.2s, two steps, no tweening).
- **Idle:** dashed idle-ink outline and lettering.
- **Fault:** red-pen outline and lettering over red-pen-wash hatching.

### Switch S1 (signature)
The detection control, drawn as an SPST switch between the two blocks, and the largest control on the sheet.
- **On:** the lever lies closed across both terminals; the downstream wire is solid ink. Each detection result sends one ink pulse along the wire (420ms, linear, at most eight in flight), so the pulse rate is the real detection rate.
- **Off:** the lever swings open 30° (220ms ease-out) and the downstream wire falls back to a dashed idle-ink line.
- **Hover / press:** an 18% non-repro wash, then pressed film. Keyboard shortcut D.

### Parts List (BOM)
A ruled table: symbol, part, quantity.
- **Rows:** the class symbol in its ink; the part name; a presence line with a 1.8rem mark square (filled with the class ink when present, dashed idle ink otherwise); designators in form ink, truncated with an ellipsis.
- **Quantity:** display-size tabular figures; an en dash in idle ink when the count is not known.
- **Unrecognised row:** a dashed square symbol, the presence line beside the Learn command, and a detail line that turns red pen on error.

### Reference Table
A ruled table of REF, CONF, ZONE, LOCATION at 2rem with fixed 3.05rem rows; the designator is lettered in its class ink, confidence right-aligned in tabular figures. Empty and error messages span the row; leftover height is filled with empty ruled rows.

### Part Marks (camera overlay)
Net-label annotation for each tracked part: a class-ink box (3.5px non-scaling stroke) over a 7px paper keyline, and a solid class-ink flag with paper lettering (designator and confidence) above the box, or below it when there is no room. All boxes draw first and all flags on top, so no flag is hidden. An unrecognised object gets a dashed ink box and an ink flag lettered "?".

### Title Block
A four-column ruled grid in a pen-4 frame: the wordmark with a one-line subtitle, the clock, then DATE, MODEL, SHOWN FROM and EXIT cells, each with a field name in form ink above its value.
- **Hold to exit:** the EXIT cell fills with ink left to right over 1000ms while held (the one motion kept under reduced motion, because it is the feedback), its lettering turning to paper from 500ms; releasing early cancels.

### Zone Rulers and Stamps
- **Rulers:** pen-1 ruled cells lettered 1–3 and A–C; a zone holding a part is washed in 55% non-repro blue and its letter turns ink with a light stroke.
- **Stamp:** an opaque film rectangle with a pen-3 border, top-left of the camera, for a mode notice (DETECTION OFF · CAMERA ONLY).
- **Connection banner:** a 92rem centred film panel with a pen-4 red-pen border over the dimmed sheet; when the service has been stopped on purpose it is inked navy instead.

## Do's and Don'ts

### Do:
- **Do** measure everything in rem on the 1920×1080 drawing (1rem = 10px) and let the root font size scale the sheet; give any lettering under 2rem a pixel floor.
- **Do** draw boundaries with the four pen widths (0.1, 0.15, 0.2, 0.3rem) and let line style (solid, dashed, hatched) carry state with colour.
- **Do** keep every class colour bound to its class: resistor ink for resistors, capacitor ink for capacitors, red pen for faults only.
- **Do** use real schematic symbols and drafting furniture (net-label flags, ruled tables, title-block cells, reference designators like R1, C1, S1) for new elements.
- **Do** show emphasis with text stroke in `currentColor`, never with a heavier weight or a second typeface.
- **Do** put a paper keyline under anything inked over the camera picture.
- **Do** use the sheet ease-out (`cubic-bezier(0.16, 1, 0.3, 1)`) at 150–300ms, and stop all motion under reduced motion except hold-to-exit feedback.

### Don't:
- **Don't** add shadows, glows, blur or smooth gradients; the only gradients on the sheet are the dot grid and 45° hatching.
- **Don't** round container corners; round forms are kept to terminals and line caps.
- **Don't** letter text in non-repro blue or grid dot.
- **Don't** use red pen for anything but a fault or a lost connection.
- **Don't** use icon fonts or emoji; a symbol is a drawn SVG schematic symbol or lettering.
- **Don't** add a small tracked label above a heading as decoration; small tracked lettering names a field in a ruled cell or a table column, nothing else.
