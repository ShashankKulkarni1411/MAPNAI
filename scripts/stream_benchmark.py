"""
MAPNAI — scripts/stream_benchmark.py
Two offline measurements for the report (continousexplanation.md §6), no database or network needed:

  dedup    duplicate lookup per article: the old linear SimHash scan vs the banded index (utils/deduplicator.py),
           over N stored fingerprints.
  polling  a day of simulated feeds (Poisson publishing, rates from a few a day to a few an hour): requests and
           mean time-to-fetch with fixed-interval polling vs the adaptive rules (stream/polling.py).

    python scripts/stream_benchmark.py dedup --sizes 1000 10000 100000
    python scripts/stream_benchmark.py polling --feeds 70 --fixed 15 30
"""

import argparse
import os
import random
import statistics
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stream import polling                                            # noqa: E402
from utils.deduplicator import SimHashIndex, simhash_distance          # noqa: E402


# ── Dedup ────────────────────────────────────────────────────

def bench_dedup(sizes, queries: int = 200, threshold: int = 3, seed: int = 1):
    rng = random.Random(seed)
    rows = []
    for n in sizes:
        stored = [f"{rng.getrandbits(64):016x}" for _ in range(n)]
        index = SimHashIndex(threshold)
        for h in stored:
            index.add(h)
        qs = [f"{rng.getrandbits(64):016x}" for _ in range(queries)]

        t = time.perf_counter()
        for q in qs:
            any(simhash_distance(q, h) <= threshold for h in stored)
        linear_ms = (time.perf_counter() - t) / queries * 1000

        t = time.perf_counter()
        for q in qs:
            index.find(q)
        banded_ms = (time.perf_counter() - t) / queries * 1000
        rows.append((n, linear_ms, banded_ms))
    print(f"{'stored':>10}{'linear ms/item':>18}{'banded ms/item':>18}{'speed-up':>12}")
    for n, lin, band in rows:
        print(f"{n:>10}{lin:>18.3f}{band:>18.4f}{lin / max(band, 1e-9):>11.0f}x")
    return rows


# ── Polling ──────────────────────────────────────────────────

def simulate_feed(rate_per_h: float, policy, cfg, hours: float = 24.0, seed: int = 0):
    """policy: minutes (fixed) or "adaptive". Returns (requests, [delay in minutes of every item])."""
    rng = random.Random(seed)
    t, items = 0.0, []
    while True:
        t += rng.expovariate(rate_per_h / 60.0) if rate_per_h > 0 else hours * 60 + 1
        if t > hours * 60:
            break
        items.append(t)
    polls, delays, fetched = 0, [], 0
    now, interval = 0.0, polling.initial_interval("section", cfg) / 60
    while now <= hours * 60:
        polls += 1
        new = [x for x in items[fetched:] if x <= now]
        delays.extend(now - x for x in new)
        fetched += len(new)
        if policy == "adaptive":
            interval = polling.next_interval(interval * 60, polling.OK, len(new), "section", cfg) / 60
            now += interval
        else:
            now += policy
    return polls, delays


def bench_polling(feeds: int, fixed, max_interval=None, seed: int = 7):
    from config.settings import Settings
    base = Settings(_env_file=None)
    cfg = SimpleNamespace(stream_min_interval_top_s=base.stream_min_interval_top_s,
                          stream_min_interval_s=base.stream_min_interval_s,
                          stream_max_interval_s=float(max_interval or base.stream_max_interval_s),
                          stream_initial_interval_s=base.stream_initial_interval_s)
    rng = random.Random(seed)
    rates = [rng.choice([0.1, 0.2, 0.5, 1, 2, 4, 8]) for _ in range(feeds)]        # items per hour
    policies = [*fixed, "adaptive"]
    print(f"{feeds} feeds, 24 h, publishing {min(rates)}–{max(rates)} items/h each ({sum(rates) * 24:.0f} items/day)")
    print("delay = minutes from publication to fetch, over every article (busy feeds weigh more)")
    print(f"{'policy':>14}{'requests/day':>15}{'median':>9}{'mean':>8}{'p90':>8}")
    for pol in policies:
        total, delays = 0, []
        for i, r in enumerate(rates):
            polls, d = simulate_feed(r, pol, cfg, seed=seed + i)
            total += polls
            delays.extend(d)
        delays.sort()
        q = lambda f: delays[int(f * (len(delays) - 1))]   # noqa: E731
        label = f"every {pol:g} min" if pol != "adaptive" else "adaptive"
        print(f"{label:>14}{total:>15}{q(0.5):>8.1f}m{statistics.fmean(delays):>7.1f}m{q(0.9):>7.1f}m")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="MAPNAI stream benchmarks")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dedup")
    d.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 100000])
    d.add_argument("--queries", type=int, default=200)
    pp = sub.add_parser("polling")
    pp.add_argument("--feeds", type=int, default=70)
    pp.add_argument("--fixed", type=float, nargs="+", default=[5, 15, 30])
    pp.add_argument("--max-interval", type=float, default=None, help="adaptive ceiling in seconds (default: settings)")
    args = p.parse_args(argv)
    if args.cmd == "dedup":
        bench_dedup(args.sizes, args.queries)
    else:
        bench_polling(args.feeds, args.fixed, args.max_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
