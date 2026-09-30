"""Deterministic policy. This file owns every operational decision.

Jev supplies judgments; this supplies consequences. It is plain Python, it is
unit-tested without touching the network, and every rule that could page
someone is readable in one screen.

Thresholds are DEMONSTRATION VALUES. Calibrate them against your own incident
history before trusting them."""
from __future__ import annotations

import os

from .models import Decisions, IncidentContext, Route

# How close to a threshold counts as "too close to call". If moving the
# probability by this much would flip the routing outcome, we escalate
# instead of acting.
FRAGILE_MARGIN = float(os.getenv("FRAGILE_MARGIN", "0.03"))

T_IMPACT = 0.90          # customer impact required for a page
T_ATTENTION = 0.90       # immediate attention required for a page
T_QUIET = 0.20           # below this, nobody is affected and nothing is urgent
T_DEGRADED = 0.80        # material degradation that warrants a Slack ping
T_AFFECTED = 0.60        # users are affected enough to tell someone

IMPACT_RANK = {"negligible": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# Ownership is a separate decision from severity.
DOMAIN_OWNERS = {
    "infrastructure": "platform",
    "capacity": "platform",
    "database": "data",
    "security": "security",
}


def is_fragile(value: float, threshold: float, margin: float = FRAGILE_MARGIN) -> bool:
    """True when `value` sits so close to `threshold` that the routing
    outcome is decided by noise.

    This is the useful uncertainty question, and it is not the same as
    "is the probability near 0.5". A confident 0.62 is a fine answer; it
    is only a problem when the rule we are about to apply cuts at 0.60."""
    return abs(value - threshold) < margin


def _static_fallback(ctx: IncidentContext) -> Route:
    """Used when Jev is unavailable. Mirrors classic Alertmanager behaviour:
    trust the severity label that shipped with the alert. Degraded, never silent."""
    severities = {a.labels.get("severity", "warning") for a in ctx.alerts}
    if "critical" in severities:
        return Route(
            priority="P1", channel="pagerduty", target=ctx.service.owner,
            reason="Decision layer unavailable; fell back to static severity label (critical).",
        )
    return Route(
        priority="P3", channel="jira", target=ctx.service.owner,
        reason="Decision layer unavailable; fell back to static severity label.",
    )


def _owner_for(ctx: IncidentContext, d: Decisions) -> str:
    if d.domain_confidence >= 0.60 and d.domain in DOMAIN_OWNERS:
        return DOMAIN_OWNERS[d.domain]
    return ctx.service.owner


def decide_route(ctx: IncidentContext, d: Decisions | None) -> Route:
    if d is None:
        return _static_fallback(ctx)

    svc = ctx.service
    owner = _owner_for(ctx, d)
    impact = IMPACT_RANK.get(d.impact_level, 0)

    # 1. Non-production never pages. A hard constraint in code beats a probability.
    if svc.environment != "production":
        return Route(
            priority="P3", channel="jira", target=owner,
            reason=f"Non-production environment ({svc.environment}); never pages.",
        )

    page_signals = [(d.customer_impact, T_IMPACT),
                    (d.requires_immediate_attention, T_ATTENTION)]

    # 2. P1: tier-1, users affected, action needed now - and not marginal.
    if svc.criticality == "tier-1" and all(v > t for v, t in page_signals):
        if any(is_fragile(v, t) for v, t in page_signals):
            return Route(
                priority="P2", channel="review", target=owner,
                reason=(
                    "P1 rule matched only marginally "
                    f"(impact {d.customer_impact:.2f}, attention "
                    f"{d.requires_immediate_attention:.2f}, thresholds {T_IMPACT:.2f}); "
                    "escalated rather than paging on a near-tie."
                ),
                escalated_for_review=True,
            )
        return Route(
            priority="P1", channel="pagerduty", target=owner,
            reason=(
                f"tier-1 service, customer impact {d.customer_impact:.2f} > {T_IMPACT:.2f}, "
                f"immediate attention {d.requires_immediate_attention:.2f} > {T_ATTENTION:.2f}."
            ),
        )

    # 3. tier-1 that nearly qualified: a human should look, but not at 3am.
    if svc.criticality == "tier-1" and any(is_fragile(v, t) for v, t in page_signals):
        return Route(
            priority="P2", channel="review", target=owner,
            reason=(
                "tier-1 incident sits on the paging threshold "
                f"(impact {d.customer_impact:.2f}, attention "
                f"{d.requires_immediate_attention:.2f}); escalated for review."
            ),
            escalated_for_review=True,
        )

    # 4. Nobody affected, nothing urgent: suppress, unless it is a close call.
    quiet = [(d.customer_impact, T_QUIET), (d.requires_immediate_attention, T_QUIET)]
    if all(v < t for v, t in quiet) and impact <= 1:
        if any(is_fragile(v, t) for v, t in quiet):
            return Route(
                priority="P3", channel="jira", target=owner,
                reason="Close to the suppression threshold; filed a ticket rather than suppressing.",
                escalated_for_review=True,
            )
        return Route(
            priority="SUPPRESS", channel="none", target=owner,
            reason="No evidence of user impact and no need for immediate action.",
        )

    # 5. P2: real degradation, not yet a page.
    #    The third clause matters: a tier-2 service with a clear user-visible
    #    error rate belongs in Slack even when neither headline signal is
    #    extreme. Without it, moderate regressions silently became tickets.
    users_affected_and_notable = d.customer_impact > T_AFFECTED and impact >= 2
    if impact >= 3 or d.material_degradation > T_DEGRADED or users_affected_and_notable:
        return Route(
            priority="P2", channel="slack", target=owner,
            reason=(
                f"Impact '{d.impact_level}' (score {d.impact_score:.2f}), "
                f"material degradation {d.material_degradation:.2f}."
            ),
            escalated_for_review=is_fragile(d.material_degradation, T_DEGRADED),
        )

    # 6. Everything else is a ticket.
    return Route(
        priority="P3", channel="jira", target=owner,
        reason=f"No P1/P2 rule matched; impact '{d.impact_level}' (score {d.impact_score:.2f}).",
    )
