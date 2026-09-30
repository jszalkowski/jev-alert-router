import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.normalize import group_alerts, normalize, correlation_key

FIX = Path(__file__).parent.parent / "fixtures"


def test_parses_alertmanager_v4_payload():
    payload = json.loads((FIX / "production-outage.json").read_text())
    alerts = normalize(payload)
    assert len(alerts) == 4
    assert {a.name for a in alerts} == {
        "HighHttpErrorRate", "KubernetesPodCrashLooping",
        "HighLatency", "DatabaseConnectionPoolHigh",
    }


def test_resolved_alerts_are_dropped():
    payload = {"alerts": [
        {"status": "resolved", "labels": {"alertname": "Gone"}},
        {"status": "firing", "labels": {"alertname": "Here"}},
    ]}
    assert [a.name for a in normalize(payload)] == ["Here"]


def test_duration_is_computed_from_startsAt():
    start = (datetime.now(timezone.utc) - timedelta(minutes=7)).isoformat().replace("+00:00", "Z")
    payload = {"alerts": [{"status": "firing", "startsAt": start, "labels": {"alertname": "A"}}]}
    assert 380 <= normalize(payload)[0].duration_seconds <= 460


def test_four_alerts_one_service_collapse_to_one_incident():
    payload = json.loads((FIX / "production-outage.json").read_text())
    groups = group_alerts(normalize(payload))
    assert len(groups) == 1
    assert list(groups)[0] == "prod/checkout-api"
    assert len(next(iter(groups.values()))) == 4


def test_different_services_do_not_correlate():
    payload = {"alerts": [
        {"status": "firing", "labels": {"alertname": "A", "service": "a", "namespace": "prod"}},
        {"status": "firing", "labels": {"alertname": "B", "service": "b", "namespace": "prod"}},
    ]}
    assert len(group_alerts(normalize(payload))) == 2


def test_correlation_falls_back_through_label_names():
    from src.models import AlertFacts
    assert correlation_key(AlertFacts(name="x", labels={"job": "j", "namespace": "n"})) == "n/j"
    assert correlation_key(AlertFacts(name="x", labels={})) == "default/unknown"
