"""Alertmanager webhook receiver.

  POST /alerts   Alertmanager v4 webhook body (optionally with a `context` key)
  GET  /healthz
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from .context import build_context
from .jev import decide
from .normalize import CORRELATION_WINDOW_SECONDS, group_alerts, normalize
from .policy import decide_route
from .routing import dispatch, render

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
app = FastAPI(title="jev-alert-router")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/alerts", response_class=PlainTextResponse)
def alerts(payload: dict[str, Any]) -> str:
    """Alertmanager posts here. `context` is the enrichment a webhook can't
    know (cluster state, traffic, deployments); in production this is fetched,
    not posted."""
    parsed = normalize(payload)
    if not parsed:
        return "no firing alerts in payload\n"

    extra = payload.get("context", {})
    blocks: list[str] = []

    for key, group in group_alerts(parsed).items():
        ctx = build_context(
            incident_id=f"inc-{uuid.uuid4().hex[:8]}",
            alerts=group,
            extra=extra.get(key, extra),
        )
        decisions = decide(ctx)
        route = decide_route(ctx, decisions)
        dispatch(route, ctx)
        blocks.append(render(ctx, decisions, route))

    header = (
        f"{len(parsed)} alert(s) -> {len(blocks)} incident(s) "
        f"(correlation window {CORRELATION_WINDOW_SECONDS}s)\n"
        + "=" * 62
    )
    return header + "\n" + ("\n" + "-" * 62 + "\n").join(blocks) + "\n"
