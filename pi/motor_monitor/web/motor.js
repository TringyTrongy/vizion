// Vizion Motor page: polls /api/state four times a second and draws the inspection panel.
"use strict";

const $ = (id) => document.getElementById(id);
const POLL_MS = 250;
const WINDOW_S = 60;
const LAMP_WORDS = {
  "WATCHING": "OK", "ANOMALY": "Anomaly", "STOPPED": "Stopped", "LEARNING": "Learning",
  "NOT LEARNED": "Not learned", "NO CAMERA": "No camera",
};
const EVENT_CHIPS = {
  anomaly: ["Anomaly", "ng"], learned: ["Learned", "info"], learn: ["Setup", "info"],
  learn_failed: ["Not learned", "low"], start: ["Run", "info"], stop: ["Stop", "info"], camera: ["No camera", "low"],
};

const kiosk = new URLSearchParams(location.search).has("kiosk");
let seq = 0;
let samples = [];  // [seq, t, told°, seen°, mismatch, state code]
let last = null;
let failures = 0;
let lastEventsKey = null;
let plateBusy = { live: false, expected: false };
let plateKey = { live: "", expected: "" };
let errorTimer = null;

// ---- Small helpers -------------------------------------------------------------------------

function fmt(v, digits = 3) {
  return v === null || v === undefined ? "–" : Number(v).toFixed(digits);
}
function deg(v) {
  if (v === null || v === undefined) return "–";
  const n = Math.round(v);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n)}°`;
}
function clockOf(stamp) {
  return stamp ? stamp.slice(11, 19) : "";
}
function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}
function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// ---- Polling -------------------------------------------------------------------------------

async function poll() {
  try {
    const r = await fetch(`/api/state?after=${seq}`, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    const s = await r.json();
    failures = 0;
    $("offline").hidden = true;
    if (s.seq < seq) samples = [];  // the server restarted
    for (const p of s.trace) samples.push(p);
    seq = s.seq;
    if (samples.length) {
      const newest = samples[samples.length - 1][1];
      while (samples.length && samples[0][1] < newest - WINDOW_S) samples.shift();
    }
    last = s;
    render(s);
  } catch (e) {
    failures += 1;
    if (failures >= 3) $("offline").hidden = false;
  } finally {
    setTimeout(poll, POLL_MS);
  }
}

// ---- Rendering -----------------------------------------------------------------------------

function render(s) {
  const st = s.state;
  document.querySelector(".station").dataset.state = st;
  for (const m of document.querySelectorAll(".mode")) m.classList.toggle("on", m.dataset.mode === s.mode);
  $("rig-tag").hidden = !s.rig.simulated;
  $("sim").hidden = !(s.rig.simulated && s.rig.camera.startsWith("simulated"));

  renderLamp(s);
  setText($("reason"), s.reason);
  renderMatch(s);
  renderKeys(s);
  renderPanes(s);
  renderTools(s);
  renderTrends();
  renderEvents(s);
}

function renderLamp(s) {
  const lamp = $("lamp");
  const word = LAMP_WORDS[s.state] || s.state;
  if (lamp.dataset.state !== s.state || $("lamp-word").textContent !== word) {
    lamp.dataset.state = s.state;
    lamp.dataset.size = word.length <= 7 ? "l" : word.length <= 9 ? "m" : "s";
    setText($("lamp-word"), word);
    fitLamp();
  }
  const learn = s.learn;
  $("learn").hidden = !learn;
  if (learn) {
    const bar = $("learn-bar");
    if (!bar.children.length) bar.innerHTML = "<i></i>".repeat(32);
    const on = Math.round(learn.progress * 32);
    [...bar.children].forEach((seg, i) => seg.classList.toggle("on", i < on));
    const phase = learn.phase === "still" ? "Holding the arm still" : "Sweeping";
    setText($("learn-text"), `${phase} · ${learn.remaining_s} s left · ${learn.pictures} pictures`);
  }
}

function fitLamp() {
  const w = $("lamp-word");
  w.style.fontSize = "";
  const face = w.parentElement;
  const room = face.clientWidth - 40;
  if (w.scrollWidth > room && room > 0) {
    const size = parseFloat(getComputedStyle(w).fontSize);
    w.style.fontSize = `${Math.floor(size * room / w.scrollWidth)}px`;
  }
}

function renderMatch(s) {
  const limit = s.now.limit;
  let value = s.now.mismatch;
  let note = "Compared with the master images at the same commanded position.";
  if (s.state === "ANOMALY" && s.trip && s.trip.score !== undefined) {
    value = s.trip.score;
    note = "Held at the frame that tripped tool 01.";
  } else if (!limit) {
    value = null;
    note = "Learn normal sets the limit.";
  } else if (s.state === "STOPPED") {
    note = "Compared with the arm parked in the middle: a push shows here.";
  }
  setText($("match-value"), value === null ? "–" : fmt(value));
  setText($("match-limit"), limit ? `limit ${fmt(limit)}` : "");
  setText($("match-note"), note);
  const fill = $("match-fill");
  const frac = value === null || !limit ? 0 : Math.min(1, value / (2 * limit));
  fill.style.width = `${(frac * 100).toFixed(1)}%`;
  fill.classList.toggle("over", value !== null && limit && value > limit);
  $("match-tick").hidden = !limit;
}

function renderKeys(s) {
  const st = s.state;
  const learnKey = $("learn-key");
  const runKey = $("run-key");
  const restartKey = $("restart-key");
  learnKey.disabled = st === "LEARNING";
  learnKey.classList.toggle("primary", st === "NOT LEARNED");
  const stopping = ["WATCHING", "LEARNING", "ANOMALY", "NO CAMERA"].includes(st);
  runKey.dataset.action = stopping ? "stop" : "start";
  runKey.firstChild.textContent = stopping ? "Stop" : "Start";
  runKey.disabled = st === "NOT LEARNED";
  runKey.classList.toggle("primary", st === "STOPPED");
  restartKey.disabled = !["ANOMALY", "NO CAMERA"].includes(st);
  restartKey.classList.toggle("primary", !restartKey.disabled);
  $("confirm-n").textContent = s.settings.confirm_frames;
}

function renderPanes(s) {
  const st = s.state;
  const held = st === "ANOMALY" && s.trip;
  const tripId = held ? s.trip.id : null;
  // Expected
  let expNote = "none yet";
  if (st === "WATCHING") expNote = `master at ${deg(s.now.command_deg)}`;
  else if (st === "STOPPED") expNote = "master, arm parked in the middle";
  else if (st === "LEARNING") expNote = "recording master images";
  else if (held) expNote = `master at ${deg(s.trip.command_deg)}`;
  else if (s.master) expNote = "master";
  setText($("expected-note"), expNote);
  const fps = s.now.fps ? `${s.now.fps} fps` : "no pictures";
  setText($("live-note"), held ? "the frame that tripped it" : `camera now · ${fps}`);

  const live = held ? `trip-${tripId}` : `f-${s.frames}`;
  const expected = held ? `trip-${tripId}` : s.master && st !== "LEARNING" && st !== "NOT LEARNED" ? `f-${s.frames}` : "";
  loadPlate("live", live, held ? `/api/plate/live.jpg?trip=${tripId}` : `/api/plate/live.jpg?f=${s.frames}`);
  if (expected) loadPlate("expected", expected, `/api/plate/expected.jpg?${held ? `trip=${tripId}` : `f=${s.frames}`}`);
  else clearPlate("expected", st === "LEARNING" ? "Recording the master images. Keep hands away from the arm."
    : "No master images yet. Learn normal records them.");

  // Region boxes
  const box = s.plate.box;
  const limit = s.now.limit;
  const over = held || (s.now.mismatch !== null && limit && s.now.mismatch > limit);
  const judged = ["WATCHING", "STOPPED", "ANOMALY"].includes(st) && limit;
  for (const which of ["expected", "live"]) {
    const roi = $(`roi-${which}`);
    roi.hidden = !box;
    if (!box) continue;
    roi.style.left = `${box[0] * 100}%`;
    roi.style.top = `${box[1] * 100}%`;
    roi.style.width = `${box[2] * 100}%`;
    roi.style.height = `${box[3] * 100}%`;
    roi.classList.toggle("below", box[1] < 0.12);
    roi.classList.toggle("ok", which === "live" && judged && !over);
    roi.classList.toggle("ng", which === "live" && judged && !!over);
  }
  const shown = held ? s.trip.score : s.now.mismatch;
  setText($("tool-tag"), shown === null || shown === undefined ? "01 Arm match" : `01 Arm match ${fmt(shown, 2)}`);

  const heldEl = $("held");
  heldEl.hidden = !held;
  if (held) {
    heldEl.innerHTML = `<b>Held frame</b><span>${esc(clockOf(s.trip.time))} · tool 01 tripped at mismatch ${fmt(s.trip.score, 2)}, limit ${fmt(s.trip.limit, 2)}. The servo is not being driven.</span>`;
  }
}

async function loadPlate(which, key, url) {
  if (plateKey[which] === key || plateBusy[which]) return;
  plateBusy[which] = true;
  try {
    const r = await fetch(url, { cache: "no-store" });
    if (r.status === 204) {
      clearPlate(which, which === "live" ? "Waiting for the camera…" : "No master image for this moment.");
      plateKey[which] = key;
      return;
    }
    if (!r.ok) return;
    const blob = await r.blob();
    const well = $(`pane-${which}`).querySelector(".well");
    let img = well.querySelector("img");
    if (!img) {
      img = document.createElement("img");
      img.alt = which === "live" ? "What the camera sees now" : "The master image the camera expected at this moment";
      well.prepend(img);
    }
    const old = img.src;
    img.src = URL.createObjectURL(blob);
    if (old && old.startsWith("blob:")) URL.revokeObjectURL(old);
    $(`${which}-empty`).hidden = true;
    plateKey[which] = key;
  } catch (e) {
    // the next poll tries again
  } finally {
    plateBusy[which] = false;
  }
}

function clearPlate(which, text) {
  const well = $(`pane-${which}`).querySelector(".well");
  const img = well.querySelector("img");
  if (img) {
    if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
    img.remove();
  }
  const empty = $(`${which}-empty`);
  setText(empty, text);
  empty.hidden = false;
  plateKey[which] = "";
}

function judge(el, text, cls) {
  setText(el, text);
  el.className = `judge${cls ? ` ${cls}` : ""}`;
}

function renderTools(s) {
  const st = s.state;
  const limit = s.now.limit;
  const cells = (n) => {
    const row = $(`tool-${n}`);
    return { m: row.querySelector('[data-k="m"]'), a: row.querySelector('[data-k="a"]'), j: row.querySelector('[data-k="j"]') };
  };
  // 01 Arm match
  const t1 = cells(1);
  const judged = ["WATCHING", "STOPPED", "ANOMALY"].includes(st) && limit;
  const value = st === "ANOMALY" && s.trip ? s.trip.score : s.now.mismatch;
  setText(t1.m, judged ? fmt(value) : "–");
  setText(t1.a, limit ? `limit ${fmt(limit)}` : "not learned");
  if (!judged || value === null) judge(t1.j, "–", "");
  else if (st === "ANOMALY") judge(t1.j, "Anomaly", "ng");
  else if (value > limit) judge(t1.j, "Over", "ng");
  else judge(t1.j, "OK", "ok");
  // 02 Arm position
  const t2 = cells(2);
  if (st === "WATCHING" || (st === "ANOMALY" && s.trip)) {
    const seen = st === "ANOMALY" ? s.trip.seen_deg : s.now.seen_deg;
    const told = st === "ANOMALY" ? s.trip.command_deg : s.now.command_deg;
    setText(t2.m, seen === null || seen === undefined ? "not recognised" : `seen ${deg(seen)}`);
    setText(t2.a, `told ${deg(told)}`);
    judge(t2.j, "Info", "info");
  } else {
    setText(t2.m, "–");
    setText(t2.a, "–");
    judge(t2.j, "–", "");
  }
  // 03 Camera
  const t3 = cells(3);
  const fps = s.now.fps;
  const age = s.now.camera_age_s;
  if (age === null || age > 2) {
    setText(t3.m, "no pictures");
    judge(t3.j, "None", "low");
  } else {
    setText(t3.m, fps ? `${fps.toFixed(1)} fps` : "starting");
    if (fps && fps < 3) judge(t3.j, "Low", "low");
    else judge(t3.j, "OK", "ok");
  }

  const c = s.counts;
  setText($("c-inspected"), String(c.inspected));
  setText($("c-over"), String(c.over_limit));
  setText($("c-anomalies"), String(c.anomalies));
  setText($("c-sweeps"), String(c.sweeps));

  const m = s.master;
  setText($("learned-line"), m
    ? `Normal learned ${m.learned_at.slice(11, 16)} from ${m.images} master images. Normal frames differ by ${fmt(m.normal_p50)} (99 in 100 under ${fmt(m.normal_p99)}), so the limit is ${fmt(m.limit)}.`
    : "");
  const notes = [...new Set(s.rig.notes)];
  setText($("rig-notes"), notes.join(" "));
}

// ---- Trends --------------------------------------------------------------------------------

function sizeSvg(svg) {
  const w = Math.max(200, Math.round(svg.clientWidth));
  const h = Math.max(100, Math.round(svg.clientHeight));
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  return [w, h];
}

function renderTrends() {
  const svgM = $("trend-mismatch");
  const svgA = $("trend-angle");
  const [wm, hm] = sizeSvg(svgM);
  const [wa, ha] = sizeSvg(svgA);
  const pad = { l: 46, r: 12, t: 12, b: 22 };
  const newest = samples.length ? samples[samples.length - 1][1] : 0;
  const t0 = newest - WINDOW_S;
  const xOf = (t, w) => pad.l + ((t - t0) / WINDOW_S) * (w - pad.l - pad.r);
  const limit = last && last.now.limit;

  // Bands where the motor was not sweeping, and anomaly marks: shared by both charts.
  const bands = [];
  const trips = [];
  let start = null;
  let prev = null;
  for (const p of samples) {
    const sweeping = p[5] === "W";
    if (!sweeping && start === null) start = p[1];
    if (sweeping && start !== null) { bands.push([start, p[1]]); start = null; }
    if (p[5] === "A" && prev !== "A") trips.push(p[1]);
    prev = p[5];
  }
  if (start !== null) bands.push([start, newest]);

  // Mismatch (log scale)
  const lo = Math.log10(0.001), hi = Math.log10(2);
  const yM = (v) => {
    const c = Math.min(hi, Math.max(lo, Math.log10(Math.max(v, 0.001))));
    return pad.t + (1 - (c - lo) / (hi - lo)) * (hm - pad.t - pad.b);
  };
  let out = "";
  for (const [a, b] of bands) out += `<rect class="idle-band" x="${xOf(a, wm)}" y="${pad.t}" width="${Math.max(0, xOf(b, wm) - xOf(a, wm))}" height="${hm - pad.t - pad.b}"/>`;
  for (const v of [0.001, 0.01, 0.1, 1]) {
    const y = yM(v);
    out += `<line class="grid" x1="${pad.l}" x2="${wm - pad.r}" y1="${y}" y2="${y}"/><text class="axis-label" x="${pad.l - 6}" y="${y + 4}" text-anchor="end">${v}</text>`;
  }
  for (const t of trips) out += `<line class="trip-line" x1="${xOf(t, wm)}" x2="${xOf(t, wm)}" y1="${pad.t}" y2="${hm - pad.b}"/>`;
  if (limit) {
    const y = yM(limit);
    out += `<line class="limit" x1="${pad.l}" x2="${wm - pad.r}" y1="${y}" y2="${y}"/><text class="limit-label" x="${wm - pad.r - 4}" y="${y - 5}" text-anchor="end">LIMIT ${limit.toFixed(2)}</text>`;
  }
  out += pathOf(samples, (p) => p[4], (p) => xOf(p[1], wm), yM, "mismatch");
  for (const p of samples) {
    if (p[4] !== null && limit && p[4] > limit) out += `<circle class="over" cx="${xOf(p[1], wm).toFixed(1)}" cy="${yM(p[4]).toFixed(1)}" r="3"/>`;
  }
  out += timeAxis(wm, hm, pad, xOf);
  svgM.innerHTML = out;

  // Arm angle: told versus seen
  const yA = (v) => pad.t + (1 - (v + 50) / 100) * (ha - pad.t - pad.b);
  out = "";
  for (const [a, b] of bands) out += `<rect class="idle-band" x="${xOf(a, wa)}" y="${pad.t}" width="${Math.max(0, xOf(b, wa) - xOf(a, wa))}" height="${ha - pad.t - pad.b}"/>`;
  for (const v of [-40, 0, 40]) {
    const y = yA(v);
    out += `<line class="grid" x1="${pad.l}" x2="${wa - pad.r}" y1="${y}" y2="${y}"/><text class="axis-label" x="${pad.l - 6}" y="${y + 4}" text-anchor="end">${deg(v)}</text>`;
  }
  for (const t of trips) out += `<line class="trip-line" x1="${xOf(t, wa)}" x2="${xOf(t, wa)}" y1="${pad.t}" y2="${ha - pad.b}"/>`;
  out += pathOf(samples, (p) => p[2], (p) => xOf(p[1], wa), yA, "told");
  out += pathOf(samples, (p) => p[3], (p) => xOf(p[1], wa), yA, "seen");
  out += timeAxis(wa, ha, pad, xOf);
  svgA.innerHTML = out;
}

function pathOf(points, value, x, y, cls) {
  let d = "";
  let pen = false;
  for (const p of points) {
    const v = value(p);
    if (v === null || v === undefined) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${x(p).toFixed(1)} ${y(v).toFixed(1)}`;
    pen = true;
  }
  return d ? `<path class="${cls}" d="${d}"/>` : "";
}

