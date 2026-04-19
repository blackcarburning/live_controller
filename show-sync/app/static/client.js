const sessionId = document.body.dataset.sessionId;
const statusEl = document.getElementById("status");
const displayEl = document.getElementById("display");
const textEl = document.getElementById("text-overlay");

let ws = null;
let reconnectTimer = null;
let syncInterval = null;
let fadeTimer = null;

let syncSamples = [];
let clockOffset = 0;

function nowSeconds() {
  return Date.now() / 1000;
}

function wsUrl() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/${sessionId}`;
}

function cleanupTimers() {
  if (syncInterval) {
    clearInterval(syncInterval);
    syncInterval = null;
  }
}

function scheduleReconnect(delayMs) {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delayMs);
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2) return sorted[mid];
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

function recomputeClockOffset() {
  if (!syncSamples.length) return;

  const best = [...syncSamples]
    .sort((a, b) => a.rtt - b.rtt)
    .slice(0, 5);

  clockOffset = median(best.map(s => s.offset));

  const bestRtt = best[0].rtt;
  statusEl.textContent =
    `Connected • synced (${Math.round(bestRtt * 1000)} ms RTT)`;
}

function syncOnce() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({
    type: "sync",
    t0: nowSeconds()
  }));
}

// --- Effect rendering ---

function clearEffect() {
  if (fadeTimer) {
    clearTimeout(fadeTimer);
    fadeTimer = null;
  }
  displayEl.style.transition = "none";
  displayEl.style.background = "#000000";
  textEl.style.display = "none";
  textEl.textContent = "";
}

function runEffect(msg) {
  const effect = msg.effect || "solid";
  const params = msg.params || {};
  const durationMs = (msg.duration || 1.0) * 1000;
  const color = params.color || "#ff0000";

  clearEffect();

  switch (effect) {
    case "solid":
      displayEl.style.transition = "none";
      displayEl.style.background = color;
      fadeTimer = setTimeout(clearEffect, durationMs);
      break;

    case "fade_in":
      // Start black, transition to color over the duration.
      displayEl.style.transition = "none";
      displayEl.style.background = "#000000";
      // Double rAF ensures the browser paints black before the transition starts.
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          displayEl.style.transition = `background-color ${durationMs}ms linear`;
          displayEl.style.background = color;
          fadeTimer = setTimeout(clearEffect, durationMs + 100);
        });
      });
      break;

    case "fade_out":
      // Start at color, transition to black over the duration.
      displayEl.style.transition = "none";
      displayEl.style.background = color;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          displayEl.style.transition = `background-color ${durationMs}ms linear`;
          displayEl.style.background = "#000000";
          fadeTimer = setTimeout(clearEffect, durationMs + 100);
        });
      });
      break;

    case "text":
      textEl.textContent = params.text || "";
      textEl.style.color = color;
      textEl.style.display = "flex";
      fadeTimer = setTimeout(clearEffect, durationMs);
      break;

    default:
      // Unknown effect type: fall back to a solid color flash.
      displayEl.style.transition = "none";
      displayEl.style.background = color;
      fadeTimer = setTimeout(clearEffect, durationMs);
      break;
  }
}

// --- Scheduling ---

function scheduleCue(msg) {
  const localTarget = msg.server_start_time - clockOffset;

  function check() {
    const now = nowSeconds();
    if (now >= localTarget) {
      runEffect(msg);
      return;
    }

    const remainingMs = (localTarget - now) * 1000;

    if (remainingMs > 30) {
      setTimeout(check, remainingMs - 20);
    } else {
      requestAnimationFrame(check);
    }
  }

  check();
}

// --- WebSocket connection ---

function connect() {
  cleanupTimers();
  syncSamples = [];
  clockOffset = 0;

  if (ws) {
    try { ws.close(); } catch (e) {}
    ws = null;
  }

  statusEl.textContent = "Connecting…";
  ws = new WebSocket(wsUrl());

  ws.onopen = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    statusEl.textContent = "Connected";

    setTimeout(syncOnce, 100);
    setTimeout(syncOnce, 300);
    setTimeout(syncOnce, 600);
    setTimeout(syncOnce, 1000);
    setTimeout(syncOnce, 1500);
    setTimeout(syncOnce, 2200);

    syncInterval = setInterval(syncOnce, 60000);
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === "sync_reply") {
      const t2 = nowSeconds();
      const t0 = msg.t0;
      const t1 = msg.server_time;
      const rtt = t2 - t0;
      const midpoint = (t0 + t2) / 2;
      const offset = t1 - midpoint;

      syncSamples.push({ rtt, offset });

      if (syncSamples.length > 20) {
        syncSamples.shift();
      }

      recomputeClockOffset();
      return;
    }

    if (msg.type === "cue") {
      scheduleCue(msg);
    }
  };

  ws.onerror = () => {
    statusEl.textContent = "Connection issue";
  };

  ws.onclose = () => {
    cleanupTimers();
    statusEl.textContent = "Reconnecting…";
    scheduleReconnect(3000);
  };
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      connect();
    } else {
      syncOnce();
    }
  }
});

window.addEventListener("online", () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    connect();
  } else {
    syncOnce();
  }
});

window.addEventListener("pageshow", () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    connect();
  }
});

connect();
