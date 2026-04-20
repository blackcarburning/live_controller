/**
 * show-sync client — WebSocket-driven effect renderer.
 *
 * Supports two playback modes:
 *
 *   1. Legacy cue mode  (show file with flat "effects" list)
 *      Server sends individual "cue" messages; each triggers a one-shot
 *      render call (solid colour, fade in/out, text).
 *
 *   2. Timeline mode  (show file with "tracks" / "clips" structure, v2)
 *      Server sends a "show_load" message carrying the full show JSON,
 *      followed by a "show_start" message with the authoritative server
 *      timestamp at which timeline time-zero begins.  The client then runs
 *      its own rAF loop, evaluating active clips at each frame and
 *      compositing the result (solid layers below text layers).
 */

const sessionId = document.body.dataset.sessionId;
const statusEl  = document.getElementById('status');
const displayEl = document.getElementById('display');
const textEl    = document.getElementById('text-overlay');

let ws             = null;
let reconnectTimer = null;
let syncInterval   = null;
let fadeTimer      = null;

let syncSamples = [];
let clockOffset = 0;   // estimated (local → server) clock delta in seconds

// ── Timeline state ────────────────────────────────────────────────────────────
let tlShow      = null;   // loaded show JSON (v2 with "tracks")
let tlStartTime = null;   // server timestamp when show time = 0
let tlRafId     = null;   // requestAnimationFrame handle

// ── Clock helpers ─────────────────────────────────────────────────────────────

function nowSeconds() {
  return Date.now() / 1000;
}

function serverNow() {
  return nowSeconds() + clockOffset;
}

