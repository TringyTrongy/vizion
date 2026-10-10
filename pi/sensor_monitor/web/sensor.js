"use strict";
// Vizion Sense page: polls /api/state for the chosen stream and draws it. No libraries.
(() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const params = new URLSearchParams(location.search);
  const KIOSK = params.has("kiosk");
  const LITE = KIOSK || params.has("lite");
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TOUCH = matchMedia("(hover: none)").matches;
  const body = document.body;
  if (LITE) body.classList.add("lite");

  const store = {
    get(k) { try { return localStorage.getItem("vizion-sense-" + k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem("vizion-sense-" + k, v); } catch { /* private window */ } },
  };

  let streamKey = params.get("stream") || store.get("stream") || "live";
  let meta = null;
  let since = 0;
  let points = [];
  let pollGen = 0;
  let pollTimer = 0;
  let failures = 0;
  let lastStatus = "";
  let lastStreams = "";
  let alertsKey = "";
  let seenAlerts = new Set();
  let recentTop = "";
  let checksKey = "";
  let charts = [];
  let state = null;
  let epoch = null;  // the stream's reset counter: a change means start the drawing again
  let resetTimer = 0;
  let levelEdit = null;  // ON/OFF levels being tapped, ahead of the server

  const STATUS_WORD = { NORMAL: "Normal", ANOMALY: "Anomaly", "SENSOR ERROR": "Sensor error", STARTING: "Starting",
    OFFLINE: "Offline", PAUSED: "Paused", RUNNING: "Running", STANDBY: "Standby", OFF: "Off",
    "SHUT DOWN": "Shut down", WAITING: "Waiting" };
  const WIRING = "Wiring: data to pin 7 (GPIO4), + to pin 1 (3.3 V), − to pin 6 (GND).";
  const EXPORT_HINT = {
    live: "Every reading, normal ones too: timestamp, temperature_c, humidity_percent, anomaly_status, alert_reason, source.",
    replay: "What has been played so far: timestamp, temperature_c, dataset_value, dataset_unit, anomaly_status, alert_reason, source.",
    motor: "One row a second: timestamp, humidity_percent, fan, state, mode, on_at, off_at, servo_pulse_us, event.",
  };
  const MODES = [["auto", "Auto", "The humidity decides"], ["hand", "Hand", "Runs whatever the humidity"],
    ["off", "Off", "Keeps the fan stopped"]];
  const CHECK_WORD = { ok: "OK", watch: "Watch", tripped: "Tripped", idle: "Idle" };
  const isMotor = () => !!meta && meta.kind === "motor";

  // ---------------------------------------------------------------- polling
  async function poll() {
    clearTimeout(pollTimer);
    const gen = ++pollGen;
    const key = streamKey;
    try {
      const r = await fetch(`/api/state?stream=${encodeURIComponent(key)}&since=${since}`, { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      const s = await r.json();
      if (gen !== pollGen) return;
      failures = 0;
      body.classList.remove("is-offline");
      apply(s);
    } catch {
      if (gen !== pollGen) return;
      if (++failures >= 3) offline();
    }
    pollTimer = setTimeout(poll, meta && meta.kind === "replay" ? 250 : 1000);
  }

  function switchStream(key) {
    if (key === streamKey) return;
    streamKey = key;
    store.set("stream", key);
    const info = state && state.streams.find((s) => s.key === key);
    if (info && info.kind === "replay") store.set("dataset", key);
    const url = new URL(location.href);
    url.searchParams.set("stream", key);
    history.replaceState(null, "", url);
    meta = null;
    epoch = null;
    since = 0;
    points = [];
    poll();
  }

  function apply(s) {
    const sameStream = meta && meta.key === s.meta.key;
    if (s.seq < since || (sameStream && epoch !== null && s.epoch !== epoch)) {
      // Readings reset, a replay jumped or the server restarted: draw everything again.
      epoch = s.epoch;
      since = 0;
      points = [];
      alertsKey = "";
      seenAlerts = new Set();
      recentTop = "";
      clearTimeout(pollTimer);
      pollTimer = setTimeout(poll, 0);
      return;
    }
    epoch = s.epoch;
    state = s;
    if (!meta || meta.key !== s.meta.key) {
      meta = s.meta;
      streamKey = s.stream;
      points = [];
      build();
    }
    meta = s.meta;
    points.push(...s.points);
    if (points.length > meta.chart_points) points.splice(0, points.length - meta.chart_points);
    since = s.seq;
    renderStreams(s.streams);
    $("#clock").textContent = s.clock.slice(11);
    if (isMotor()) {
      renderMotor(s);
    } else {
      renderStatus(s);
      renderBadge(s);
      renderActions(s);
      renderMetrics(s);
      renderAlerts(s);
      renderRecent(s);
      renderReplay(s);
    }
    renderStats(s.counts);
    drawCharts();
  }

  function offline() {
    body.classList.remove("is-anomaly", "is-error");
    body.classList.add("is-offline");
    setStatusWord("OFFLINE");
    $("#sentence").textContent = "The dashboard server is not answering. It may have been closed or restarted.";
    const badge = $("#badge");
    badge.className = "badge down";
    $("#badge-text").textContent = "No connection to the Pi";
  }

  // ---------------------------------------------------------------- building per stream
  function build() {
    const k = meta.kind;
    $("#chart-title").textContent = k !== "replay" ? "Last 10 minutes"
      : meta.key === "machine" ? "Last 2 days of the recording" : "Last 2 weeks of the recording";
    $("#stats").innerHTML = meta.stats.map((st) =>
      `<div><dt>${esc(st.label)}</dt><dd data-count="${st.key}"${st.format ? ` data-format="${st.format}"` : ""}>0</dd></div>`).join("");
    $("#export-title").textContent = `Export · ${meta.title}`;
    $("#export-hint").textContent = EXPORT_HINT[k] || "";
    for (const b of document.querySelectorAll(".export-pop .pill")) b.hidden = k === "replay" && b.dataset.range !== "all";
    $(".export-pop .pill[data-range=all]").textContent = k === "replay" ? "Everything played so far" : "Everything";
    body.classList.toggle("view-motor", k === "motor");
    if (k === "motor") buildMotor(); else buildSensor();
    lastStatus = "";
    alertsKey = "";
    seenAlerts = new Set();
    recentTop = "";
    checksKey = "";
    tilt();
  }

  function buildSensor() {
    const k = meta.kind;
    $("#legend").innerHTML = `<li><i class="lg-line"></i>Reading</li><li><i class="lg-band"></i>Expected range</li>` +
      `<li><i class="lg-flag"></i>Flagged</li><li><i class="lg-err"></i>Sensor error</li>` +
      (k === "replay" ? `<li><i class="lg-window"></i>NAB labelled anomaly window</li>` : "");
    $("#alerts-title").textContent = "Alerts";
    $("#side-b").innerHTML = `<header class="card-head"><p class="label">Recent readings</p></header>
      <table class="recent"><thead><tr id="recent-head"></tr></thead><tbody id="recent"></tbody></table>`;

    // Metric cards: one per channel; a replay has one channel, so the second card describes the data.
    meta.channels.forEach((ch, i) => { $(`#metric-${i}`).className = "card metric"; $(`#metric-${i}`).innerHTML = metricHTML(ch); });
    if (meta.channels.length === 1) {
      const card = $("#metric-1");
      card.className = "card dataset";
      const [a, b] = meta.dataset_span;
      card.innerHTML = `
        <header class="card-head"><p class="label">About this data</p><p class="label quiet">Public · not from the Vizion sensor</p></header>
        <h3>${esc(meta.title)}</h3>
        <p>${esc(meta.about)}</p>
        <p class="label quiet">${meta.rows.toLocaleString()} readings · ${a.slice(0, 10)} to ${b.slice(0, 10)} · ${meta.windows.length} labelled anomaly windows</p>
        <p class="label quiet">${esc(meta.unit_note)}</p>`;
    }
    charts = meta.channels.map((ch) => chartFor(ch, false));
    $("#charts").replaceChildren(...charts.map((c) => c.el));
    $("#charts").style.gridTemplateRows = `repeat(${charts.length}, minmax(0, 1fr))`;
    const short = { temperature_c: "Temp", humidity_percent: "Humidity" };
    $("#recent-head").innerHTML = "<th>Time</th>" + meta.channels.map((c) =>
      `<th>${short[c.key] || esc(c.label)}</th>`).join("") + "<th>Status</th>";
    buildControls();
  }

  function chartFor(ch, motor) {
    const el = document.createElement("div");
    el.className = "chart";
    el.innerHTML = `<canvas></canvas><span class="chart-label">${esc(ch.label)}${ch.unit ? " · " + esc(ch.unit) : ""}</span>`;
    return { el, canvas: el.firstChild, ch, motor };
  }

  function metricHTML(ch) {
    const edge = 100 * (1 - 1 / 1.5) / 2;
    const k = ch.k;
    return `
      <header class="card-head"><p class="label">${esc(ch.label)}</p><span class="state-note">Waiting</span></header>
      <div class="value"><span class="num">—</span><span class="unit">${esc(ch.unit || "")}</span></div>
      <div class="meter" style="--edge:${edge.toFixed(2)}%" title="Where the reading sits against the recent average. The amber ends start at ${k}σ: beyond them the reading is flagged.">
        <div class="track"></div><div class="mid"></div><div class="mark" style="left:50%;visibility:hidden"></div>
        <div class="ticks"><span class="lo">−${k}σ</span><span class="avg">average</span><span class="hi">+${k}σ</span></div>
      </div>
      <div class="facts"></div>`;
  }

  function buildControls() {
    const c = $("#controls");
    // A replay restarts with "From the start", so it gets no separate reset.
    const actions = `<div class="pills"><button class="pill" data-action="pause" aria-pressed="false">Pause readings</button>` +
      (meta.kind === "replay" ? "" : `<button class="pill" data-action="reset" title="Clears the chart, alerts, counts and baseline. The log on the Pi is kept.">Reset readings</button>`) +
      `</div><span class="sep" aria-hidden="true"></span>`;
    if (meta.kind === "replay") {
      const sets = state.streams.filter((s) => s.kind === "replay");
      const picker = sets.length < 2 ? "" : `<div class="pills seg" role="group" aria-label="Sample dataset">` +
        sets.map((s) => `<button class="pill${s.key === meta.key ? " on" : ""}" data-stream="${s.key}" aria-pressed="${s.key === meta.key}">${esc(datasetName(s))}</button>`).join("") +
        `</div><span class="sep" aria-hidden="true"></span>`;
      c.innerHTML = picker + actions + `<div class="progress"><span class="label">Replay</span><div class="track"><i></i></div><span class="when">--</span></div>
        <div class="pills"><button class="pill" data-window="0">From the start</button>` +
        meta.windows.map((w, i) => `<button class="pill" data-window="${i + 1}" title="Labelled anomaly at ${w.label}">Window ${i + 1}</button>`).join("") + "</div>";
    } else {
      c.innerHTML = actions + `<span class="label quiet" id="live-note"></span>`;
    }
  }

  // ---------------------------------------------------------------- rendering: DHT11 and replays
  // The navigation: the DHT11 and the fan, then one "Sample data" entry for the public dataset
  // replays, which opens the one looked at last. The replay view switches between them.
  function renderStreams(list) {
    const items = list.filter((s) => s.kind !== "replay")
      .map((s) => ({ key: s.key, label: s.title, tag: s.tag, active: s.key === streamKey }));
    const sets = list.filter((s) => s.kind === "replay");
    if (sets.length) {
      const here = sets.some((s) => s.key === streamKey);
      const last = sets.find((s) => s.key === store.get("dataset")) || sets[0];
      items.push({ key: here ? streamKey : last.key, label: "Sample data", tag: "DATA", active: here });
    }
    const key = JSON.stringify(items);
    if (key === lastStreams) return;
    lastStreams = key;
    $("#streams").innerHTML = items.map((s, i) =>
      `<button data-stream="${s.key}" class="${s.active ? "active" : ""}" aria-pressed="${s.active}" title="Key ${i + 1}">` +
      `${esc(s.label)}${s.tag ? `<span class="tag">${esc(s.tag)}</span>` : ""}</button>`).join("");
  }

  function datasetName(s) {
    return s.title.replace(/ temperature$/i, "");
  }

  function setStatusWord(status) {
    if (status === lastStatus) return;
    lastStatus = status;
    const el = $("#status");
    const word = STATUS_WORD[status] || status;
    el.setAttribute("aria-label", word);
    el.classList.remove("shown");
    el.replaceChildren(...[...word].map((ch, i) => {
      const s = document.createElement("span");
      s.className = "char";
      s.textContent = ch === " " ? " " : ch;  // a plain space would collapse in an inline-block
      s.style.transitionDelay = `${i * 0.03}s`;
      s.setAttribute("aria-hidden", "true");
      return s;
    }));
    void el.offsetWidth;
    requestAnimationFrame(() => el.classList.add("shown"));
  }

  function setSentence(html) {
    const el = $("#sentence");
    if (el.innerHTML !== html) el.innerHTML = html;
  }

  function renderStatus(s) {
    const paused = !!s.paused;
    body.classList.toggle("is-paused", paused);
    body.classList.toggle("is-anomaly", !paused && s.status === "ANOMALY");
    body.classList.toggle("is-error", !paused && s.status === "SENSOR ERROR");
    setStatusWord(paused ? "PAUSED" : s.status);
    const cur = s.current;
    const open = s.open_alert;
    let html;
    if (paused) {
      html = meta.kind === "live" ? "<b>Readings are paused.</b> The DHT11 is not read and nothing is logged until you resume. The fan's Auto mode waits too."
        : "<b>The replay is paused.</b>";
      if (cur) html += ` Last reading at ${when(cur.timestamp)}.`;
    } else if (!cur) html = "Waiting for the first reading…";
    else if (s.status === "SENSOR ERROR") {
      html = `<b>${esc(open ? open.reasons[0] : cur.error || "No reading")}.</b>`;
      if (meta.kind === "live" && !meta.simulated) html += " " + WIRING;
    } else if (s.status === "ANOMALY") {
      if (cur.status === "ANOMALY") {  // say what is unusual about the newest reading
        html = `<b>${esc(cur.reasons[0])}.</b>`;
        if (cur.reasons.length > 1) html += ` Also: ${esc(cur.reasons.slice(1, 3).join("; "))}.`;
      } else {
        html = `Back in the usual range; the alert closes after a few normal readings. It began with: ${esc(open.reasons[0])}.`;
      }
      if (meta.simulated && cur.note) html += ` <span class="label quiet">(${esc(cur.note)}, simulated)</span>`;
    } else if (cur.status === "SENSOR ERROR") {
      html = `One read failed (${esc(cur.reasons[0] || "no reply")}); trying again.`;
    } else if (cur.status === "ANOMALY") {
      html = `One unusual reading, watching the next: ${esc(cur.reasons[0])}.`;
    } else if (cur.learning) {
      const d = Object.values(cur.channels)[0] || {};
      html = `Learning what normal looks like: <b>${d.n ?? 0} of ${d.needed ?? "?"}</b> readings. Limits and sudden changes are already checked.`;
    } else {
      const what = meta.channels.length > 1 ? "Temperature and humidity are" : `${meta.channels[0].label} is`;
      html = `${what} within the usual range of the recent readings.`;
    }
    setSentence(html);
  }

  function renderBadge(s) {
    const badge = $("#badge");
    const live = meta.kind === "live";
    const down = live && s.status === "SENSOR ERROR";
    badge.className = "badge " + (s.paused ? "paused" : down ? "down" : meta.simulated ? "sim" : meta.kind === "replay" ? "replay" : "");
    $("#badge-text").textContent = s.paused ? `Paused · ${meta.title}` : down ? `Live · DHT11 not responding` : meta.badge;
    if (live) {
      const note = $("#live-note");
      if (note) note.textContent = `Read every ${meta.interval_s} s${meta.method ? " with " + meta.method : ""} · every reading is logged on the Pi`;
    }
  }

  function renderActions(s) {
    const b = $('[data-action="pause"]');
    if (!b) return;
    const label = s.paused ? "Resume readings" : "Pause readings";
    if (b.textContent !== label) b.textContent = label;
    b.classList.toggle("on", !!s.paused);
    b.setAttribute("aria-pressed", String(!!s.paused));
  }

  function renderMetrics(s) {
    const cur = s.current;
    meta.channels.forEach((ch, i) => {
      const card = $(`#metric-${i}`);
      const value = cur ? cur.values[ch.key] : null;
      const d = cur && cur.channels[ch.key];
      const flagged = !!cur && cur.status === "ANOMALY" && cur.reasons.some((r) => r.startsWith(ch.label));
      const failed = !cur || value == null;
      card.classList.toggle("flagged", flagged);
      card.classList.toggle("failed", failed && !!cur);
      card.classList.toggle("learning", !!d && d.n < d.needed);
      $(".state-note", card).textContent = !cur ? "Waiting" : failed ? "No reading" : flagged ? "Unusual"
        : d && d.n < d.needed ? `Learning · ${d.n}/${d.needed}` : "Within the usual range";
      tween($(".num", card), failed ? null : value, ch.decimals);
      const mark = $(".mark", card);
      const meter = $(".meter", card);
      const facts = [];
      if (d && d.z != null) {
        const range = ch.k * 1.5;
        mark.style.left = `${Math.max(0, Math.min(100, 50 + (d.z / range) * 50))}%`;
        mark.style.visibility = "visible";
        meter.style.opacity = 1;
        facts.push(`Average <b>${fmt(d.mean, ch)}</b>`, `Usual spread <b>±${fmt(d.sigma, ch, 1)}</b>`,
          `Now <b>${d.z >= 0 ? "+" : "−"}${Math.abs(d.z).toFixed(1)}σ</b>`);
      } else {
        mark.style.visibility = "hidden";  // no baseline or no value: nothing to place
        meter.style.opacity = 0.35;
        if (d) facts.push(`Building the baseline: <b>${d.n} of ${d.needed}</b> readings`);
      }
      if (ch.low != null && ch.high != null) facts.push(`Limits <b>${ch.low}–${fmt(ch.high, ch, 0)}</b>`);
      // Replays are shown in °C; the dataset's own number stays visible, with how sure its unit is.
      if (meta.dataset_unit === "°F" && value != null) {
        facts.push(`<b>${(value * 9 / 5 + 32).toFixed(1)} °F</b> in the data (°F ${esc(meta.unit_basis)})`);
      }
      setHTML($(".facts", card), facts.map((x) => `<span>${x}</span>`).join(""));
    });
  }

  function setHTML(el, html) {
    if (el && el.innerHTML !== html) el.innerHTML = html;
  }

  function unitSuffix(ch) {
    return !ch.unit ? "" : ch.unit === "%" ? "%" : " " + ch.unit;
  }

  function fmt(v, ch, decimals) {
    return `${Number(v).toFixed(decimals ?? ch.decimals)}${unitSuffix(ch)}`;
  }

  function tween(el, target, dp) {
    el.classList.toggle("none", target == null);
    if (target == null) { el.textContent = "—"; el.dataset.v = ""; return; }
    const from = el.dataset.v === "" || el.dataset.v == null ? target : Number(el.dataset.v);
    el.dataset.v = target;
    // replays change several times a second: a tween would always lag behind the newest value
    if (REDUCED || from === target || (meta && meta.kind === "replay")) { el.textContent = target.toFixed(dp); return; }
    const t0 = performance.now();
    const step = (t) => {
      const p = Math.min(1, (t - t0) / 450);
      const e = 1 - Math.pow(1 - p, 3);
      if (Number(el.dataset.v) !== target) return;
      el.textContent = (from + (target - from) * e).toFixed(dp);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function when(stamp) {
    if (meta.kind === "replay") return stamp.slice(0, 16);
    const today = state.clock.slice(0, 10);
    return stamp.slice(0, 10) === today ? stamp.slice(11) : stamp.slice(5, 16);
  }

  function seconds(a, b) {
    return Math.max(0, (Date.parse(b.replace(" ", "T")) - Date.parse(a.replace(" ", "T"))) / 1000);
  }

  function duration(a, b) {
    const s = seconds(a, b);
    if (s < 90) return `${Math.round(s)} s`;
    if (s < 5400) return `${Math.round(s / 60)} min`;
    if (s < 172800) return `${(s / 3600).toFixed(1)} h`;
    return `${(s / 86400).toFixed(1)} days`;
  }

  function clockText(s) {  // 83 -> "1:23", 3725 -> "1:02:05"
    s = Math.max(0, Math.round(s));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
  }

  function renderAlerts(s) {
    const total = s.counts.anomaly_alerts + s.counts.error_alerts;
    $("#alerts-count").textContent = total ? `${total} ${meta.kind === "replay" ? "so far in this replay" : "since the dashboard started"}` : "";
    const key = JSON.stringify(s.alerts.map((a) => [a.id, a.end, a.reasons.length])) + s.counts.readings;
    if (key === alertsKey) return;
    alertsKey = key;
    const list = $("#alerts");
    if (!s.alerts.length) {
      const n = s.counts.readings;
      list.innerHTML = `<li class="empty">No alerts yet. ${n ? `${n.toLocaleString()} readings checked so far.` : ""}</li>`;
      return;
    }
    list.innerHTML = s.alerts.map((a) => {
      const err = a.kind === "SENSOR ERROR";
      const open = !a.end;
      const fresh = !seenAlerts.has(a.id) ? "" : " style=\"animation:none\"";
      const range = open ? `${when(a.start)} → now` : `${when(a.start)} – ${when(a.end)} · ${duration(a.start, a.end)}`;
      return `<li class="${open ? "open" : ""} ${err ? "err" : ""}"${fresh}>
        <div class="when"><span>${range}</span><span class="kind">${err ? "Sensor error" : "Anomaly"}${open ? " · active" : ""}</span></div>
        ${a.reasons.map((r) => `<p class="reason">${esc(r)}</p>`).join("")}</li>`;
    }).join("");
    s.alerts.forEach((a) => seenAlerts.add(a.id));
  }

  function renderRecent(s) {
    const rows = s.recent.slice(0, KIOSK ? 8 : 9);
    const top = rows.length ? rows[0][0] + rows.length : "";
    if (top === recentTop) return;
    const prevTop = recentTop;
    recentTop = top;
    const code = { NORMAL: "N", ANOMALY: "A", "SENSOR ERROR": "E" };
    $("#recent").innerHTML = rows.map((r, i) => {
      const status = r[r.length - 2];
      const reason = r[r.length - 1];
      const vals = r.slice(1, r.length - 2).map((v, j) => v == null ? "—" : fmt(v, meta.channels[j]));
      const label = status === "SENSOR ERROR" ? "ERROR" : status;
      return `<tr class="${i === 0 && prevTop ? "fresh" : ""}" title="${esc(reason || "Normal")}"><td>${when(r[0])}</td>` +
        vals.map((v) => `<td>${v}</td>`).join("") + `<td class="st st-${code[status]}">${label}</td></tr>`;
    }).join("");
  }

  function renderStats(counts) {
    for (const dd of document.querySelectorAll("[data-count]")) {
      const target = counts[dd.dataset.count] ?? 0;
      if (dd.dataset.format === "duration") {  // a clock, not a count
        const text = clockText(target);
        if (dd.textContent !== text) dd.textContent = text;
        continue;
      }
      const from = Number(dd.dataset.v ?? 0);
      if (from === target && dd.dataset.v != null) continue;
      dd.dataset.v = target;
      if (REDUCED || target < from) { dd.textContent = target.toLocaleString(); continue; }
      const t0 = performance.now();
      const step = (t) => {
        const p = Math.min(1, (t - t0) / 700);
        if (Number(dd.dataset.v) !== target) return;
        dd.textContent = Math.round(from + (target - from) * (1 - Math.pow(1 - p, 3))).toLocaleString();
        if (p < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }
  }

  function renderReplay(s) {
    if (meta.kind !== "replay" || !s.replay) return;
    const bar = $(".progress .track i");
    if (bar) bar.style.width = `${(s.replay.progress * 100).toFixed(2)}%`;
    const w = $(".progress .when");
    if (w && s.current) w.textContent = s.current.timestamp.slice(0, 16);
  }

  // ---------------------------------------------------------------- the motor: building
  const DIAL = { cx: 130, cy: 132, r: 104 };
  function dialPoint(deg, r) {
    const a = (deg * Math.PI) / 180;
    return [DIAL.cx + r * Math.sin(a), DIAL.cy - r * Math.cos(a)];
  }

  function buildMotor() {
    $("#legend").innerHTML = `<li><i class="lg-line"></i>Humidity</li><li><i class="lg-level"></i>ON and OFF levels</li>` +
      `<li><i class="lg-run"></i>Fan running</li><li><i class="lg-trip"></i>Shut down</li>`;
    $("#alerts-title").textContent = "Fan events";
    $("#side-b").innerHTML = `<header class="card-head"><p class="label">Safety checks</p><p class="label quiet">Any one shuts the fan down</p></header>
      <ul class="checks" id="checks"></ul>`;

    const h = $("#metric-0");
    h.className = "card metric motor-humidity";
    h.innerHTML = `
      <header class="card-head"><p class="label">Humidity · DHT11</p><span class="state-note">Waiting</span></header>
      <div class="value"><span class="num">—</span><span class="unit">%</span></div>
      <div class="scale" aria-hidden="true">
        <div class="track"></div><div class="hold"></div><div class="above"></div>
        <div class="tick t-off"></div><div class="tick t-on"></div><div class="mark"></div>
        <span class="lab l-off"></span><span class="lab l-on"></span>
      </div>
      <div class="steppers">
        <div class="stepper"><span>Fan on at</span><button class="step" data-level="on" data-d="-1" aria-label="Lower the ON level">−</button><b data-v="on">—</b><button class="step" data-level="on" data-d="1" aria-label="Raise the ON level">+</button></div>
        <div class="stepper"><span>off at</span><button class="step" data-level="off" data-d="-1" aria-label="Lower the OFF level">−</button><b data-v="off">—</b><button class="step" data-level="off" data-d="1" aria-label="Raise the OFF level">+</button></div>
      </div>`;

    const sw = meta.sweep;
    const [ax, ay] = dialPoint(-sw.degrees, DIAL.r);
    const [bx, by] = dialPoint(sw.degrees, DIAL.r);
    const ticks = [-90, -60, -30, 0, 30, 60, 90].map((d) => {
      const [x1, y1] = dialPoint(d, DIAL.r + 6);
      const [x2, y2] = dialPoint(d, DIAL.r + (d % 90 === 0 ? 16 : 12));
      return `<line class="dial-tick" x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`;
    }).join("");
    const f = $("#metric-1");
    f.className = "card metric motor-fan";
    f.innerHTML = `
      <header class="card-head"><p class="label">Fan · SG90 servo</p><span class="state-note">—</span></header>
      <div class="fan-body">
        <div class="dial-wrap" aria-hidden="true">
          <svg class="dial" viewBox="0 0 260 142">
            <path class="dial-track" d="M ${DIAL.cx - DIAL.r} ${DIAL.cy} A ${DIAL.r} ${DIAL.r} 0 0 1 ${DIAL.cx + DIAL.r} ${DIAL.cy}"/>
            <path class="dial-sweep" d="M ${ax.toFixed(1)} ${ay.toFixed(1)} A ${DIAL.r} ${DIAL.r} 0 0 1 ${bx.toFixed(1)} ${by.toFixed(1)}"/>
            ${ticks}
          </svg>
          <div class="dial-arm" style="--deg:${sw.degrees}deg;animation-duration:${sw.period_s / 2}s"></div>
          <div class="dial-hub"></div>
        </div>
        <div class="fan-read">
          <div class="value"><span class="num" id="run-clock">0:00</span></div>
          <p class="state-label" id="run-label">Not running</p>
        </div>
      </div>
      <div class="facts"></div>`;

    charts = [chartFor(meta.channels[0], true)];
    $("#charts").replaceChildren(charts[0].el);
    $("#charts").style.gridTemplateRows = "minmax(0, 1fr)";

    $("#controls").innerHTML = `<div class="pills seg" role="group" aria-label="Fan mode">` +
      MODES.map(([k, label, tip]) => `<button class="pill" data-mode="${k}" aria-pressed="false" title="${tip}">${label}</button>`).join("") +
      `</div><span class="sep" aria-hidden="true"></span>` +
      `<button class="pill stop" data-fan="stop" title="Stops the fan at once. It stays stopped until Restart.">Emergency stop</button>` +
      `<button class="pill restart" data-fan="restart" hidden>Restart</button>`;
  }

  // ---------------------------------------------------------------- the motor: rendering
  function renderMotor(s) {
    const cur = s.current;
    const st = s.status;
    body.classList.remove("is-anomaly");
    body.classList.toggle("is-error", st === "SHUT DOWN");
    body.classList.toggle("is-paused", st === "OFF" || st === "WAITING" || st === "STARTING");
    setStatusWord(st);
    if (!cur) return setSentence("Starting the fan controller…");
    const leds = Object.keys(cur.leds || {});
    setSentence(cur.trip
      ? `<b>${esc(cur.trip.reason)}.</b> The fan is stopped${leds.includes("red") ? " and the red LED flashes" : ""}. ` +
        (cur.trip.check === "estop" ? "Press Restart when it is safe to run." : "Find the cause, then press Restart.")
      : esc(cur.why));

    const badge = $("#badge");
    badge.className = "badge " + (cur.trip ? "down" : meta.method ? "" : "sim");
    $("#badge-text").textContent = cur.trip ? "Shut down · no pulses to the servo" : meta.badge;

    for (const b of document.querySelectorAll("[data-mode]")) {
      const on = b.dataset.mode === cur.mode;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    }
    $('[data-fan="stop"]').hidden = !!cur.trip;
    $('[data-fan="restart"]').hidden = !cur.trip;

    renderHumidityCard(cur);
    renderFanCard(cur);
    renderMotorEvents(s);
    renderChecks(cur.checks);
  }

  function levels(cur) {
    if (levelEdit && performance.now() - levelEdit.t < 2500) return levelEdit;
    levelEdit = null;
    return { on: cur.on_at, off: cur.off_at };
  }

  function renderHumidityCard(cur) {
    const card = $("#metric-0");
    const h = cur.humidity;
    const { on, off } = levels(cur);
    tween($(".num", card), h, 0);
    card.classList.toggle("failed", h == null && (cur.sensor === "error" || cur.sensor === "failing"));
    card.classList.toggle("above", h != null && h >= on);
    $(".state-note", card).textContent = h == null
      ? ({ paused: "DHT11 paused", none: "No DHT11", error: "DHT11 not answering", failing: "DHT11 not answering" }[cur.sensor] || "No recent reading")
      : h >= on ? "At or above the ON level" : h <= off ? "Below the OFF level" : "Between the levels";
    const pos = (v) => `${Math.max(0, Math.min(100, ((v - 20) / 80) * 100)).toFixed(2)}%`;
    $(".hold", card).style.left = pos(off);
    $(".hold", card).style.width = `calc(${pos(on)} - ${pos(off)})`;
    $(".above", card).style.left = pos(on);
    $(".t-off", card).style.left = pos(off);
    $(".t-on", card).style.left = pos(on);
    $(".l-off", card).style.left = pos(off);
    $(".l-on", card).style.left = pos(on);
    $(".l-off", card).textContent = `OFF ${off}%`;
    $(".l-on", card).textContent = `ON ${on}%`;
    const mark = $(".mark", card);
    mark.style.visibility = h == null ? "hidden" : "visible";
    if (h != null) mark.style.left = pos(h);
    $('[data-v="on"]', card).textContent = `${on}%`;
    $('[data-v="off"]', card).textContent = `${off}%`;
    const L = meta.levels;
    $('[data-level="on"][data-d="-1"]', card).disabled = on - 1 - off < L.min_gap;
    $('[data-level="on"][data-d="1"]', card).disabled = on >= L.on_max;
    $('[data-level="off"][data-d="-1"]', card).disabled = off <= L.off_min;
    $('[data-level="off"][data-d="1"]', card).disabled = on - (off + 1) < L.min_gap;
  }

  function renderFanCard(cur) {
    const card = $("#metric-1");
    const sw = meta.sweep;
    if (cur.running && !card.classList.contains("running") && cur.sweep_phase != null) {
      // The arm is a CSS animation, drawn by the GPU: the page does no work per frame. Started at
      // the server's place in the sweep (CSS goes −cos, the server +sin: a quarter turn apart).
      $(".dial-arm", card).style.animationDelay = `${(-((cur.sweep_phase + 0.25) % 1) * sw.period_s).toFixed(2)}s`;
    }
    card.classList.toggle("running", cur.running);
    card.classList.toggle("tripped", !!cur.trip);
    $(".state-note", card).textContent = cur.running ? `Sweeping ±${sw.degrees}° every ${sw.period_s} s`
      : cur.trip ? "Stopped by the shutdown" : cur.pulse_us ? "Parking in the middle" : "Parked · no pulses";
    $("#run-clock").textContent = clockText(cur.run_for_s || 0);
    $("#run-label").textContent = cur.running ? "This run" : cur.trip ? "Shut down" : "Not running";
    const facts = [`Pulse <b>${cur.pulse_us ? `${cur.pulse_us} µs` : "off"}</b> on GPIO${sw.gpio}`];
    const leds = cur.leds || {};
    if ("yellow" in leds) facts.push(`Yellow LED <b>${cur.running ? "on" : "off"}</b>`);
    if ("red" in leds) facts.push(`Red LED <b>${cur.trip ? "flashing" : "off"}</b>`);
    if (cur.outputs_note) facts.push(esc(cur.outputs_note));
    if (cur.motion_error) facts.push(`<b>Servo error:</b> ${esc(cur.motion_error)}`);
    setHTML($(".facts", card), facts.map((x) => `<span>${x}</span>`).join(""));
  }

  function renderMotorEvents(s) {
    const n = s.alerts.length;
    $("#alerts-count").textContent = n ? "Since the dashboard started" : "";
    const key = JSON.stringify(s.alerts.map((a) => [a.id, a.end, a.reasons.length, a.reasons[0]]));
    if (key === alertsKey) return;
    alertsKey = key;
    const list = $("#alerts");
    if (!n) {
      list.innerHTML = `<li class="empty">Nothing yet. In Auto the fan starts when the humidity reaches ${s.current ? s.current.on_at : "the ON level"}%.</li>`;
      return;
    }
    list.innerHTML = s.alerts.map((a) => {
      const open = !a.end;
      const fresh = !seenAlerts.has(a.id) ? "" : " style=\"animation:none\"";
      let cls, kind, range;
      if (a.kind === "SHUTDOWN") {
        cls = "err"; kind = open ? "Shut down · active" : "Shut down";
        range = open ? `${when(a.start)} → now` : `${when(a.start)} – ${when(a.end)} · ${duration(a.start, a.end)}`;
      } else if (a.kind === "RUN") {
        cls = "run"; kind = open ? "Fan running" : "Fan ran";
        range = open ? `${when(a.start)} → now` : `${when(a.start)} – ${when(a.end)} · ${duration(a.start, a.end)}`;
      } else {
        cls = "note"; kind = "Change"; range = when(a.start);
      }
      return `<li class="${cls}${open ? " open" : ""}"${fresh}>
        <div class="when"><span>${range}</span><span class="kind">${kind}</span></div>
        ${a.reasons.map((r) => `<p class="reason">${esc(r)}</p>`).join("")}</li>`;
    }).join("");
    s.alerts.forEach((a) => seenAlerts.add(a.id));
  }

  function renderChecks(checks) {
    const key = JSON.stringify(checks);
    if (key === checksKey) return;
    checksKey = key;
    $("#checks").innerHTML = checks.map((c) => `<li class="ck ${c.state}"><i aria-hidden="true"></i>
      <div><p class="ck-label">${esc(c.label)}<span class="ck-tag">${CHECK_WORD[c.state] || ""}</span></p><p class="ck-now">${esc(c.now)}</p></div>
      <p class="ck-trip"><span>Trips at</span>${esc(c.trips)}</p></li>`).join("");
  }

  // ---------------------------------------------------------------- charts
  function drawCharts() {
    if (!meta) return;
    charts.forEach((c, i) => (c.motor ? drawMotorChart(c) : drawChart(c, i)));
  }

  function prepare(c) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = c.el.clientWidth;
    const h = c.el.clientHeight;
    if (!w || !h) return null;
    if (c.canvas.width !== Math.round(w * dpr) || c.canvas.height !== Math.round(h * dpr)) {
      c.canvas.width = Math.round(w * dpr);
      c.canvas.height = Math.round(h * dpr);
    }
    const ctx = c.canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const N = meta.chart_points;
    const L = 0, R = w - 54, T = 22, B = h - 22;
    const xAt = (idx) => L + ((idx + (N - points.length)) / Math.max(N - 1, 1)) * (R - L);
    return { ctx, w, h, N, L, R, T, B, xAt };
  }

  function waiting(g, text, short) {
    const { ctx, w, T, B } = g;
    ctx.fillStyle = "#8f8f92";
    ctx.font = "500 13px Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(ctx.measureText(text).width > w - 24 ? short : text, w / 2, (T + B) / 2);
  }

  function scaleY(g, lo, hi, minSpan) {
    if (hi - lo < minSpan) { const m = (hi + lo) / 2; lo = m - minSpan / 2; hi = m + minSpan / 2; }
    const pad = (hi - lo) * 0.12;
    lo -= pad; hi += pad;
    return { lo, hi, yAt: (v) => g.B - ((v - lo) / (hi - lo)) * (g.B - g.T) };
  }

  function gridlines(g, y, ch, keepClear = []) {  // keepClear: y positions whose labels win
    const { ctx, L, R } = g;
    ctx.font = `500 11px Inter, system-ui, sans-serif`;
    ctx.textBaseline = "middle";
    const ticks = niceTicks(y.lo, y.hi, 3);
    for (const t of ticks) {
      const py = y.yAt(t);
      ctx.strokeStyle = "rgba(255,255,255,0.05)";
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(L, Math.round(py) + 0.5); ctx.lineTo(R, Math.round(py) + 0.5); ctx.stroke();
      if (keepClear.some((k) => Math.abs(k - py) < 14)) continue;
      ctx.fillStyle = "#8f8f92";
      ctx.textAlign = "left";
      ctx.fillText(t.toFixed(stepDecimals(ticks)) + unitSuffix(ch), R + 8, py);
    }
  }

  function line(g, y, off) {
    const { ctx, xAt } = g;
    ctx.lineJoin = "round";
    ctx.lineWidth = 1.7;
    ctx.strokeStyle = "rgba(255,255,255,0.92)";
    ctx.beginPath();
    let open = false;
    points.forEach((p, idx) => {
      const v = p[off];
      if (v == null) { open = false; return; }
      const x = xAt(idx), py = y.yAt(v);
      if (open) ctx.lineTo(x, py); else ctx.moveTo(x, py);
      open = true;
    });
    ctx.stroke();
  }

  function newest(g, y, off) {
    const { ctx, xAt } = g;
    const lastIdx = points.length - 1;
    if (lastIdx < 0 || points[lastIdx][off] == null) return;
    const x = xAt(lastIdx), py = y.yAt(points[lastIdx][off]);
    const col = getComputedStyle(body).getPropertyValue("--state").trim() || "#00d4ff";
    ctx.fillStyle = col;
    ctx.globalAlpha = 0.25;
    ctx.beginPath(); ctx.arc(x, py, 8, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 1;
    ctx.beginPath(); ctx.arc(x, py, 3.5, 0, Math.PI * 2); ctx.fill();
  }

  function timeLabels(g) {
    const { ctx, xAt, N, L, R, h } = g;
    if (points.length < 2) return;
    ctx.fillStyle = "#8f8f92";
    ctx.textBaseline = "alphabetic";
    const n = Math.max(1, Math.min(4, Math.floor((R - L) / 120)));
    for (let j = 0; j <= n; j++) {
      // Labels sit at fixed fractions of the full window, so they never crowd while it fills up.
      const idx = Math.round((j / n) * (N - 1)) - (N - points.length);
      if (idx < 0) continue;
      const stamp = points[idx][1];
      const label = meta.kind === "replay" ? stamp.slice(5, 16).replace(" ", "  ") : stamp.slice(11, 19);
      ctx.textAlign = j === 0 ? "left" : j === n ? "right" : "center";
      ctx.fillText(label, Math.min(Math.max(xAt(idx), L), R), h - 4);
    }
  }

  function drawChart(c, i) {
    const g = prepare(c);
    if (!g) return;
    const { ctx, xAt, L, R, T, B } = g;
    const off = 3 + i * 4;  // per channel: value, band low, band high, flagged

    let lo = Infinity, hi = -Infinity;
    for (const p of points) {
      for (const v of [p[off], p[off + 1], p[off + 2]]) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    }
    if (lo === Infinity) {  // nothing to plot: only failed reads so far
      drawErrors(ctx, xAt, B);
      waiting(g, points.length ? "No values: every read in this window failed" : "Waiting for readings",
        points.length ? "Every read failed" : "Waiting");
      return;
    }
    const y = scaleY(g, lo, hi, { "%": 8, "°C": 2, "°F": 4 }[c.ch.unit] ?? 10);
    gridlines(g, y, c.ch);

    // Labelled anomaly windows (replays)
    if (meta.windows.length && points.length) {
      ctx.save();
      ctx.beginPath(); ctx.rect(L, T - 8, R - L, B - T + 8); ctx.clip();
      const pattern = hatch(ctx);
      for (const win of meta.windows) {
        let first = -1, last = -1;
        points.forEach((p, idx) => { if (p[1] >= win.start && p[1] <= win.end) { if (first < 0) first = idx; last = idx; } });
        if (first < 0) continue;
        const x0 = xAt(first), x1 = xAt(last);
        ctx.fillStyle = pattern;
        ctx.fillRect(x0, T - 8, Math.max(x1 - x0, 2), B - T + 8);
        ctx.fillStyle = "rgba(255,255,255,0.04)";
        ctx.fillRect(x0, T - 8, Math.max(x1 - x0, 2), B - T + 8);
        ctx.fillStyle = "#8f8f92";
        ctx.textAlign = "left";
        ctx.fillText(`Window ${meta.windows.indexOf(win) + 1}`, x0 + 6, T + 2);
      }
      ctx.restore();
    }

    // Expected range: average ± kσ
    let run = [];
    const flushBand = () => {
      if (run.length > 1) {
        ctx.beginPath();
        run.forEach(([x, , yh], j) => j ? ctx.lineTo(x, yh) : ctx.moveTo(x, yh));
        for (let j = run.length - 1; j >= 0; j--) ctx.lineTo(run[j][0], run[j][1]);
        ctx.closePath();
        ctx.fillStyle = "rgba(255,255,255,0.06)";
        ctx.fill();
        ctx.setLineDash([3, 4]);
        ctx.strokeStyle = "rgba(255,255,255,0.22)";
        ctx.lineWidth = 1;
        for (const k of [1, 2]) {
          ctx.beginPath();
          run.forEach((r, j) => j ? ctx.lineTo(r[0], r[k]) : ctx.moveTo(r[0], r[k]));
          ctx.stroke();
        }
        ctx.setLineDash([]);
      }
      run = [];
    };
    points.forEach((p, idx) => {
      if (p[off + 1] != null) run.push([xAt(idx), y.yAt(p[off + 1]), y.yAt(p[off + 2])]);
      else flushBand();
    });
    flushBand();

    line(g, y, off);

    // Flagged readings and sensor errors
    points.forEach((p, idx) => {
      const x = xAt(idx);
      if (p[off + 3] && p[off] != null) {
        ctx.fillStyle = "#f59e0b";
        ctx.beginPath(); ctx.arc(x, y.yAt(p[off]), points.length > 400 ? 2 : 3, 0, Math.PI * 2); ctx.fill();
      } else if (p[2] === "E") {
        ctx.fillStyle = "#fb7185";
        ctx.fillRect(x - 1, B - 10, 2, 12);
      }
    });

    newest(g, y, off);
    timeLabels(g);
  }

  // Motor points: [seq, time, state code, humidity, ON level, OFF level]. State codes: R running,
  // S standby, O off, X shut down, W waiting.
  function drawMotorChart(c) {
    const g = prepare(c);
    if (!g) return;
    const { ctx, xAt, N, L, R, T, B } = g;
    let lo = Infinity, hi = -Infinity;
    for (const p of points) for (const v of [p[3], p[4], p[5]]) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    if (lo === Infinity) return waiting(g, "Waiting for readings", "Waiting");
    const y = scaleY(g, lo, hi, 16);
    // The levels are labelled in the right margin, where the scale is; close ones are pushed apart.
    const lastP = points[points.length - 1];
    let yOn = y.yAt(lastP[4]), yOff = y.yAt(lastP[5]);
    if (yOff - yOn < 14) { const mid = (yOn + yOff) / 2; yOn = mid - 7; yOff = mid + 7; }
    gridlines(g, y, c.ch, [yOn, yOff]);

    // Fan running and shut down, as bands behind everything
    const half = (R - L) / Math.max(N - 1, 1) / 2;
    let start = 0;
    for (let idx = 1; idx <= points.length; idx++) {
      if (idx < points.length && points[idx][2] === points[start][2]) continue;
      const code = points[start][2];
      if (code === "R" || code === "X") {
        const x0 = Math.max(xAt(start) - half, L), x1 = Math.min(xAt(idx - 1) + half, R);
        ctx.fillStyle = code === "R" ? "rgba(0,212,255,0.10)" : "rgba(251,113,133,0.13)";
        ctx.fillRect(x0, T - 8, Math.max(x1 - x0, 1.5), B - T + 8);
      }
      start = idx;
    }

    // The ON and OFF levels (they can change, so they are drawn as steps)
    for (const [k, dash, alpha] of [[4, [6, 4], 0.6], [5, [2, 4], 0.4]]) {
      ctx.setLineDash(dash);
      ctx.strokeStyle = `rgba(255,255,255,${alpha})`;
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      let prev = null;
      points.forEach((p, idx) => {
        const x = xAt(idx), py = Math.round(y.yAt(p[k])) + 0.5;
        if (prev == null) ctx.moveTo(x, py); else { ctx.lineTo(x, prev); ctx.lineTo(x, py); }
        prev = py;
      });
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.font = "600 11px Inter, system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.fillText(`ON ${lastP[4]}%`, R + 6, yOn);
    ctx.fillStyle = "#8f8f92";
    ctx.fillText(`OFF ${lastP[5]}%`, R + 6, yOff);
    ctx.font = "500 11px Inter, system-ui, sans-serif";

    line(g, y, 3);
    newest(g, y, 3);
    timeLabels(g);
  }

  function drawErrors(ctx, xAt, B) {
    ctx.fillStyle = "#fb7185";
    points.forEach((p, idx) => { if (p[2] === "E") ctx.fillRect(xAt(idx) - 1, B - 10, 2, 12); });
  }

  let hatchCache = null;
  function hatch(ctx) {
    if (!hatchCache) {
      const p = document.createElement("canvas");
      p.width = p.height = 8;
      const g = p.getContext("2d");
      g.strokeStyle = "rgba(255,255,255,0.13)";
      g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(0, 8); g.lineTo(8, 0); g.stroke();
      hatchCache = p;
    }
    return ctx.createPattern(hatchCache, "repeat");
  }

  function niceTicks(lo, hi, count) {
    // The largest round step (1, 2 or 5 × 10^n) that still gives `count` labels or more.
    const mag = Math.pow(10, Math.floor(Math.log10((hi - lo) / count)) + 1);
    let out = [];
    for (const m of [5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01]) {
      const step = m * mag;
      out = [];
      for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
      if (out.length >= count) break;
    }
    return out;
  }
  function stepDecimals(ticks) {
    if (ticks.length < 2) return 0;
    const s = Math.abs(ticks[1] - ticks[0]);
    return s >= 0.999 ? 0 : s >= 0.0999 ? 1 : 2;
  }

  // ---------------------------------------------------------------- actions
  async function post(path, data) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
    return r.json();
  }

  let toastTimer = 0;
  function toast(html, ms = 6000) {
    const t = $("#toast");
    t.innerHTML = html;
    t.hidden = false;
    t.style.animation = "none"; void t.offsetWidth; t.style.animation = "";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, ms);
  }

  async function doExport(range) {
    togglePop(false);
    toast("Preparing the CSV…", 20000);
    try {
      const r = await fetch(`/api/export.csv?stream=${encodeURIComponent(streamKey)}&range=${range}`, { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      const rows = Number(r.headers.get("X-Rows") || 0);
      const saved = r.headers.get("X-Saved-To") || "";
      const blob = await r.blob();
      if (!KIOSK) {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = saved.split(/[\\/]/).pop() || "vizion.csv";
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      }
      const what = isMotor() ? "rows" : "readings";
      toast(rows ? `<b>${rows.toLocaleString()} ${what}</b> exported${KIOSK ? "" : " and downloaded"}. Saved on the Pi as <code>${esc(saved)}</code>`
        : "Nothing recorded in that range yet.", 9000);
    } catch {
      toast("The export failed: the dashboard server did not answer.");
    }
  }

  function togglePop(show) {
    const pop = $("#export-pop");
    const open = show ?? pop.hidden;
    pop.hidden = !open;
    $("#export-btn").setAttribute("aria-expanded", String(open));
  }

  async function fanAction(data, quiet) {
    try {
      const r = await post("/api/fan", data);
      if (!quiet || !r.ok) toast(esc(r.message), r.ok ? 5000 : 8000);
    } catch {
      toast("The dashboard server did not answer.");
    }
    poll();
  }

  function stepLevel(which, d) {
    if (!state || !state.current) return;
    const cur = levels(state.current);
    const next = { on: cur.on, off: cur.off };
    next[which] += d;
    const L = meta.levels;
    if (next.on > L.on_max || next.on < L.on_min || next.off < L.off_min || next.on - next.off < L.min_gap) return;
    levelEdit = { ...next, t: performance.now() };
    renderHumidityCard(state.current);
    fanAction({ action: "levels", on_at: next.on, off_at: next.off }, true);
  }

  document.addEventListener("click", async (e) => {
    const t = e.target.closest("button");
    if (!t) { if (!e.target.closest(".export-pop")) togglePop(false); return; }
    if (t.dataset.stream) switchStream(t.dataset.stream);
    else if (t.id === "export-btn") togglePop();
    else if (t.dataset.range) doExport(t.dataset.range);
    else if (t.dataset.mode) fanAction({ action: "mode", mode: t.dataset.mode });
    else if (t.dataset.fan) fanAction({ action: t.dataset.fan });
    else if (t.dataset.level) stepLevel(t.dataset.level, Number(t.dataset.d));
    else if (t.dataset.action === "pause") {
      const r = await post("/api/pause", { stream: streamKey, paused: !(state && state.paused) });
      toast(esc(r.message), 4000);
      poll();
    } else if (t.dataset.action === "reset") {
      clearTimeout(resetTimer);
      if (!t.classList.contains("confirm")) {
        t.classList.add("confirm");
        t.textContent = "Tap again to reset";
        resetTimer = setTimeout(() => { t.classList.remove("confirm"); t.textContent = "Reset readings"; }, 3000);
      } else {
        t.classList.remove("confirm");
        t.textContent = "Reset readings";
        const r = await post("/api/reset", { stream: streamKey });
        toast(esc(r.message), 6000);
        poll();
      }
    } else if (t.dataset.window != null) {
      const r = await post("/api/replay", { stream: streamKey, window: Number(t.dataset.window) });
      toast(esc(r.message), 3500);
      since = 0; points = [];
      poll();
    }
    if (!t.closest(".export-pop") && t.id !== "export-btn") togglePop(false);
  });

  // Kiosk: hold EXIT for a second, or press Q or Esc
  function quit() { post("/api/quit", {}).catch(() => {}); }
  if (KIOSK) {
    const exit = $("#exit-btn");
    exit.hidden = false;
    let holdTimer = 0;
    const start = () => { exit.classList.add("holding"); holdTimer = setTimeout(quit, 1000); };
    const stop = () => { exit.classList.remove("holding"); clearTimeout(holdTimer); };
    exit.addEventListener("pointerdown", start);
    for (const ev of ["pointerup", "pointerleave", "pointercancel"]) exit.addEventListener(ev, stop);
    body.style.cursor = "none";
    let hide = 0;
    addEventListener("pointermove", () => { body.style.cursor = ""; clearTimeout(hide); hide = setTimeout(() => { body.style.cursor = "none"; }, 3000); });
  }
  addEventListener("keydown", (e) => {
    if (e.target.closest && e.target.closest("input, textarea")) return;
    if (KIOSK && (e.key === "q" || e.key === "Q" || e.key === "Escape")) return quit();
    if (e.key === "Escape") return togglePop(false);
    const n = Number(e.key);
    if (n >= 1 && n <= 9) {
      const b = document.querySelectorAll("#streams button")[n - 1];
      if (b) switchStream(b.dataset.stream);
    } else if (e.key === "e" || e.key === "E") togglePop();
    else if (e.key === "p" || e.key === "P") { const b = $('[data-action="pause"]'); if (b) b.click(); }
  });

  // ---------------------------------------------------------------- the portfolio's touches
  function tilt() {
    if (LITE || TOUCH || REDUCED) return;
    for (const card of document.querySelectorAll(".metric")) {
      if (card.dataset.tilt) continue;
      card.dataset.tilt = "1";
      card.addEventListener("mousemove", (e) => {
        if (e.target.closest("button")) { card.style.transform = ""; return; }  // keep buttons still under the pointer
        const r = card.getBoundingClientRect();
        const rx = ((e.clientY - r.top) / r.height - 0.5) * -5;
        const ry = ((e.clientX - r.left) / r.width - 0.5) * 5;
        card.style.transform = `perspective(1000px) rotateX(${rx}deg) rotateY(${ry}deg) translateY(-4px)`;
      });
      card.addEventListener("mouseleave", () => { card.style.transform = ""; });
    }
  }

  function loader() {
    const el = $("#loader");
    let seen = false;
    try { seen = sessionStorage.getItem("vizion-sense-loader") === "1"; } catch { /* ignore */ }
    if (seen || REDUCED) { el.remove(); return; }
    const text = $(".loader-text", el);
    const chars = [...text.textContent];
    text.replaceChildren(...chars.map((c, i) => {
      const s = document.createElement("span");
      s.className = "char";
      s.textContent = c === " " ? " " : c;
      s.style.animationDelay = `${i * 0.05}s`;
      return s;
    }));
    setTimeout(() => {
      el.classList.add("done");
      try { sessionStorage.setItem("vizion-sense-loader", "1"); } catch { /* ignore */ }
      setTimeout(() => el.remove(), 800);
    }, chars.length * 50 + 650);
  }

  // The drifting constellation behind everything. Its links take the colour of the state.
  function constellation() {
    const canvas = $("#bg");
    const ctx = canvas.getContext("2d");
    let w = 0, h = 0;
    const count = LITE ? 60 : innerWidth < 768 ? 28 : 72;
    const dotAlpha = LITE ? 0.28 : 0.16;
    const reach = LITE ? 160 : 130;
    const linkAlpha = (d) => (LITE ? 0.24 - d / 700 : 0.16 - d / 850);
    const parts = [];
    const mouse = { x: null, y: null };
    function resize() {
      w = innerWidth; h = innerHeight;
      canvas.width = w; canvas.height = h;
    }
    resize();
    addEventListener("resize", () => { resize(); drawCharts(); });
    for (let i = 0; i < count; i++) {
      parts.push({ x: Math.random() * w, y: Math.random() * h, vx: (Math.random() - 0.5) * 0.45, vy: (Math.random() - 0.5) * 0.45, r: Math.random() * 1.5 + 0.5 });
    }
    if (!TOUCH) {
      addEventListener("mousemove", (e) => { mouse.x = e.clientX; mouse.y = e.clientY; });
      addEventListener("mouseout", () => { mouse.x = mouse.y = null; });
    }
    const tint = () => body.classList.contains("is-anomaly") ? "245,158,11" : body.classList.contains("is-error") ? "251,113,133" : "255,255,255";
    let last = 0;
    const frameMs = LITE ? 1000 / 24 : 0;
    function frame(t) {
      if (!REDUCED) requestAnimationFrame(frame);
      if (document.hidden || t - last < frameMs) return;
      last = t;
      ctx.clearRect(0, 0, w, h);
      const rgb = tint();
      ctx.lineWidth = 0.5;
      for (let i = 0; i < parts.length; i++) {
        const p = parts[i];
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0 || p.x > w) p.vx *= -1;
        if (p.y < 0 || p.y > h) p.vy *= -1;
        ctx.fillStyle = `rgba(255,255,255,${dotAlpha})`;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill();
        if (mouse.x != null) {
          const d = Math.hypot(mouse.x - p.x, mouse.y - p.y);
          if (d < 150) {
            ctx.strokeStyle = `rgba(0,212,255,${0.2 - d / 750})`;
            ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(mouse.x, mouse.y); ctx.stroke();
          }
        }
        for (let j = i + 1; j < parts.length; j++) {
          const q = parts[j];
          const d = Math.hypot(p.x - q.x, p.y - q.y);
          if (d < reach) {
            ctx.strokeStyle = `rgba(${rgb},${linkAlpha(d)})`;
            ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke();
          }
        }
      }
    }
    if (REDUCED) { frame(1e9); return; }
    requestAnimationFrame(frame);
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  if ("ResizeObserver" in window) new ResizeObserver(() => drawCharts()).observe($("#charts"));
  loader();
  constellation();
  poll();
})();
