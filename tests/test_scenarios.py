"""End-to-end scenario tests in mock mode.

These assert the ARCHITECTURE behaves sensibly given deterministic inputs.
They say nothing about whether Jev is any good - that needs live mode and
a labelled dataset. See scripts/evaluate.py."""
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("JEV_MODE", "mock")

from src.context import build_context
from src.jev import decide
from src.normalize import group_alerts, normalize
from src.policy import decide_route

FIX = Path(__file__).parent.parent / "fixtures"
from fixtures import load


def run(fixture: str):
    payload = load(fixture)
    alerts = normalize(payload)
    groups = group_alerts(alerts)
    key, group = next(iter(groups.items()))
    ctx = build_context("inc-test", group, payload.get("context", {}))
    d = decide(ctx)
    return ctx, d, decide_route(ctx, d)


def test_scenario_1_production_outage_pages():
    ctx, d, route = run("production-outage.json")
    assert ctx.service.criticality == "tier-1"
    assert len(ctx.alerts) == 4, "four alerts should collapse into one incident"
    assert route.priority == "P1"
    assert route.channel == "pagerduty"
    assert d.customer_impact > 0.90


def test_scenario_2_dev_cpu_spike_does_not_page():
    ctx, d, route = run("dev-cpu-spike.json")
    assert ctx.service.environment == "development"
    assert route.channel != "pagerduty"
    assert route.priority in {"P3", "SUPPRESS"}


def test_scenario_3_deployment_regression_is_p2_and_surfaces_deploy_link():
    ctx, d, route = run("deployment-regression.json")
    assert route.priority == "P2"
    assert route.channel == "slack"
    assert d.deployment_related > 0.60, "alerts began 3 min after a 9-min-old deploy"
    assert route.target == "discovery"


def test_scenario_4_ambiguous_escalates_rather_than_guessing():
    ctx, d, route = run("ambiguous-alert.json")
    assert route.escalated_for_review is True


def test_severity_label_is_not_what_decides():
    """dev-cpu-spike is labelled severity=critical in YAML and must still
    not page. This is the whole thesis, as an assertion."""
    payload = load("dev-cpu-spike.json")
    assert payload["alerts"][0]["labels"]["severity"] == "critical"
    _, _, route = run("dev-cpu-spike.json")
    assert route.channel != "pagerduty"


@pytest.mark.parametrize("fixture", [
    "production-outage.json", "dev-cpu-spike.json",
    "deployment-regression.json", "ambiguous-alert.json",
])
def test_every_fixture_produces_a_route(fixture):
    """No alert is ever silently dropped."""
    _, _, route = run(fixture)
    assert route.priority in {"P1", "P2", "P3", "SUPPRESS"}
    assert route.reason
