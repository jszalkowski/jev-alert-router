"""Policy tests. No network, no Jev. We are testing OUR rules, with
Jev's judgments supplied as fixed inputs. This is the half of the system
that must be provably correct."""
import pytest

from src.models import (Decisions, IncidentContext, AlertFacts, ServiceFacts,
                        KubernetesFacts, TrafficFacts, DeploymentFacts)
from src.policy import decide_route


def ctx(environment="production", criticality="tier-1", owner="payments", severity="critical"):
    return IncidentContext(
        incident_id="inc-test",
        alerts=[AlertFacts(name="HighHttpErrorRate", labels={"severity": severity})],
        service=ServiceFacts(name="checkout-api", environment=environment,
                             criticality=criticality, owner=owner, customer_facing=True),
        kubernetes=KubernetesFacts(desired_replicas=20, available_replicas=12),
        traffic=TrafficFacts(requests_per_second=1800, http_5xx_rate=0.23),
        deployment=DeploymentFacts(deployed_minutes_ago=9),
    )


def dec(**kw):
    base = dict(customer_impact=0.94, material_degradation=0.97,
                requires_immediate_attention=0.96, deployment_related=0.88,
                domain="application", domain_confidence=0.61,
                impact_score=3.2, impact_level="high", impact_confidence=0.8)
    base.update(kw)
    return Decisions(**base)


def test_tier1_customer_impact_is_p1():
    r = decide_route(ctx(), dec(customer_impact=0.98, requires_immediate_attention=0.97))
    assert r.priority == "P1"
    assert r.channel == "pagerduty"


def test_tier1_sitting_on_the_threshold_escalates_instead_of_paging():
    """0.91 against a 0.90 threshold is a coin flip dressed as a decision."""
    r = decide_route(ctx(), dec(customer_impact=0.91, requires_immediate_attention=0.92))
    assert r.channel == "review"
    assert r.escalated_for_review is True


def test_tier2_with_same_signals_is_not_p1():
    r = decide_route(ctx(criticality="tier-2"), dec())
    assert r.priority == "P2"
    assert r.channel == "slack"


def test_non_production_never_pages():
    r = decide_route(ctx(environment="development"), dec())
    assert r.priority == "P3"
    assert r.channel == "jira"


def test_no_impact_is_suppressed():
    r = decide_route(ctx(), dec(customer_impact=0.03, requires_immediate_attention=0.04,
                               material_degradation=0.10, impact_level="negligible", impact_score=0.1))
    assert r.priority == "SUPPRESS"
    assert r.channel == "none"


def test_mid_range_probabilities_are_not_treated_as_uncertainty():
    """A confident 0.55 is an answer, not a hesitation. Only proximity to a
    threshold we actually apply counts as uncertainty."""
    r = decide_route(ctx(criticality="tier-2"),
                     dec(customer_impact=0.55, material_degradation=0.55,
                         requires_immediate_attention=0.52, impact_level="low",
                         impact_score=1.2))
    assert r.channel != "review"


def test_infrastructure_domain_routes_to_platform_not_service_owner():
    """Severity and ownership are separate decisions."""
    r = decide_route(ctx(), dec(customer_impact=0.98, requires_immediate_attention=0.97,
                               domain="infrastructure", domain_confidence=0.82))
    assert r.priority == "P1"
    assert r.target == "platform"


def test_low_domain_confidence_keeps_service_owner():
    r = decide_route(ctx(), dec(customer_impact=0.98, requires_immediate_attention=0.97,
                               domain="infrastructure", domain_confidence=0.41))
    assert r.target == "payments"


def test_jev_unavailable_falls_back_to_static_severity_never_drops():
    r = decide_route(ctx(severity="critical"), None)
    assert r.priority == "P1"
    assert r.channel == "pagerduty"
    assert "fell back" in r.reason


def test_jev_unavailable_with_warning_label_still_routes():
    r = decide_route(ctx(severity="warning"), None)
    assert r.channel == "jira"
    assert r.priority != "SUPPRESS"   # never silently drop


@pytest.mark.parametrize("value,threshold,expected", [
    (0.91, 0.90, True),    # decided by noise
    (0.98, 0.90, False),   # comfortably clear
    (0.50, 0.90, False),   # unambiguously below
])
def test_fragility_is_measured_at_the_threshold_not_at_half(value, threshold, expected):
    from src.policy import is_fragile
    assert is_fragile(value, threshold) is expected


def test_noul_answers_carry_no_confidence_field():
    """Documented API behaviour we depend on: NoulAnswer is [type, noul]."""
    from typesafe_sdk import NoulAnswer
    assert set(NoulAnswer.model_fields) == {"type", "noul"}
