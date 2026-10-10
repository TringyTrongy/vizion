---
version: 1
slug: "pi-sensor-monitor-web-index-html"
primary_target: "pi/sensor_monitor/web/index.html"
related_targets: ["pi/sensor_monitor/web/sensor.css","pi/sensor_monitor/web/sensor.js","pi/sensor_monitor/sensor_dashboard.py"]
---

## Scope

Vizion Sense: the temperature and humidity anomaly dashboard (`pi/sensor_monitor/web/index.html`, served by `pi/sensor_monitor/sensor_dashboard.py` on port 8766). Shown full screen in Chromium kiosk on the Pi's 1920×1080 monitor (`?kiosk`, which also turns on the lite rendering), and opened in a normal browser on a laptop or phone (`--host 0.0.0.0`). Separate surface from the camera dashboard (`pi/web/`, Schematic Sheet); it does not share that design system.

## Audience, task, content, constraints

- The reader the user named is the portfolio owner, an AI/ML engineer and Forge Fellow (https://gowrishankar2705.github.io/gowrishankar/): the user asked for a dashboard that "would impress his taste". Second reader: the user, a learner, who demos it and reads it at arm's length.
- Three tabs picked from the top bar (since the user's redo on 2026-10-10): DHT11 `LIVE` (GPIO4, every 2 s; renamed from "Live sensor" at the user's request on 2026-10-09), Motor (the SG90 "fan" switched by humidity, with latched safety shutdowns; the kiosk opens here), and Sample data `DATA` (the NAB Industrial machine and Office ambient replays, picked with pills inside the tab). The Simulated tab was removed; `--dht11 sim` feeds a labelled simulated DHT11 for development. Public and simulated data must always be visibly labelled as such.
- Per reading: timestamp, temperature °C, humidity %, status NORMAL / ANOMALY / SENSOR ERROR, alert reason. Plus: rolling baseline (average, spread, z), alerts with start/end and reasons, recent readings, counts, CSV export (last hour / today / everything), hold-to-exit in kiosk.
- Offline, no build step, stdlib server, self-hosted fonts. The Pi 5 renders it alongside other work: no backdrop blur in lite mode, the background animation capped at 24 fps.

## Direction contract

THESIS: The dashboard belongs in the portfolio owner's own world: the near-black, monochrome, Space Grotesk + Inter site with glass cards, pill chips, a hexagon portrait frame, count-up stats, a vertical experience timeline and a drifting constellation. Data first, explained in plain words; colour is reserved for state.

OWN-WORLD: Background #020202; headings #fff; body #bdbdbf; muted #8f8f92. Space Grotesk 700 for the status word, values and counts (tight tracking); Inter for text; uppercase letter-spaced labels like the portfolio's category labels. Cards rgba(20,20,25,0.4) with a 1px rgba(255,255,255,0.06) border and 20px radius (his skill cards); pills #1a1a2e with a 0.1 white border (his skill chips); white primary button (his "View My Work"). State colours only: cyan #00d4ff live/normal (his cursor-link cyan), amber #f59e0b anomaly (his only warm accent), rose #fb7185 sensor error.

STORY: From across the desk: one huge word (NORMAL / ANOMALY / SENSOR ERROR) beside a hexagon emblem, and the reason in a sentence. Closer: the two values with a deviation meter showing where each sits against its recent average and threshold; the chart with the expected range band, flagged points and failed reads; the alert timeline; the recent readings. Switching to a replay shows the detector catching NAB's labelled machine failure, with the labelled windows hatched on the chart.

FIRST VIEWPORT: 1920×1080, one screen, no scroll. Top bar: logo VZ. (its dot takes the state colour), sources, clock, Export CSV. Hero row: hexagon + status word, reason sentence, controls (Pause readings / Reset readings with a second-tap confirm, then the dataset pills and replay jumps, or the live note; PAUSED shows as a grey status word); right: floating source badge (the only provenance label: "Live · DHT11 on GPIO4", "Simulated DHT11 · not a real sensor", "Public dataset replay · NAB") and four count-up stats (readings, flagged, failed reads, anomaly alerts). Then temperature and humidity cards (dataset card in replays), the chart across both, and on the right the alert timeline over the recent-readings table.

FORM: Portfolio Monochrome, built directly from the named reference instead of a concept roll; no seed key. The user set the direction in their own words on 2026-10-09: "https://gowrishankar2705.github.io/gowrishankar/index.html go to this portfolio and make the dashboard that would impress his taste." Signature moments: the status word re-reveals letter by letter on every change (his reveal-text), the hexagon core breathes and its ring pulses on alerts, the constellation's links turn amber or rose with the state, numbers tween like his counters, cards tilt on hover on desktop.

FINISH: reviewed by the finish reviewer against this contract and the portfolio; DESIGN.md stays the camera dashboard's record, so this surface's decisions live in this contract and the CSS header.

## Unresolved

- The DHT11 has been wired and reading since 2026-10-10; early read failures were a loose jumper wire.
- The Motor tab (humidity scale with ON/OFF steppers, a CSS-animated servo dial, safety checks, events timeline, Auto/Hand/Off pills, Emergency stop / Restart) was added after this surface's finish review and has not had its own review.