function timeAxis(w, h, pad, xOf) {
  const newest = samples.length ? samples[samples.length - 1][1] : 0;
  let out = "";
  for (const ago of [60, 45, 30, 15, 0]) {
    const x = xOf(newest - ago, w);
    out += `<text class="axis-label" x="${x}" y="${h - 6}" text-anchor="${ago === 60 ? "start" : ago === 0 ? "end" : "middle"}">${ago ? `−${ago} s` : "now"}</text>`;
  }
  return out;
}

// ---- History -------------------------------------------------------------------------------

function renderEvents(s) {
  const evs = s.events;
  const key = evs.map((e) => `${e.id}${e.evidence ? "e" : ""}`).join(",");
  if (key === lastEventsKey) return;
  lastEventsKey = key;
  const list = $("events");
  if (!evs.length) {
    list.innerHTML = `<li class="events-empty">Nothing yet. Learn normal, start the sweep, then try stopping the arm by hand.</li>`;
    return;
  }
  list.innerHTML = evs.slice().reverse().map((e) => {
    const [label, cls] = EVENT_CHIPS[e.kind] || [e.kind, "info"];
    const shots = e.kind === "anomaly" && e.evidence
      ? `<div class="shots"><figure><img src="/api/evidence/${e.id}/expected.jpg" alt="Expected at the anomaly" loading="lazy"><figcaption>Expected</figcaption></figure><figure><img src="/api/evidence/${e.id}/live.jpg" alt="Live at the anomaly" loading="lazy"><figcaption>Live</figcaption></figure></div>`
      : "";
    return `<li><time>${esc(clockOf(e.time))}</time><span class="judge ${cls}">${esc(label)}</span><p>${esc(e.text)}</p>${shots}</li>`;
  }).join("");
}

