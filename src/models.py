"""Typed incident state. The context we build is the whole product;
Jev only ever sees what we put in here."""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field

Environment = Literal["production", "staging", "development"]
Criticality = Literal["tier-1", "tier-2", "tier-3"]


class AlertFacts(BaseModel):
    name: str
    value: Optional[float] = None
    duration_seconds: int = 0
    labels: dict[str, str] = Field(default_factory=dict)


class ServiceFacts(BaseModel):
    name: str
    environment: Environment = "production"
    criticality: Criticality = "tier-3"
    owner: str = "unknown"
    customer_facing: bool = False


class KubernetesFacts(BaseModel):
    desired_replicas: Optional[int] = None
    available_replicas: Optional[int] = None
    restarts_last_10m: Optional[int] = None

    @property
    def unavailable_fraction(self) -> Optional[float]:
        if not self.desired_replicas:
            return None
        avail = self.available_replicas or 0
        return round(1 - (avail / self.desired_replicas), 3)


class TrafficFacts(BaseModel):
    requests_per_second: Optional[float] = None
    http_5xx_rate: Optional[float] = None
    p99_latency_ms: Optional[float] = None


class DeploymentFacts(BaseModel):
    deployed_minutes_ago: Optional[int] = None
    version: Optional[str] = None
    previous_version: Optional[str] = None


class IncidentContext(BaseModel):
    """What we send to Jev. Deliberately small, typed, and free of
    raw log lines, request bodies, secrets and customer data."""
    incident_id: str
    alerts: list[AlertFacts]
    service: ServiceFacts
    kubernetes: KubernetesFacts = Field(default_factory=KubernetesFacts)
    traffic: TrafficFacts = Field(default_factory=TrafficFacts)
    deployment: DeploymentFacts = Field(default_factory=DeploymentFacts)

    def as_state(self) -> dict:
        """The exact object handed to Jev as `state`."""
        d = self.model_dump(exclude_none=True)
        uf = self.kubernetes.unavailable_fraction
        if uf is not None:
            d.setdefault("kubernetes", {})["unavailable_fraction"] = uf
        d["alert_count"] = len(self.alerts)
        d["alert_names"] = [a.name for a in self.alerts]
        return d


class Decisions(BaseModel):
    """Jev's judgments. Probabilities and scores only: no priority here."""
    customer_impact: float
    material_degradation: float
    requires_immediate_attention: float
    deployment_related: float
    domain: str
    domain_confidence: float
    impact_score: float          # expected value across the ordered rubric
    impact_level: str            # nearest rubric level, for humans
    impact_confidence: float
    model: str = "mock"
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def raw_ambiguity(self) -> float:
        """Distance of the least decisive Noul from 0.5, as a 0..1 score.

        DISPLAY ONLY. We do not gate on this, and the reason is worth
        knowing: it cannot tell "the model is unsure" apart from "the
        answer is genuinely moderate". A half-degraded service SHOULD
        score ~0.6 on customer impact; that is a confident answer, not a
        hesitant one. Gating on it sent every mid-severity incident to
        human review. Policy uses boundary fragility instead - see
        policy.py:is_fragile."""
        nouls = [
            self.customer_impact,
            self.material_degradation,
            self.requires_immediate_attention,
        ]
        return round(min(abs(p - 0.5) * 2 for p in nouls), 3)


class Route(BaseModel):
    priority: Literal["P1", "P2", "P3", "SUPPRESS"]
    channel: Literal["pagerduty", "slack", "jira", "none", "review"]
    target: str
    reason: str
    escalated_for_review: bool = False
