#!/usr/bin/env python3
"""Evaluate the two halves of the system SEPARATELY.

  1. Is our deterministic policy correct?      -> pytest, no network
  2. Does Jev make useful judgments?           -> this script, needs live mode

Conflating them is the most common way to fool yourself. A perfect policy on
bad judgments routes confidently to the wrong place.

Usage:
  JEV_MODE=live TYPESAFE_API_KEY=... python scripts/evaluate.py
  JEV_MODE=mock python scripts/evaluate.py      # exercises the harness only
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.context import build_context
from src.jev import decide
from src.normalize import group_alerts, normalize
from src.policy import decide_route

FIX = Path(__file__).parent.parent / "fixtures"

# A labelled set. Four rows is not an evaluation; it is a smoke test with
# opinions. Replace it with your own incidents before believing anything.
LABELS = [
    {"fixture": "production-outage.json",      "expected_customer_impact": True,
     "expected_attention": True,  "expected_domain": "application", "expected_priority": "P1"},
    {"fixture": "dev-cpu-spike.json",          "expected_customer_impact": False,
     "expected_attention": False, "expected_domain": "capacity",    "expected_priority": "P3"},
    {"fixture": "deployment-regression.json",  "expected_customer_impact": True,
     "expected_attention": False, "expected_domain": "application", "expected_priority": "P2"},
    {"fixture": "ambiguous-alert.json",        "expected_customer_impact": True,
     "expected_attention": True,  "expected_domain": "application", "expected_priority": "REVIEW"},
]


def run_one(fixture: str):
    payload = json.loads((FIX / fixture).read_text())
    group = next(iter(group_alerts(normalize(payload)).values()))
    ctx = build_context("eval", group, payload.get("context", {}))
    d = decide(ctx)
    return d, decide_route(ctx, d)


def main() -> int:
    mode = os.getenv("JEV_MODE", "mock")
    rows, tp = [], {"impact_hit": 0, "attention_hit": 0, "domain_hit": 0, "priority_hit": 0}
    false_pages = missed_critical = 0

    for lab in LABELS:
        d, route = run_one(lab["fixture"])
        if d is None:
            print(f"{lab['fixture']}: decision layer unavailable"); continue

        got_impact = d.customer_impact > 0.5
        got_attention = d.requires_immediate_attention > 0.5
        got_priority = "REVIEW" if route.escalated_for_review else route.priority

        tp["impact_hit"] += got_impact == lab["expected_customer_impact"]
        tp["attention_hit"] += got_attention == lab["expected_attention"]
        tp["domain_hit"] += d.domain == lab["expected_domain"]
        tp["priority_hit"] += got_priority == lab["expected_priority"]

        if route.priority == "P1" and lab["expected_priority"] not in {"P1"}:
            false_pages += 1
        if lab["expected_priority"] == "P1" and route.priority != "P1":
            missed_critical += 1

        rows.append((lab["fixture"], d, route, lab, got_priority))

    n = len(rows) or 1
    print(f"\nmode: {mode}   scenarios: {len(rows)}\n" + "=" * 92)
    print(f"{'scenario':30} {'impact':>7} {'atten':>7} {'domain':>14} {'expected':>9} {'got':>9}")
    print("-" * 92)
    for f, d, route, lab, got in rows:
        print(f"{f:30} {d.customer_impact:7.2f} {d.requires_immediate_attention:7.2f} "
              f"{d.domain:>14} {lab['expected_priority']:>9} {got:>9}")

    print("-" * 92)
    print(f"customer-impact agreement : {tp['impact_hit']}/{n}")
    print(f"attention agreement       : {tp['attention_hit']}/{n}")
    print(f"domain agreement          : {tp['domain_hit']}/{n}")
    print(f"routing agreement         : {tp['priority_hit']}/{n}")
    print(f"false pages               : {false_pages}")
    print(f"missed criticals          : {missed_critical}")
    if mode != "live":
        print("\nNOTE: mock mode measures the harness, not Jev. Only JEV_MODE=live")
        print("      tells you anything about the model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
