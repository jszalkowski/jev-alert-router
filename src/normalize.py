"""Alertmanager webhook -> normalized alerts, plus deliberately simple
deterministic correlation. Jev is not involved in either step."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import AlertFacts

CORRELATION_WINDOW_SECONDS = 600


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_seconds(alert: dict[str, Any], now: datetime | None = None) -> int:
    start = _parse_ts(alert.get("startsAt"))
    if not start:
        return 0
    now = now or datetime.now(timezone.utc)
    return max(0, int((now - start).total_seconds()))


def _float_or_none(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize(payload: dict[str, Any], now: datetime | None = None) -> list[AlertFacts]:
    """Accepts an Alertmanager v4 webhook body."""
    out: list[AlertFacts] = []
    for a in payload.get("alerts", []):
        if a.get("status") == "resolved":
            continue
        labels = {str(k): str(v) for k, v in (a.get("labels") or {}).items()}
        annotations = a.get("annotations") or {}
        out.append(
            AlertFacts(
                name=labels.get("alertname", "UnknownAlert"),
                value=_float_or_none(annotations.get("value")),
                duration_seconds=_duration_seconds(a, now),
                labels=labels,
            )
        )
    return out


def correlation_key(alert: AlertFacts) -> str:
    """Deliberately boring. Same service + same namespace = same incident,
    within a time window applied by the caller.

    This is NOT clever correlation, and it is not Jev's job. Real
    correlation wants a dependency graph and trace data; see docs/architecture.md.
    """
    labels = alert.labels
    service = labels.get("service") or labels.get("job") or labels.get("app") or "unknown"
    namespace = labels.get("namespace", "default")
    return f"{namespace}/{service}"


def group_alerts(alerts: list[AlertFacts]) -> dict[str, list[AlertFacts]]:
    groups: dict[str, list[AlertFacts]] = {}
    for a in alerts:
        groups.setdefault(correlation_key(a), []).append(a)
    return groups
