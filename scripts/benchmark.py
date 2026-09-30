#!/usr/bin/env python3
"""Measure the decision layer: latency, call count, token usage, fallbacks.

Cost is NOT calculated here. TypeSafe publishes a per-token input price, but
turning that into a per-incident figure depends on your context size and your
alert volume, and inventing a number would be worse than omitting one.
Token counts are printed so you can do it against current pricing yourself.
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.context import build_context
from src.jev import decide
from src.normalize import group_alerts, normalize
from src.policy import decide_route

FIX = Path(__file__).parent.parent / "fixtures"
from fixtures import load
FIXTURES = ["production-outage.json", "dev-cpu-spike.json",
            "deployment-regression.json", "ambiguous-alert.json"]
QUESTIONS_PER_INCIDENT = 6   # 4 Noul + 1 Choice + 1 Score, one request


def p95(values: list[float]) -> float:
    """Linear-interpolated 95th percentile.

    Same convention as numpy's default and statistics.quantiles(inclusive).
    The obvious `srt[int(len(srt) * 0.95)]` is not a p95: at n=40 it returns
    the 39th of 40 samples, which is the 97.5th percentile.
    """
    if len(values) < 2:
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=100, method="inclusive")[94]


def main() -> int:
    runs = int(os.getenv("BENCH_RUNS", "40"))
    lat, toks, fallbacks, priorities, reviews = [], [], 0, {}, 0

    for i in range(runs):
        name = FIXTURES[i % len(FIXTURES)]
        payload = load(name)
        group = next(iter(group_alerts(normalize(payload)).values()))
        ctx = build_context(f"bench-{i}", group, payload.get("context", {}))

        t0 = time.perf_counter()
        d = decide(ctx)
        elapsed = (time.perf_counter() - t0) * 1000

        if d is None:
            fallbacks += 1
            continue
        lat.append(d.latency_ms or elapsed)
        toks.append(d.input_tokens)
        route = decide_route(ctx, d)
        priorities[route.priority] = priorities.get(route.priority, 0) + 1
        reviews += route.escalated_for_review

    n = len(lat) or 1
    srt = sorted(lat)
    print(f"\nmode:                  {os.getenv('JEV_MODE', 'mock')}")
    print(f"incidents:             {runs}")
    print(f"Jev requests:          {len(lat)}   (1 request per incident)")
    print(f"questions evaluated:   {len(lat) * QUESTIONS_PER_INCIDENT}   "
          f"({QUESTIONS_PER_INCIDENT} per request, one parallel pass)")
    print(f"median latency:        {statistics.median(srt):.1f} ms")
    print(f"p95 latency:           {p95(srt):.1f} ms")
    print(f"mean input tokens:     {statistics.mean(toks) if any(toks) else 0:.0f}")
    print(f"fallbacks (Jev down):  {fallbacks}")
    print(f"escalated for review:  {reviews}  ({reviews / n * 100:.0f}%)")
    for p in ("P1", "P2", "P3", "SUPPRESS"):
        print(f"routed {p:9}      {priorities.get(p, 0)}")
    if os.getenv("JEV_MODE", "mock") != "live":
        print("\nNOTE: mock latency is local computation. It says nothing about the API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
