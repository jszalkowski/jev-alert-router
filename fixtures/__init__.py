"""Fixture loader.

Fixtures declare alert age as `_alert_age_minutes` and the loader stamps
`startsAt` relative to now. Hardcoded absolute timestamps rot: a fixture
written today claims an alert started weeks ago when you clone it next month,
which silently breaks any judgment that compares alert age to deployment age.

Found the hard way. Live Jev returned deployment_related=0.45 on a fixture
called "deployment-regression" because the alerts predated the deploy by well
over an hour. It was reading the data correctly; the data was wrong.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent


def load(name: str) -> dict[str, Any]:
    payload = json.loads((FIXTURES / name).read_text())
    age = payload.pop("_alert_age_minutes", 5)
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=age)).isoformat().replace("+00:00", "Z")
    for a in payload.get("alerts", []):
        a["startsAt"] = stamp
    return payload