// ---- Controls ------------------------------------------------------------------------------

async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `The dashboard answered ${r.status}.`);
  return data;
}

function showError(text) {
  const el = $("key-error");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(errorTimer);
  errorTimer = setTimeout(() => { el.hidden = true; }, 6000);
}

async function press(key) {
  if (!key || key.disabled) return;
  key.classList.add("pressed");
  setTimeout(() => key.classList.remove("pressed"), 160);
  try {
    if (key.dataset.action) await post("/api/control", { action: key.dataset.action });
    else if (key.dataset.sim) await post("/api/sim", { action: key.dataset.sim });
    $("key-error").hidden = true;
  } catch (e) {
    showError(e.message);
  }
}

for (const key of document.querySelectorAll("[data-action], [data-sim]")) {
  key.addEventListener("click", () => press(key));
}

const exportKey = $("export-key");
const exportMenu = $("export-menu");
function toggleExport(open) {
  const show = open === undefined ? exportMenu.hidden : open;
  exportMenu.hidden = !show;
  exportKey.setAttribute("aria-expanded", String(show));
  if (show) exportMenu.querySelector("a").focus();
}
exportKey.addEventListener("click", () => toggleExport());
document.addEventListener("click", (e) => {
  if (!exportMenu.hidden && !e.target.closest(".export")) toggleExport(false);
});
for (const a of exportMenu.querySelectorAll("a")) a.addEventListener("click", () => toggleExport(false));

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === " " || k === "spacebar") { e.preventDefault(); press($("run-key")); }
  else if (k === "l") press($("learn-key"));
  else if (k === "r") press($("restart-key"));
  else if (k === "e") toggleExport();
  else if (k === "escape") {
    if (!exportMenu.hidden) toggleExport(false);
    else if (kiosk) quit();
  } else if (k === "q" && kiosk) quit();
});

// ---- Kiosk exit ----------------------------------------------------------------------------

async function quit() {
  try { await post("/api/quit", {}); } catch (e) { /* closing anyway */ }
  window.close();
}
if (kiosk) {
  document.body.classList.add("kiosk");
  const exit = $("exit-key");
  exit.hidden = false;
  let timer = null;
  const begin = (e) => {
    e.preventDefault();
    exit.classList.add("holding");
    timer = setTimeout(quit, 1000);
  };
  const cancel = () => {
    exit.classList.remove("holding");
    clearTimeout(timer);
  };
  exit.addEventListener("pointerdown", begin);
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) exit.addEventListener(ev, cancel);
}

// ---- Clock and start -----------------------------------------------------------------------

function tick() {
  const d = new Date();
  setText($("clock"), d.toTimeString().slice(0, 8));
}
setInterval(tick, 1000);
tick();
window.addEventListener("resize", () => { fitLamp(); if (last) renderTrends(); });
document.fonts.ready.then(fitLamp);
poll();
