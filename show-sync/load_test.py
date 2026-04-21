#!/usr/bin/env python3
"""
load_test.py — WebSocket load-tester for the show-sync listener endpoint.

Simulates up to 2000 phone-like clients connecting to ``/ws/{session_id}``,
spread across a configurable ramp window, holding the connection for a
configurable duration, and reporting connection latency and outcome metrics.

Requirements
------------
    pip install websockets

Usage
-----
    python load_test.py --help

    # 100 clients over 10 s ramp, hold for 30 s
    python load_test.py --clients 100 --ramp 10 --hold 30

    # 500 clients over 30 s ramp against a custom endpoint
    python load_test.py --clients 500 --ramp 30 --hold 60 \\
        --url wss://localhost-0.tailc4daa4.ts.net/ws/

    # 2000 clients over 60 s ramp, skip TLS cert verification
    python load_test.py --clients 2000 --ramp 60 --hold 120 --no-verify
"""

import argparse
import asyncio
import ssl
import statistics
import sys
import time

try:
    import websockets
    import websockets.exceptions
except ImportError:
    print(
        "ERROR: 'websockets' package not found.\n"
        "Install it with:  pip install websockets",
        file=sys.stderr,
    )
    sys.exit(1)


# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "wss://localhost-0.tailc4daa4.ts.net/ws/"
DEFAULT_SESSION  = "load-test"
DEFAULT_CLIENTS  = 100
DEFAULT_RAMP     = 10
DEFAULT_HOLD     = 30
REPORT_INTERVAL    = 5   # seconds between progress lines
HANDSHAKE_TIMEOUT  = 15  # seconds to wait for the WebSocket handshake


# ── Shared metrics ─────────────────────────────────────────────────────────────

class Metrics:
    """Thread-safe (asyncio-safe) counters and latency store."""

    def __init__(self):
        self.attempted  = 0
        self.connected  = 0
        self.failed     = 0
        self.active     = 0
        self.latencies: list[float] = []   # seconds
        self.errors:    list[str]   = []   # sample error strings (capped)
        self._lock = asyncio.Lock()

    async def record_attempt(self):
        async with self._lock:
            self.attempted += 1

    async def record_connected(self, latency_s: float):
        async with self._lock:
            self.connected += 1
            self.active    += 1
            self.latencies.append(latency_s)

    async def record_disconnected(self):
        async with self._lock:
            self.active = max(0, self.active - 1)

    async def record_failed(self, error: str):
        async with self._lock:
            self.failed += 1
            if len(self.errors) < 20:
                self.errors.append(error)

    def snapshot(self) -> dict:
        """Return a point-in-time copy of key counters.

        Asyncio is single-threaded: no other coroutine runs while this method
        executes (there is no ``await``), so reading shared state here is safe
        without acquiring the lock.
        """
        lats = self.latencies
        lat_avg  = statistics.mean(lats)     if lats else None
        lat_p50  = statistics.median(lats)   if lats else None
        lat_p95  = _percentile(lats, 95)     if lats else None
        lat_p99  = _percentile(lats, 99)     if lats else None
        return {
            "attempted": self.attempted,
            "connected": self.connected,
            "failed":    self.failed,
            "active":    self.active,
            "lat_avg":   lat_avg,
            "lat_p50":   lat_p50,
            "lat_p95":   lat_p95,
            "lat_p99":   lat_p99,
        }


def _percentile(data: list[float], pct: float) -> float:
    """Compute the *pct*-th percentile of *data* (sorted copy)."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


# ── Single client coroutine ────────────────────────────────────────────────────

async def _client(
    url: str,
    client_id: int,
    hold: float,
    ssl_ctx,
    metrics: Metrics,
):
    """Connect to *url*, hold the WebSocket open for *hold* seconds, then close."""
    await metrics.record_attempt()
    t_start = time.monotonic()
    try:
        connect_kwargs = {"ssl": ssl_ctx} if ssl_ctx is not None else {}
        # open_connection with a 15-second handshake timeout
        async with websockets.connect(url, open_timeout=HANDSHAKE_TIMEOUT, **connect_kwargs) as ws:
            latency = time.monotonic() - t_start
            await metrics.record_connected(latency)
            try:
                # Hold the connection alive, responding to any incoming messages
                deadline = time.monotonic() + hold
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=remaining)
                        # Ignore received messages (cues, show_start, etc.)
                    except asyncio.TimeoutError:
                        break
                    except websockets.exceptions.ConnectionClosed:
                        break
            finally:
                await metrics.record_disconnected()
    except Exception as exc:
        await metrics.record_failed(f"client-{client_id}: {type(exc).__name__}: {exc}")


# ── Reporter coroutine ─────────────────────────────────────────────────────────

async def _reporter(metrics: Metrics, total: int, stop_event: asyncio.Event):
    """Print periodic progress lines until *stop_event* is set."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=REPORT_INTERVAL)
        except asyncio.TimeoutError:
            pass
        snap = metrics.snapshot()
        lat_str = (
            f"lat avg={snap['lat_avg']*1000:.1f}ms "
            f"p50={snap['lat_p50']*1000:.1f}ms "
            f"p95={snap['lat_p95']*1000:.1f}ms"
            if snap["lat_avg"] is not None
            else "lat n/a"
        )
        print(
            f"[{time.strftime('%H:%M:%S')}] "
            f"attempted={snap['attempted']}/{total} "
            f"connected={snap['connected']} "
            f"active={snap['active']} "
            f"failed={snap['failed']} "
            f"{lat_str}"
        )


