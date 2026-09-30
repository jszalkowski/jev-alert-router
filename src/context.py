"""Context enrichment. In a real deployment these are API calls to your
service catalogue, the Kubernetes API and your deployment tracker.

Here they read from a local catalogue plus whatever the webhook carried,
so the demo runs with no cluster and no credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import (
    AlertFacts,
    DeploymentFacts,
    IncidentContext,
    KubernetesFacts,
    ServiceFacts,
    TrafficFacts,
)

CATALOG_PATH = Path(os.getenv("SERVICE_CATALOG", Path(__file__).parent.parent / "fixtures" / "service-catalog.json"))


def _catalog() -> dict[str, Any]:
    if CATALOG_PATH.exists():
        return json.loads(CATALOG_PATH.read_text())
    return {}


def lookup_service(name: str, environment_hint: str | None = None) -> ServiceFacts:
    cat = _catalog()
    entry = cat.get(name)
    if not entry:
        # Unknown service. Fail toward "we don't know", never toward "unimportant".
        return ServiceFacts(
            name=name,
            environment=environment_hint or "production",
            criticality="tier-3",
            owner="unknown",
            customer_facing=False,
        )
    return ServiceFacts(**{"name": name, **entry})


def build_context(
    incident_id: str,
    alerts: list[AlertFacts],
    extra: dict[str, Any] | None = None,
) -> IncidentContext:
    """`extra` carries the facts a webhook cannot know: cluster state,
    traffic and deployment metadata. In production these come from the
    Kubernetes API and your deploy tracker."""
    extra = extra or {}
    labels = alerts[0].labels if alerts else {}
    service_name = (
        labels.get("service") or labels.get("job") or labels.get("app") or "unknown"
    )
    env_hint = labels.get("environment") or labels.get("env")

    service = lookup_service(service_name, env_hint)
    if env_hint:
        service.environment = env_hint  # webhook wins; it knows where it fired

    return IncidentContext(
        incident_id=incident_id,
        alerts=alerts,
        service=service,
        kubernetes=KubernetesFacts(**extra.get("kubernetes", {})),
        traffic=TrafficFacts(**extra.get("traffic", {})),
        deployment=DeploymentFacts(**extra.get("deployment", {})),
    )