function wsUrl() {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${window.location.host}/ws/${sessionId}`;
}

function cleanupTimers() {
  if (syncInterval) { clearInterval(syncInterval); syncInterval = null; }
}

function scheduleReconnect(delayMs) {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => { reconnectTimer = null; connect(); }, delayMs);
}

function median(values) {
  if (!values.length) return 0;
  const s   = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function recomputeClockOffset() {
  if (!syncSamples.length) return;
  const best    = [...syncSamples].sort((a, b) => a.rtt - b.rtt).slice(0, 5);
  clockOffset   = median(best.map(s => s.offset));
  const minRtt  = best[0].rtt;
  statusEl.textContent = `Connected \u2022 synced (${Math.round(minRtt * 1000)} ms RTT)`;
}

function syncOnce() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: 'sync', t0: nowSeconds() }));
}

// ── Legacy effect rendering (cue mode) ───────────────────────────────────────

function clearEffect() {
  if (fadeTimer) { clearTimeout(fadeTimer); fadeTimer = null; }
  displayEl.style.transition = 'none';
  displayEl.style.background = '#000000';
  displayEl.style.opacity    = '1';
  textEl.style.display       = 'none';
  textEl.textContent         = '';
  textEl.style.opacity       = '1';
}

function runEffect(msg) {
  const effect     = msg.effect || 'solid';
  const params     = msg.params || {};
  const durationMs = (msg.duration || 1.0) * 1000;
  const color      = params.color || '#ff0000';

  clearEffect();

  switch (effect) {
    case 'solid':
      displayEl.style.transition = 'none';
      displayEl.style.background = color;
      fadeTimer = setTimeout(clearEffect, durationMs);
      break;

    case 'fade_in':
      // Start black, transition to colour over the duration.
      displayEl.style.transition = 'none';
      displayEl.style.background = '#000000';
      // Double rAF ensures the browser paints black before the transition starts.
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          displayEl.style.transition = `background-color ${durationMs}ms linear`;
          displayEl.style.background = color;
          fadeTimer = setTimeout(clearEffect, durationMs + 100);
        });
      });
      break;

    case 'fade_out':
      // Start at colour, transition to black over the duration.
      displayEl.style.transition = 'none';
      displayEl.style.background = color;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          displayEl.style.transition = `background-color ${durationMs}ms linear`;
          displayEl.style.background = '#000000';
          fadeTimer = setTimeout(clearEffect, durationMs + 100);
        });
      });
      break;

    case 'text':
      textEl.textContent    = params.text  || '';
      textEl.style.color    = color;
      textEl.style.fontSize = (params.size || 5) + 'vmin';
      textEl.style.display  = 'flex';
      fadeTimer = setTimeout(clearEffect, durationMs);
      break;

    default:
      // Unknown effect type — fall back to a solid colour flash.
      displayEl.style.transition = 'none';
      displayEl.style.background = color;
      fadeTimer = setTimeout(clearEffect, durationMs);
      break;
  }
}

// ── Legacy scheduling (cue mode) ─────────────────────────────────────────────

function scheduleCue(msg) {
  const localTarget = msg.server_start_time - clockOffset;

  function check() {
    const now = nowSeconds();
    if (now >= localTarget) { runEffect(msg); return; }
    const remainingMs = (localTarget - now) * 1000;
    if (remainingMs > 30) {
      setTimeout(check, remainingMs - 20);
    } else {
      requestAnimationFrame(check);
    }
  }
  check();
}

// ── Timeline rendering ────────────────────────────────────────────────────────

function _clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

function compositeTimeline(showTime) {
  /**
   * Evaluate all timeline clips at `showTime` seconds and update the DOM.
   * Tracks are sorted by layer ascending: higher-layer tracks render on top.
   */
  const sorted = [...tlShow.tracks].sort((a, b) => a.layer - b.layer);

  let bg = null, bgOp = 0;
  let txt = null, txtColor = '#fff', txtOp = 0, txtSz = 5;

  for (const track of sorted) {
    for (const clip of track.clips) {
      if (showTime < clip.start || showTime >= clip.start + clip.duration) continue;

      const pos = showTime - clip.start;
      const dur = clip.duration;
      const fi  = clip.fade_in  || 0;
      const fo  = clip.fade_out || 0;

      let op = 1;
      if (fi > 0 && pos < fi)       op *= pos / fi;
      if (fo > 0 && pos > dur - fo) op *= (dur - pos) / fo;
      op = _clamp(op, 0, 1);

      const type   = clip.type;
      const params = clip.params || {};

      if (type === 'color' || type === 'fade_in' || type === 'fade_out') {
        bg   = params.color || '#ff0000';
        bgOp = op;
      } else if (type === 'text') {
        txt      = params.text  || '';
        txtColor = params.color || '#ffffff';
        txtSz    = params.size  || 5;
        txtOp    = op;
      }
    }
  }

  // Solid / colour layer
  if (bg && bgOp > 0) {
    displayEl.style.transition = 'none';
    displayEl.style.background = bg;
    displayEl.style.opacity    = bgOp;
  } else {
    displayEl.style.background = '#000';
    displayEl.style.opacity    = '1';
  }

  // Text layer (rendered on top via z-index in join.html)
  if (txt !== null && txtOp > 0) {
    textEl.textContent    = txt;
    textEl.style.color    = txtColor;
    textEl.style.fontSize = txtSz + 'vmin';
    textEl.style.opacity  = txtOp;
    textEl.style.display  = 'flex';
  } else {
    textEl.style.display = 'none';
    textEl.style.opacity = '1';
    textEl.textContent   = '';
  }
}

function timelineFrame() {
  if (!tlShow || tlStartTime === null) return;

  const showTime = serverNow() - tlStartTime;

  if (showTime < 0) {
    // Show hasn't started yet
    displayEl.style.background = '#000';
    displayEl.style.opacity    = '1';
    textEl.style.display       = 'none';
  } else {
    compositeTimeline(showTime);
  }

  tlRafId = requestAnimationFrame(timelineFrame);
}

function startTimelinePlayback(show, serverStartTime) {
  // Cancel any legacy cue timers
  clearEffect();
  if (tlRafId) { cancelAnimationFrame(tlRafId); tlRafId = null; }

  tlShow      = show;
  tlStartTime = serverStartTime;
  tlRafId     = requestAnimationFrame(timelineFrame);
}

function stopTimelinePlayback() {
  if (tlRafId) { cancelAnimationFrame(tlRafId); tlRafId = null; }
  tlShow      = null;
  tlStartTime = null;
}

// ── WebSocket connection ──────────────────────────────────────────────────────

function connect() {
  cleanupTimers();
  syncSamples = [];
  clockOffset = 0;

  if (ws) { try { ws.close(); } catch (e) {} ws = null; }

  statusEl.textContent = 'Connecting\u2026';
  ws = new WebSocket(wsUrl());

  ws.onopen = () => {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    statusEl.textContent = 'Connected';

    // Fire several sync probes in quick succession, then keep ticking
    [100, 300, 600, 1000, 1500, 2200].forEach(d => setTimeout(syncOnce, d));
    syncInterval = setInterval(syncOnce, 60000);
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    // ── Clock sync ────────────────────────────────────────────────────────────
    if (msg.type === 'sync_reply') {
      const t2  = nowSeconds();
      const rtt = t2 - msg.t0;
      syncSamples.push({ rtt, offset: msg.server_time - (msg.t0 + t2) / 2 });
      if (syncSamples.length > 20) syncSamples.shift();
      recomputeClockOffset();
      return;
    }

    // ── Timeline mode ─────────────────────────────────────────────────────────
    if (msg.type === 'show_load') {
      // Pre-load show data; actual playback begins on show_start
      tlShow = msg.show;
      return;
    }

    if (msg.type === 'show_start') {
      const show = msg.show || tlShow;
      if (show) startTimelinePlayback(show, msg.server_show_start_time);
      return;
    }

    if (msg.type === 'show_stop') {
      stopTimelinePlayback();
      clearEffect();
      return;
    }

    // ── Legacy cue mode ───────────────────────────────────────────────────────
    if (msg.type === 'cue') {
      // Switching back from timeline mode to cue mode if server sends a cue
      stopTimelinePlayback();
      scheduleCue(msg);
    }
  };

  ws.onerror = () => { statusEl.textContent = 'Connection issue'; };

  ws.onclose = () => {
    cleanupTimers();
    statusEl.textContent = 'Reconnecting\u2026';
    scheduleReconnect(3000);
  };
}

// ── Reconnect on visibility / network ────────────────────────────────────────

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    if (!ws || ws.readyState !== WebSocket.OPEN) connect(); else syncOnce();
  }
});

window.addEventListener('online', () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) connect(); else syncOnce();
});

window.addEventListener('pageshow', () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) connect();
});

connect();

// ── Show preload from URL query parameter ─────────────────────────────────────
//
// If the join URL includes a ?show=filename.json parameter, the client will
// fetch that file from /static/shows/ and preload it as the active show.
// Playback still starts only when the server sends a show_start message, so
// this just pre-warms tlShow so the show_start message can begin immediately.
//
// Example join URL:
//   /join/a1b2c3d4?show=A_storm_is_coming.json

(function () {
  const params   = new URLSearchParams(window.location.search);
  const showName = params.get('show');
  if (!showName) return;

  // Only allow bare .json filenames — no path separators.
  if (!showName.endsWith('.json') || showName.indexOf('/') !== -1 || showName.indexOf('\\') !== -1) {
    console.warn('[show-sync] invalid show name ignored');
    return;
  }

  fetch('/static/shows/' + encodeURIComponent(showName))
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (show) {
      tlShow = show;
      console.log('[show-sync] preloaded show:', showName);
    })
    .catch(function (err) {
      console.warn('[show-sync] could not load show:', showName, err);
    });
}());