# ── Main orchestrator ──────────────────────────────────────────────────────────

async def run(
    url: str,
    num_clients: int,
    ramp: float,
    hold: float,
    ssl_ctx,
):
    metrics    = Metrics()
    stop_event = asyncio.Event()

    reporter_task = asyncio.create_task(
        _reporter(metrics, num_clients, stop_event)
    )

    print(
        f"Starting load test: {num_clients} clients | "
        f"ramp {ramp:.0f}s | hold {hold:.0f}s | url={url}"
    )
    print("-" * 70)

    # Schedule each client at a uniformly-spaced offset within [0, ramp].
    # For 1 client the offset is 0; for N > 1 the spacing is ramp/(N-1).
    tasks = []
    for i in range(num_clients):
        if num_clients > 1:
            delay = i * ramp / (num_clients - 1)
        else:
            delay = 0.0
        tasks.append(asyncio.create_task(_delayed_client(url, i, delay, hold, ssl_ctx, metrics)))

    # Wait for all client tasks to complete
    await asyncio.gather(*tasks, return_exceptions=True)

    # Signal reporter to print its final line and exit
    stop_event.set()
    await reporter_task

    # ── Final summary ─────────────────────────────────────────────────────────
    snap = metrics.snapshot()
    print("-" * 70)
    print("Load test complete.")
    print(f"  Clients attempted : {snap['attempted']}")
    print(f"  Connected         : {snap['connected']}")
    print(f"  Failed            : {snap['failed']}")
    success_rate = (
        snap["connected"] / snap["attempted"] * 100
        if snap["attempted"] > 0 else 0.0
    )
    print(f"  Success rate      : {success_rate:.1f}%")
    if snap["lat_avg"] is not None:
        print(
            f"  Latency (connect) : "
            f"avg={snap['lat_avg']*1000:.1f}ms "
            f"p50={snap['lat_p50']*1000:.1f}ms "
            f"p95={snap['lat_p95']*1000:.1f}ms "
            f"p99={snap['lat_p99']*1000:.1f}ms"
        )
    if metrics.errors:
        print(f"  Sample errors ({len(metrics.errors)}):")
        for err in metrics.errors[:5]:
            print(f"    {err}")
        if len(metrics.errors) > 5:
            print(f"    … and {len(metrics.errors) - 5} more")


async def _delayed_client(url, client_id, delay, hold, ssl_ctx, metrics):
    """Sleep for *delay* seconds then launch a client coroutine."""
    if delay > 0:
        await asyncio.sleep(delay)
    await _client(url, client_id, hold, ssl_ctx, metrics)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _build_ssl_context(no_verify: bool, url: str):
    """Return an SSL context if the URL is wss://, else None.

    When *no_verify* is True, certificate verification is disabled (useful for
    local / self-signed certificates).
    """
    if not url.startswith("wss://"):
        return None  # ws:// — plaintext, no SSL needed
    ctx = ssl.create_default_context()
    if no_verify:
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
    return ctx


def _build_url(base: str, session: str) -> str:
    """Append the session ID to the base URL, normalizing trailing slashes."""
    return base.rstrip("/") + "/" + session


def main():
    parser = argparse.ArgumentParser(
        description="Load-test the show-sync WebSocket listener endpoint.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_BASE_URL,
        help="Base WebSocket URL up to (but not including) the session ID, "
             "e.g. wss://host/ws/  or  ws://localhost:8000/ws/",
    )
    parser.add_argument(
        "--session",
        default=DEFAULT_SESSION,
        help="Session ID to append to --url (e.g. load-test or a1b2c3d4).",
    )
    parser.add_argument(
        "--clients",
        type=int,
        default=DEFAULT_CLIENTS,
        metavar="N",
        help="Number of simulated clients (max recommended: 2000).",
    )
    parser.add_argument(
        "--ramp",
        type=float,
        default=DEFAULT_RAMP,
        metavar="SECONDS",
        help="Spread window in seconds over which clients connect (1–60).",
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=DEFAULT_HOLD,
        metavar="SECONDS",
        help="How long each client stays connected after handshake.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Disable TLS certificate verification (for self-signed / local certs).",
    )
    args = parser.parse_args()

    if args.clients < 1:
        parser.error("--clients must be at least 1")
    if args.ramp < 0:
        parser.error("--ramp must be >= 0")
    if args.hold < 0:
        parser.error("--hold must be >= 0")

    url     = _build_url(args.url, args.session)
    ssl_ctx = _build_ssl_context(args.no_verify, url)

    print(f"Target URL : {url}")
    print(f"TLS verify : {'disabled' if args.no_verify else 'enabled'}")
    print()

    # Raise the default asyncio event-loop connection limit to allow 2000+
    # concurrent WebSocket connections.
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        need = args.clients + 64
        if soft < need:
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(need, hard), hard))
    except Exception:
        pass  # Windows / unsupported — proceed anyway

    asyncio.run(run(url, args.clients, args.ramp, args.hold, ssl_ctx))


if __name__ == "__main__":
    main()
