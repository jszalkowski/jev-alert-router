"""Routing. Dry-run by default: it prints what it would do.

Wiring real PagerDuty/Slack/Jira clients is deliberately left as the last,
smallest step. Nothing here should be the interesting part of the system."""
from __future__ import annotations

import os

from .models import Decisions, IncidentContext, Route

DRY_RUN = os.getenv("ROUTER_DRY_RUN", "true").lower() != "false"


def render(ctx: IncidentContext, d: Decisions | None, route: Route) -> str:
    lines = [
        f"Incident: {ctx.service.name}  ({ctx.service.environment}, {ctx.service.criticality})",
        f"Alerts:   {len(ctx.alerts)}  ->  {', '.join(a.name for a in ctx.alerts)}",
        f"Priority: {route.priority}",
        f"Owner:    {route.target}",
        f"Action:   {route.channel}",
        "",
    ]
    if d is None:
        lines += ["Jev decisions:", "  unavailable - static fallback in use", ""]
    else:
        lines += [
            f"Jev decisions ({d.model}, {d.latency_ms:.0f} ms):",
            f"  customer impact:       {d.customer_impact:.2f}",
            f"  material degradation:  {d.material_degradation:.2f}",
            f"  immediate attention:   {d.requires_immediate_attention:.2f}",
            f"  deployment related:    {d.deployment_related:.2f}",
            f"  domain:                {d.domain} (confidence {d.domain_confidence:.2f})",
            f"  impact:                {d.impact_level} (score {d.impact_score:.2f})",
            f"  raw ambiguity (info):  {d.raw_ambiguity:.2f}",
            "",
        ]
    lines += [f"Reason:   {route.reason}"]
    if route.escalated_for_review:
        lines += ["Flagged:  uncertain - queued for human review"]
    return "\n".join(lines)


def dispatch(route: Route, ctx: IncidentContext) -> dict:
    payload = {
        "channel": route.channel,
        "target": route.target,
        "priority": route.priority,
        "service": ctx.service.name,
        "incident_id": ctx.incident_id,
        "dry_run": DRY_RUN,
    }
    if DRY_RUN:
        return payload | {"delivered": False, "note": "dry run; set ROUTER_DRY_RUN=false to deliver"}
    raise NotImplementedError(
        "Real PagerDuty/Slack/Jira delivery is intentionally not implemented. "
        "Wire your own clients here once you have run this in shadow mode."
    )
