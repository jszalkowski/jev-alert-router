#!/usr/bin/env python3
"""Run every fixture through the full pipeline and print the routes."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.context import build_context
from src.jev import decide
from src.normalize import group_alerts, normalize
from src.policy import decide_route
from src.routing import render

FIX = Path(__file__).parent.parent / "fixtures"
from fixtures import load
ORDER = ["production-outage.json", "dev-cpu-spike.json",
         "deployment-regression.json", "ambiguous-alert.json"]


def main() -> int:
    names = sys.argv[1:] or ORDER
    for i, name in enumerate(names, 1):
        payload = load(name)
        alerts = normalize(payload)
        for key, group in group_alerts(alerts).items():
            ctx = build_context(f"inc-{i:03d}", group, payload.get("context", {}))
            d = decide(ctx)
            route = decide_route(ctx, d)
            print(f"\n{'=' * 64}\nSCENARIO {i}: {name}  [{key}]\n{'=' * 64}")
            print(render(ctx, d, route))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
