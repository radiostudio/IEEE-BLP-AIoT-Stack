"""Expo load test for the gateway dashboard server (stdlib only).

Simulates N visitors opening the dashboard on their phones. Each virtual
user replays what gateway/dashboard/index.html really does:

  on open : GET /, /api/sensors, /api/latest/<uid> per sensor,
            /api/series/<uid>/<field> per field   (backfill, sequential)
  then    : every 5 s  /api/sensors, /api/latest/<uid> per sensor,
            /api/annotations                      (refresh, sequential)

Modes:
  dashboard  realistic browser behaviour above (default)
  ping       each user hammers GET /api/sensors every --interval seconds

Usage:
  python tools/gateway_loadtest.py --host 192.168.1.100 --users 100 --duration 60
  python tools/gateway_loadtest.py --users 25,50,100,200 --duration 30   # step test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import defaultdict


class Stats:
    def __init__(self):
        self.lat = defaultdict(list)      # endpoint -> [seconds]
        self.err = defaultdict(int)       # endpoint -> count
        self.errkinds = defaultdict(int)  # message -> count
        self.bytes = 0
        self.t0 = time.perf_counter()

    def ok(self, ep, dt, n):
        self.lat[ep].append(dt)
        self.bytes += n

    def fail(self, ep, kind):
        self.err[ep] += 1
        self.errkinds[kind] += 1


def endpoint_of(path: str) -> str:
    p = path.split("?")[0]
    for pre in ("/api/latest/", "/api/series/"):
        if p.startswith(pre):
            return pre + "*"
    return p


async def get(host, port, path, st: Stats, timeout):
    ep = endpoint_of(path)
    t = time.perf_counter()
    w = None
    try:
        async def _do():
            nonlocal w
            r, w = await asyncio.open_connection(host, port)
            w.write(f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                    f"Connection: close\r\n\r\n".encode())
            await w.drain()
            return await r.read()
        raw = await asyncio.wait_for(_do(), timeout)
        head, _, body = raw.partition(b"\r\n\r\n")
        code = int(head.split(b" ", 2)[1]) if head else 0
        if code != 200:
            st.fail(ep, f"HTTP {code}")
            return None
        st.ok(ep, time.perf_counter() - t, len(raw))
        return body
    except asyncio.TimeoutError:
        st.fail(ep, "timeout")
    except Exception as e:  # refused / reset / etc.
        st.fail(ep, type(e).__name__)
    finally:
        if w is not None:
            try:
                w.close()
            except Exception:
                pass
    return None


async def user_dashboard(host, port, st, stop, timeout, interval):
    async def sensors():
        b = await get(host, port, "/api/sensors", st, timeout)
        return json.loads(b) if b else []

    await get(host, port, "/", st, timeout)
    uids = [s["uid"] for s in await sensors()]
    for uid in uids:                       # backfill
        b = await get(host, port, f"/api/latest/{uid}", st, timeout)
        fields = json.loads(b).get("fields", {}) if b else {}
        for f in fields:
            await get(host, port, f"/api/series/{uid}/{f}"
                      "?since=21600&agg=mean&bucket=60", st, timeout)
    while not stop.is_set():               # 5 s refresh loop
        t = time.perf_counter()
        for uid in [s["uid"] for s in await sensors()]:
            await get(host, port, f"/api/latest/{uid}", st, timeout)
        await get(host, port, "/api/annotations", st, timeout)
        try:
            await asyncio.wait_for(stop.wait(),
                                   max(0, interval - (time.perf_counter() - t)))
        except asyncio.TimeoutError:
            pass


async def user_ping(host, port, st, stop, timeout, interval):
    while not stop.is_set():
        await get(host, port, "/api/sensors", st, timeout)
        try:
            await asyncio.wait_for(stop.wait(),
                                   interval * random.uniform(0.8, 1.2))
        except asyncio.TimeoutError:
            pass


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p / 100))] if xs else float("nan")


def report(st: Stats, users, wall):
    allv = [x for v in st.lat.values() for x in v]
    nerr = sum(st.err.values())
    total = len(allv) + nerr
    print(f"\n=== {users} users, {wall:.0f}s ===")
    print(f"requests {total}  ok {len(allv)}  errors {nerr} "
          f"({100 * nerr / max(1, total):.2f}%)  "
          f"{total / wall:.0f} req/s  {st.bytes / wall / 1024:.0f} KiB/s")
    print(f"{'endpoint':<20}{'n':>7}{'err':>6}{'p50 ms':>9}{'p95 ms':>9}"
          f"{'p99 ms':>9}{'max ms':>9}")
    for ep in sorted(set(st.lat) | set(st.err)):
        v = st.lat.get(ep, [])
        print(f"{ep:<20}{len(v):>7}{st.err.get(ep, 0):>6}"
              f"{pct(v, 50) * 1e3:>9.0f}{pct(v, 95) * 1e3:>9.0f}"
              f"{pct(v, 99) * 1e3:>9.0f}{(max(v) if v else 0) * 1e3:>9.0f}")
    if st.errkinds:
        print("error kinds:", dict(st.errkinds))
    p95 = pct(allv, 95) * 1e3
    verdict = ("SMOOTH" if nerr == 0 and p95 < 500 else
               "DEGRADED" if nerr / max(1, total) < 0.02 and p95 < 2000 else
               "OVERLOADED")
    print(f"verdict: {verdict} (overall p95 {p95:.0f} ms)")
    return verdict


async def run_once(args, users):
    st = Stats()
    stop = asyncio.Event()
    fn = user_dashboard if args.mode == "dashboard" else user_ping
    tasks = []
    t0 = time.perf_counter()
    for i in range(users):                 # ramp: spread joins over --ramp s
        tasks.append(asyncio.create_task(
            fn(args.host, args.port, st, stop, args.timeout, args.interval)))
        await asyncio.sleep(args.ramp / users)
    await asyncio.sleep(max(0, args.duration - (time.perf_counter() - t0)))
    stop.set()
    await asyncio.wait(tasks, timeout=args.timeout + 5)
    for t in tasks:
        t.cancel()
    return report(st, users, time.perf_counter() - t0)


async def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--host", default="192.168.1.100")
    ap.add_argument("--port", type=int, default=8931)
    ap.add_argument("--users", default="100", help="N or comma list for steps")
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--ramp", type=float, default=10,
                    help="seconds over which users join")
    ap.add_argument("--interval", type=float, default=5)
    ap.add_argument("--timeout", type=float, default=10)
    ap.add_argument("--mode", choices=["dashboard", "ping"], default="dashboard")
    args = ap.parse_args()
    for n in [int(x) for x in args.users.split(",")]:
        await run_once(args, n)
        await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
