"""The Jev decision layer.

Jev answers bounded questions about incident state. It does not assign
priority, choose a channel, or decide who gets paged. That is policy.py.

Two modes:
  JEV_MODE=mock  deterministic stand-in, no network, no API key
  JEV_MODE=live  the real TypeSafe API

Verified against typesafe-sdk 0.7.2 and docs.typesafe.ai (Sept 2026).
"""
from __future__ import annotations

import logging
import os
import time

from .models import Decisions, IncidentContext

log = logging.getLogger(__name__)

MODEL = os.getenv("JEV_MODEL", "jev-latest")

# Ordered rubric. Score returns an expected value across these levels
# (e.g. 2.4), not a label, so index 0 is the low end.
IMPACT_LEVELS = [
    "No user-visible effect",
    "Minor degradation; few or no users notice",
    "Clear degradation for a subset of users",
    "Major degradation for many users",
    "Complete or near-complete loss of the service",
]

DOMAINS = {
    "application": "Bug or regression in the service's own code",
    "infrastructure": "Nodes, networking, cluster or platform failure",
    "database": "Datastore saturation, locking, replication or connections",
    "dependency": "An upstream or downstream service is failing",
    "capacity": "Load exceeds provisioned resources",
    "security": "Suspected abuse, intrusion or malicious traffic",
    "unknown": "The evidence does not clearly indicate a domain",
}


def _questions():
    from typesafe_sdk import Choice, Noul, NoulCriteria, Score

    return {
        "customer_impact": Noul(
            instructions=(
                "Is there evidence that real users are currently affected? Weigh "
                "`traffic.http_5xx_rate`, `traffic.p99_latency_ms` and "
                "`traffic.requests_per_second`: a high error rate with no traffic "
                "affects nobody."
            ),
            criteria=NoulCriteria(
                true="Error rates, latency or availability indicate users are experiencing failures right now",
                false="The service is degraded internally but user-facing behaviour appears unaffected, or there is no user traffic",
            ),
        ),
        "material_degradation": Noul(
            instructions=(
                "Is the service materially degraded relative to normal operation? "
                "Consider `traffic.http_5xx_rate`, `kubernetes.unavailable_fraction` "
                "and `kubernetes.restarts_last_10m`."
            ),
            criteria=NoulCriteria(
                true="Key signals are well outside a normal operating range",
                false="Signals are elevated but within a range the service routinely handles",
            ),
        ),
        "requires_immediate_attention": Noul(
            instructions=(
                "Does this situation require a human to act now, rather than during "
                "business hours? Consider `service.environment`, "
                "`service.criticality` and whether `traffic` shows live user demand."
            ),
            criteria=NoulCriteria(
                true="Waiting would allow the situation to worsen or prolong user harm",
                false="The situation is stable, self-recovering, or confined to a non-production environment",
            ),
        ),
        "deployment_related": Noul(
            instructions=(
                "Is this plausibly caused by the most recent deployment? Compare "
                "`deployment.deployed_minutes_ago` with `alerts[].duration_seconds`; "
                "absent deployment data is not evidence of a link."
            ),
            criteria=NoulCriteria(
                true="The symptoms began close in time to a recent deployment of this service",
                false="There was no recent deployment, or the timing does not line up",
            ),
        ),
        "domain": Choice(
            instructions=(
                "Which domain does this incident most likely belong to? Use "
                "`alert_names`, `kubernetes` and `traffic` as evidence."
            ),
            criteria=DOMAINS,
        ),
        "impact": Score(
            instructions=(
                "How severe is the impact on users of this service right now? Judge "
                "from `traffic` and `kubernetes.unavailable_fraction`, scaled by "
                "`service.customer_facing`."
            ),
            criteria=IMPACT_LEVELS,
        ),
    }


def _nearest_level(score: float) -> str:
    idx = max(0, min(len(IMPACT_LEVELS) - 1, round(score)))
    return ["negligible", "low", "medium", "high", "critical"][idx]


