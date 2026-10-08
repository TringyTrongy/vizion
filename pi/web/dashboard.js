// Vizion dashboard page. Pulls frames from dashboard.py one at a time (newest only, so the picture
// never lags behind), draws them with the boxes of that same frame, and fills in the sheet.
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
  const MAX_REF_ROWS = 5;
  const HOLD_MS = 1000;
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');

  const sheet = $('sheet');
  const view = $('view');
  const canvas = $('frame');
  const ctx = canvas.getContext('2d', { alpha: false });
  const overlay = $('overlay');
  const marks = $('marks');
  const pulses = $('pulses');
  const s1 = $('s1');
  const measure = document.createElement('canvas').getContext('2d');

  let seq = 0;
  let current = null;        // last state from the server
  let pendingSwitch = null;  // detection state requested but not confirmed yet
  let lastResults = null;
  let bitmap = null;
  let frameW = 610;
  let frameH = 480;
  let stopped = false;

  // ------------------------------------------------------------------ small helpers

  const cache = new WeakMap();
  function text(el, value) {
    if (cache.get(el) !== value) { el.textContent = value; cache.set(el, value); }
  }
  function attr(el, name, value) {
    if (el.getAttribute(name) !== value) el.setAttribute(name, value);
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }
  const pct = (conf) => `${Math.round(conf * 100)}%`;
  const two = (n) => String(n).padStart(2, '0');
  const hhmm = (ms) => { const d = new Date(ms); return `${two(d.getHours())}:${two(d.getMinutes())}`; };

  async function post(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    return res.json();
  }

  // ------------------------------------------------------------------ the picture

  function sizeCanvas() {
    const r = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(r.width * dpr));
    const h = Math.max(1, Math.round(r.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      if (bitmap) drawFrame();
    }
  }

  function drawFrame() {
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  }

  async function frameLoop() {
    for (;;) {
      if (stopped) return;
      try {
        // The server answers within ~1 s even with no new frame; longer means it is stuck.
        const res = await fetch(`/frame?after=${seq}`, { cache: 'no-store', signal: AbortSignal.timeout(4000) });
        const header = res.headers.get('X-Vizion');
        if (res.status === 200) {
          const next = await createImageBitmap(await res.blob());
          if (bitmap) bitmap.close();
          bitmap = next;
          drawFrame();
        }
        if (header) {
          const state = JSON.parse(header);
          seq = state.seq;
          render(state);
        }
        setLink('ok');
      } catch (err) {
        if (stopped) return;
        setLink('lost');
        await new Promise((r) => setTimeout(r, 1000));
      }
    }
  }

  function setLink(kind) {
    attr(sheet, 'data-link', kind);
    $('linkBanner').hidden = kind === 'ok';
  }

  // ------------------------------------------------------------------ render the state

  function render(s) {
    current = s;
    if (s.camera.size) [frameW, frameH] = s.camera.size;
    attr(overlay, 'viewBox', `0 0 ${frameW} ${frameH}`);
    const on = pendingSwitch ?? s.detection.on;
    const working = on && s.model.state === 'ready';

    renderChain(s, on);
    renderView(s, on);
    renderMarks(s, working);
    renderRulers(working && s.camera.state === 'ok' ? s.parts : []);
    renderBom(s, on);
    renderUnknown(s);
    renderLeds(s);
    renderRefs(s, on);
    renderModelLabel(s.model.label);
    renderThreshold(s.detection);
    spawnPulses(s, working);
  }

  // 'YOLO26n NCNN 480' -> YOLO26n, with the format and input size underneath
  function renderModelLabel(label) {
    const el = $('modelLabel');
    if (cache.get(el) === label) return;
    cache.set(el, label);
    const [arch, ...rest] = label.split(' ');
    const size = rest.length > 1 ? `${rest.slice(0, -1).join(' ')} · ${rest[rest.length - 1]} PX` : rest.join(' ');
    el.innerHTML = `${esc(arch)}<small>${esc(size)}</small>`;
  }

  // Parts appear at the threshold and stay until they fall below hide_below (no blinking).
  function renderThreshold(d) {
    text($('threshold'), pct(d.threshold));
    text($('noteShow'), pct(d.threshold));
    text($('noteHide'), pct(d.hide_below));
  }

  function renderChain(s, on) {
    const cam = s.camera.state;
    attr($('cameraBlock'), 'data-state', cam === 'ok' ? 'ok' : cam === 'connecting' ? 'busy' : 'fault');
    const test = s.camera.test_image;
    text($('cameraState'), test ? 'TEST IMAGES'
      : { ok: 'CONNECTED', connecting: 'CONNECTING', lost: 'NO SIGNAL', stalled: 'FROZEN' }[cam] || cam.toUpperCase());
    text($('cameraInfo'), test || (cam === 'ok' ? `${s.camera.fps.toFixed(1)} FPS` : 'RETRYING'));

    attr(s1, 'aria-checked', String(on));
    attr(s1, 'aria-label', `Detection ${on ? 'on' : 'off'}. Press to turn it ${on ? 'off' : 'on'}.`);
    text($('s1State'), on ? 'ON' : 'OFF');

    const m = s.model.state;
    let blockState = 'ok';
    let label = 'READY';
    let info = s.model.ms ? `${s.model.ms} MS / FRAME` : ' ';
    if (!on) { blockState = 'idle'; label = 'IDLE'; info = 'DETECTION OFF'; }
    else if (m === 'loading') { blockState = 'busy'; label = 'LOADING'; info = 'ABOUT 15 S'; }
    else if (m === 'restarting') { blockState = 'busy'; label = 'RESTARTING'; info = 'AFTER A FAULT'; }
    else if (m === 'failed') { blockState = 'fault'; label = 'FAILED'; info = 'SEE PARTS TABLE'; }
    attr($('modelBlock'), 'data-state', blockState);
    text($('modelState'), label);
    text($('modelInfo'), info);
  }

  function renderView(s, on) {
    const cam = s.camera.state;
    attr(view, 'data-camera', cam);
    if (cam !== 'ok') {
      text($('viewTitle'), {
        connecting: 'CONNECTING TO THE CAMERA',
        lost: 'NO CAMERA SIGNAL',
        stalled: 'THE CAMERA PICTURE IS FROZEN',
      }[cam] || 'CAMERA PROBLEM');
      text($('viewDetail'), cam === 'connecting'
        ? (s.camera.detail || 'Starting the camera')
        : `${s.camera.detail} Vizion keeps trying to reconnect.`);
    }
    const stamp = $('stamp');
    text(stamp, s.camera.test_image ? 'TEST IMAGES · NOT THE LIVE CAMERA' : 'DETECTION OFF · CAMERA ONLY');
    stamp.hidden = cam !== 'ok' || (on && !s.camera.test_image);
  }

  function flagWidth(label, size) {
    measure.font = `${size}px osifont, sans-serif`;
    return measure.measureText(label).width;
  }

  function renderMarks(s, working) {
    if (!working || s.camera.state !== 'ok') {
      if (marks.firstChild) marks.replaceChildren();
      return;
    }
    const fs = Math.round(frameH * 0.027);  // flag lettering, in frame pixels
    const fh = Math.round(fs * 1.55);
    const pad = Math.round(fs * 0.45);
    // Boxes first, then every flag on top, so a neighbour's box never hides a label.
    let boxes = '';
    let flags = '';
    for (const p of s.parts) {
      const [x1, y1, x2, y2] = p.box;
      const label = `${p.ref}  ${pct(p.conf)}`;
      const fw = Math.ceil(flagWidth(label, fs)) + pad * 2;
      const fy = y1 - fh - 2 >= 0 ? y1 - fh : y2;
      const fx = Math.min(Math.max(0, x1), frameW - fw);
      const cls = `mk-${esc(p.cls)}`;
      boxes += `<g class="${cls}">`
        + `<rect class="mk-keyline" x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}"/>`
        + `<rect class="mk-box" x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}"/></g>`;
      flags += `<g class="${cls}">`
        + `<rect class="mk-flag-keyline" x="${fx - 1.5}" y="${fy - 1.5}" width="${fw + 3}" height="${fh + 3}"/>`
        + `<rect class="mk-flag" x="${fx}" y="${fy}" width="${fw}" height="${fh}"/>`
        + `<text class="mk-text" x="${fx + pad}" y="${fy + fh * 0.74}" font-size="${fs}">${esc(label)}</text></g>`;
    }
    for (const [x1, y1, x2, y2] of s.unknown.boxes) {
      const fw = Math.ceil(flagWidth('?', fs)) + pad * 2;
      const fy = y1 - fh - 2 >= 0 ? y1 - fh : y2;
      boxes += '<g>'
        + `<rect class="mk-unknown-keyline" x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}"/>`
        + `<rect class="mk-unknown" x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}"/></g>`;
      flags += '<g>'
        + `<rect class="mk-flag-keyline" x="${x1 - 1.5}" y="${fy - 1.5}" width="${fw + 3}" height="${fh + 3}"/>`
        + `<rect class="mk-unknown-flag" x="${x1}" y="${fy}" width="${fw}" height="${fh}"/>`
        + `<text class="mk-text" x="${x1 + pad}" y="${fy + fh * 0.74}" font-size="${fs}">?</text></g>`;
    }
    const svg = boxes + flags;
    if (cache.get(marks) !== svg) {
      marks.innerHTML = svg;
      cache.set(marks, svg);
    }
  }

  function renderRulers(parts) {
    const zones = new Set();
    for (const p of parts) { zones.add(p.zone[0]); zones.add(p.zone[1]); }
    for (const el of document.querySelectorAll('.ruler span')) {
      el.classList.toggle('on', zones.has(el.dataset.zone));
    }
  }

  function renderBom(s, on) {
    const counts = on ? s.counts : null;
    let why = 'DETECTION OFF';
    if (on && s.model.state !== 'ready') why = s.model.state === 'failed' ? 'MODEL FAILED' : 'WAITING FOR MODEL';
    if (on && s.camera.state !== 'ok') why = 'NO CAMERA';
    const live = counts && s.camera.state === 'ok';
    for (const [cls, row] of [['resistor', $('rowResistor')], ['capacitor', $('rowCapacitor')]]) {
      const n = live ? counts[cls] : null;
      attr(row, 'data-present', n == null ? 'unknown' : n > 0 ? 'yes' : 'no');
      text(row.querySelector('.qty-num'), n == null ? '–' : String(n));
      text(row.querySelector('.presence-text'), n == null ? why : n > 0 ? 'PRESENT' : 'NOT PRESENT');
      const refs = live ? s.parts.filter((p) => p.cls === cls).map((p) => p.ref).join('  ') : '';
      text(row.querySelector('.designators'), refs || ' ');
    }
    const total = $('rowTotal');
    attr(total, 'data-known', live ? 'yes' : 'no');
    text(total.querySelector('.qty-num'), live ? String(counts.total) : '–');
  }

  function renderUnknown(s) {
    const u = s.unknown;
    const row = $('rowUnknown');
    attr(row, 'data-state', u.state);
    const learned = u.learned_at ? hhmm(u.learned_at) : null;
    const [label, detail] = {
      not_learned: ['NOT LEARNED', 'Clear the table, then learn it so Vizion can spot other objects.'],
      none: ['NOT PRESENT', `Nothing else on the table. Empty table learned at ${learned}.`],
      present: ['PRESENT', 'Something here is not a resistor or capacitor: see the ? outline.'],
      relearn: ['RE-LEARN', `The view changed a lot since ${learned}. Clear the table and re-learn.`],
      off: ['OFF', 'Turn detection on to check the table.'],
      no_camera: ['NO CAMERA', 'Waiting for the camera picture.'],
      waiting: ['WAITING', 'Starts when the model is ready.'],
    }[u.state] || [u.state.toUpperCase(), ''];
    text($('unknownState'), label);
    const detailEl = $('unknownDetail');
    if (s.notice) {
      text(detailEl, s.notice.text);
      detailEl.className = `unknown-detail ${s.notice.kind === 'ok' ? 'is-ok' : 'is-error'}`;
    } else {
      text(detailEl, detail);
      detailEl.className = 'unknown-detail';
    }
    const learn = $('learn');
    if (!learn.dataset.busy) {
      text(learn, learned ? 'RE-LEARN EMPTY TABLE' : 'LEARN EMPTY TABLE');
      learn.disabled = !(s.detection.on && s.model.state === 'ready' && s.camera.state === 'ok');
    }
  }

  // The indicator LEDs: mirror each real LED, and offer the blink count when there is something to count.
  function renderLeds(s) {
    const l = s.leds;
    for (const [cls, id] of [['resistor', 'ledResistor'], ['capacitor', 'ledCapacitor']]) {
      const el = $(id);
      const led = l.leds.find((x) => x.cls === cls);
      el.hidden = !led;
      if (!led) continue;
      attr(el, 'data-ready', String(l.available));
      attr(el, 'data-lit', String(l.available && led.lit));
      text(el.querySelector('.led-ref'), `${led.ref} ${led.color.toUpperCase()}`);
    }
    const blink = $('blink');
    if (blinkMessage) return;
    const colour = (cls) => (l.leds.find((x) => x.cls === cls) || { color: cls }).color.toUpperCase();
    let label = 'BLINK COUNT ON LEDS';
    if (!l.leds.length) label = 'NO LEDS SET UP';
    else if (!l.available) label = 'LEDS NOT AVAILABLE';
    else if (l.count) {
      label = 'BLINKING ' + Object.entries(l.count.counts).filter(([, n]) => n > 0)
        .map(([cls, n]) => `${colour(cls)} ×${n}`).join(' · ');
    }
    text(blink, label);
    blink.disabled = !(l.available && s.counts && s.counts.total > 0);
  }

  function renderRefs(s, on) {
    let message = null;
    let error = false;
    if (!on) message = 'Detection is off. The camera keeps running; press S1 to turn detection back on.';
    else if (s.camera.state !== 'ok') { message = 'No camera picture, so nothing can be detected.'; error = true; }
    else if (s.model.state === 'failed') { message = s.model.detail; error = true; }
    else if (s.model.state === 'restarting') message = `${s.model.detail}. Restarting the model.`;
    else if (s.model.state !== 'ready') message = 'Loading the model. Detection starts in a few seconds.';
    else if (!s.parts.length) message = 'No resistor or capacitor detected.';

    let html;
    let used = 1;
    if (message) {
      html = `<tr class="empty${error ? ' is-error' : ''}"><td colspan="4">${esc(message)}</td></tr>`;
    } else {
      const rows = s.parts.length > MAX_REF_ROWS ? s.parts.slice(0, MAX_REF_ROWS - 1) : s.parts;
      html = rows.map((p) => `<tr data-cls="${esc(p.cls)}"><td class="ref">${esc(p.ref)}</td>`
        + `<td class="num">${pct(p.conf)}</td><td>${esc(p.zone)}</td><td>${esc(p.where)}</td></tr>`).join('');
      if (rows.length < s.parts.length) {
        const rest = s.parts.slice(rows.length).map((p) => p.ref).join(', ');
        html += `<tr class="more"><td colspan="4">+ ${s.parts.length - rows.length} more: ${esc(rest)}</td></tr>`;
      }
      used = Math.min(s.parts.length, MAX_REF_ROWS);
    }
    // Blank ruled rows fill the table, like an unfilled parts list on a drawing.
    for (let i = used; i < MAX_REF_ROWS; i++) html += '<tr><td></td><td></td><td></td><td></td></tr>';
    html += '<tr class="filler"><td></td><td></td><td></td><td></td></tr>';
    const body = $('refRows');
    if (cache.get(body) !== html) { body.innerHTML = html; cache.set(body, html); }
  }

  // One pulse along the S1 wire per detection result: the pulse rate is the real detection rate.
  function spawnPulses(s, working) {
    const results = s.detection.results;
    const fresh = lastResults == null ? 0 : results - lastResults;
    lastResults = results;
    if (!working || fresh <= 0 || reduceMotion.matches || document.hidden) return;
    if (pulses.childElementCount >= 8) return;
    const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    dot.setAttribute('class', 'pulse');
    dot.setAttribute('cx', '0');
    dot.setAttribute('cy', '40');
    dot.setAttribute('r', '3.5');
    dot.addEventListener('animationend', () => dot.remove());
    pulses.appendChild(dot);
  }

  // ------------------------------------------------------------------ controls

  async function setDetection(on) {
    pendingSwitch = on;
    if (current) render(current);
    try {
      await post('/api/detection', { on });
    } catch (err) {
      // the connection banner already says what is wrong
    } finally {
      pendingSwitch = null;
    }
  }

  async function learnEmptyTable() {
    const learn = $('learn');
    if (learn.disabled || learn.dataset.busy) return;
    learn.dataset.busy = '1';
    learn.disabled = true;
    text(learn, 'LEARNING…');
    try {
      await post('/api/empty-table', { action: 'learn' });
    } catch (err) {
      // shown by the connection banner
    } finally {
      delete learn.dataset.busy;
      if (current) renderUnknown(current);
    }
  }

  let blinkMessage = null;
  async function blinkCounts() {
    const blink = $('blink');
    if (blink.disabled) return;
    try {
      const res = await post('/api/leds', { action: 'blink' });
      if (!res.ok) {
        blinkMessage = res.message;
        text(blink, res.message.toUpperCase());
        setTimeout(() => { blinkMessage = null; if (current) renderLeds(current); }, 2500);
      }
    } catch (err) {
      // the connection banner already says what is wrong
    }
  }

  async function quit() {
    if (stopped) return;
    stopped = true;
    text($('linkTitle'), 'VIZION HAS STOPPED');
    text($('linkDetail'), 'Start it again with ./run_dashboard.sh or the Vizion Dashboard icon.');
    setLink('stopped');
    try { await post('/api/quit'); } catch (err) { /* already gone */ }
  }

  s1.addEventListener('click', () => {
    const on = pendingSwitch ?? (current ? current.detection.on : true);
    setDetection(!on);
  });
  $('learn').addEventListener('click', learnEmptyTable);
  $('blink').addEventListener('click', blinkCounts);

  // Exit needs a 1 s press so a visitor tapping the screen can't close the exhibit by accident.
  const exit = $('exit');
  let holdTimer = null;
  function cancelHold() {
    clearTimeout(holdTimer);
    holdTimer = null;
    exit.classList.remove('holding');
  }
  exit.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    exit.setPointerCapture(e.pointerId);
    exit.classList.add('holding');
    holdTimer = setTimeout(() => { cancelHold(); quit(); }, HOLD_MS);
  });
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) exit.addEventListener(type, cancelHold);
  exit.addEventListener('click', (e) => { if (e.detail === 0) quit(); });  // keyboard activation
  exit.addEventListener('contextmenu', (e) => e.preventDefault());

  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.altKey || e.metaKey || e.repeat) return;
    const key = e.key.toLowerCase();
    if (key === 'd') s1.click();
    else if (key === 'l') learnEmptyTable();
    else if (key === 'b') blinkCounts();
    else if (key === 'q' || key === 'escape') quit();
  });

  // Hide the pointer when nobody is using it, so it doesn't sit on the exhibit screen.
  let idleTimer = null;
  function wake() {
    document.body.classList.remove('idle');
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => document.body.classList.add('idle'), 4000);
  }
  for (const type of ['pointermove', 'pointerdown', 'keydown']) document.addEventListener(type, wake, { passive: true });
  wake();

  // ------------------------------------------------------------------ clock

  function tick() {
    const d = new Date();
    text($('clock'), `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`);
    text($('date'), `${two(d.getDate())} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`);
    $('clock').dateTime = d.toISOString();
    setTimeout(tick, 1000 - d.getMilliseconds() + 5);
  }

  // ------------------------------------------------------------------ start

  new ResizeObserver(sizeCanvas).observe(canvas);
  sizeCanvas();
  tick();
  document.fonts.ready.then(() => frameLoop());
})();