# --------------------------------------------------------------------------
# mock mode
# --------------------------------------------------------------------------
def _mock(ctx: IncidentContext) -> Decisions:
    """A deterministic stand-in so the repo runs with no API key.

    This is NOT a prediction of what Jev would answer.

    IMPORTANT SEMANTIC CAVEAT. This mock ramps its Noul outputs with severity,
    which is convenient for exercising policy but is NOT what a Noul means.
    Per TypeSafe's own guidance: "A Noul near 0.5 means similar probability for
    yes and no, not medium intensity." Real Jev answering "are users affected?"
    for a clearly-but-mildly degraded service should return a HIGH probability
    (users are affected; it is simply not severe), not a middling one. Intensity
    belongs in the Score primitive, which is why `impact` exists.

    Consequence: mock Noul values are usable for testing thresholds and routing
    paths, and are misleading about semantics. Live mode is the only mode that
    tells you anything about Jev.
    """
    svc, k8s, traf, dep = ctx.service, ctx.kubernetes, ctx.traffic, ctx.deployment
    prod = svc.environment == "production"
    rps = traf.requests_per_second or 0.0
    err = traf.http_5xx_rate or 0.0
    unavail = k8s.unavailable_fraction or 0.0

    has_traffic = rps > 1.0
    impact = 0.0
    if prod and has_traffic:
        impact += min(err / 0.10, 1.0) * 2.2
        impact += min(unavail / 0.50, 1.0) * 1.3
        if (traf.p99_latency_ms or 0) > 2000:
            impact += 0.6
    impact = round(min(impact, 4.0), 2)

    customer = 0.05
    if prod and has_traffic and (err > 0.01 or (traf.p99_latency_ms or 0) > 2000):
        customer = min(0.5 + err * 2.0 + unavail * 0.4, 0.98)
    elif prod and has_traffic and unavail > 0.3:
        customer = 0.62

    degraded = min(0.05 + err * 3.0 + unavail * 1.1 + (0.2 if (traf.p99_latency_ms or 0) > 2000 else 0), 0.98)
    if not prod:
        degraded = min(degraded, 0.55)

    immediate = 0.04
    if prod:
        immediate = round(min(0.15 + customer * 0.75 + unavail * 0.3, 0.97), 3)

    mins = dep.deployed_minutes_ago
    deploy_related = 0.05 if mins is None else max(0.05, min(0.95, 1.0 - (mins / 60.0)))

    if unavail > 0.25 and err > 0.05:
        domain, dconf = "application", 0.61
    elif unavail > 0.25:
        domain, dconf = "infrastructure", 0.58
    elif err > 0.05:
        domain, dconf = "application", 0.57
    elif (traf.p99_latency_ms or 0) > 2000:
        domain, dconf = "database", 0.44
    else:
        domain, dconf = "unknown", 0.31

    return Decisions(
        customer_impact=round(customer, 3),
        material_degradation=round(degraded, 3),
        requires_immediate_attention=round(immediate, 3),
        deployment_related=round(deploy_related, 3),
        domain=domain,
        domain_confidence=dconf,
        impact_score=impact,
        impact_level=_nearest_level(impact),
        impact_confidence=round(0.4 + min(impact / 4.0, 1.0) * 0.5, 2),
        model="mock",
    )


# --------------------------------------------------------------------------
# live mode
# --------------------------------------------------------------------------
def _live(ctx: IncidentContext) -> Decisions | None:
    """Returns None on any API failure. The caller must then fall back to
    existing static routing. An unavailable decision layer must never
    swallow an alert."""
    from typesafe_sdk import TypeSafeClient, TypeSafeError

    started = time.perf_counter()
    try:
        with TypeSafeClient() as client:
            # Every question travels in ONE request and is evaluated in a
            # single parallel pass.
            r = client.system_one(ctx.as_state(), _questions(), model=MODEL)
    except TypeSafeError as exc:
        log.warning("jev unavailable (%s): falling back to static routing", type(exc).__name__)
        return None
    except Exception as exc:  # noqa: BLE001 - never let the router die
        log.warning("jev call failed (%s): falling back to static routing", type(exc).__name__)
        return None

    latency_ms = (time.perf_counter() - started) * 1000
    a = r.answers
    score = float(a["impact"].score)
    return Decisions(
        customer_impact=float(a["customer_impact"].noul),
        material_degradation=float(a["material_degradation"].noul),
        requires_immediate_attention=float(a["requires_immediate_attention"].noul),
        deployment_related=float(a["deployment_related"].noul),
        domain=a["domain"].choice,
        domain_confidence=float(a["domain"].confidence),
        impact_score=round(score, 3),
        impact_level=_nearest_level(score),
        impact_confidence=float(a["impact"].confidence),
        model=r.model,
        latency_ms=round(latency_ms, 1),
        input_tokens=r.usage.input_tokens,
        output_tokens=r.usage.output_tokens,
    )


def decide(ctx: IncidentContext) -> Decisions | None:
    mode = os.getenv("JEV_MODE", "mock").lower()
    if mode == "live":
        return _live(ctx)
    started = time.perf_counter()
    d = _mock(ctx)
    d.latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return d
