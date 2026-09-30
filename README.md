# jev-alert-router

Alert severity is decided in YAML, months before the alert fires, by someone
who cannot know the context it will fire in. This is a small experiment in
deciding it at runtime instead.

**Jev makes judgments. Code owns policy.** That separation is the whole point.

```
telemetry -> context enrichment -> Jev judgments -> deterministic policy -> routing
```

Jev never assigns a priority, picks a channel, or decides who gets paged.
It answers bounded questions about state. Every consequence lives in
[`src/policy.py`](src/policy.py), in plain Python you can read in one sitting.

## Run it

No API key, no cluster, no network:

```bash
git clone https://github.com/<you>/jev-alert-router && cd jev-alert-router
uv venv && uv pip install -e ".[dev]"
JEV_MODE=mock python scripts/demo.py
```

Or the webhook path:

```bash
JEV_MODE=mock uvicorn src.app:app --port 8000
curl -X POST localhost:8000/alerts -H 'Content-Type: application/json' \
     -d @fixtures/production-outage.json
```

```
Incident: checkout-api  (production, tier-1)
Alerts:   4  ->  HighHttpErrorRate, KubernetesPodCrashLooping, HighLatency, DatabaseConnectionPoolHigh
Priority: P1
Owner:    payments
Action:   pagerduty

Jev decisions (mock, 0 ms):
  customer impact:       0.98
  material degradation:  0.98
  immediate attention:   0.97
  deployment related:    0.85
  domain:                application (confidence 0.61)
  impact:                critical (score 3.84)

Reason:   tier-1 service, customer impact 0.98 > 0.90, immediate attention 0.97 > 0.90.
```

Four alerts. One incident. One page.

## Two modes

| | |
|---|---|
| `JEV_MODE=mock` | Deterministic stand-in. No key, no network. Exercises the architecture. **Says nothing about Jev.** |
| `JEV_MODE=live` | Real [TypeSafe API](https://docs.typesafe.ai). Needs `TYPESAFE_API_KEY`. Jev is in early access as of September 2026. |

Mock mode is a transparent heuristic over the same context, not a prediction of
what Jev would answer. It exists so the repo runs for everyone; only live mode
tells you anything about the model.

## The four scenarios

```bash
JEV_MODE=mock python scripts/demo.py
```

| Scenario | Signals | Route |
|---|---|---|
| Production outage | tier-1, 23% 5xx, 40% replicas down, deployed 9 min ago | **P1 → PagerDuty** |
| Dev CPU spike | `severity: critical` in YAML, development, no traffic | **P3 → Jira** (never pages) |
| Deployment regression | tier-2, 6% 5xx, deployed 4 min ago | **P2 → Slack** |
| Ambiguous | tier-1 sitting exactly on the paging threshold | **escalated for review** |

Scenario 2 is the point of the exercise: the alert is labelled
`severity: critical` and still does not page, because nothing is affected.

## Tests

```bash
pytest -q        # 29 passed
```

Two different things get tested, and conflating them is how you fool yourself:

- **`test_policy.py`** — is our deterministic policy correct? No network, Jev's
  judgments supplied as fixed inputs. This half must be provably right.
- **`test_scenarios.py`** — does the pipeline behave end to end?
- **`scripts/evaluate.py`** — does *Jev* make useful judgments? Needs live mode
  and a labelled dataset. Four fixtures is a smoke test with opinions, not an
  evaluation.

## Measure it

```bash
JEV_MODE=live BENCH_RUNS=100 python scripts/benchmark.py
```

Reports latency, request count, token usage, fallback count and routing spread.
It deliberately does **not** compute cost: turning a per-token price into a
per-incident figure depends on your context size and alert volume, and a made-up
number is worse than no number.

## Shadow mode first

Do not let this page anyone on day one. Add it as a second Alertmanager
receiver with `continue: true` and compare against what your existing routing
did ([`prometheus/alertmanager.yml`](prometheus/alertmanager.yml)).

`ROUTER_DRY_RUN=true` is the default and real delivery raises
`NotImplementedError` on purpose.

## Fail-safe

If the decision layer is unavailable, `decide()` returns `None` and policy falls
back to the static `severity` label that shipped with the alert. Degraded, never
silent. There is no path where an alert is dropped because an API was down.

## Layout

```
src/models.py      typed incident state; what Jev is allowed to see
src/normalize.py   Alertmanager webhook -> alerts, plus dumb deterministic correlation
src/context.py     enrichment: service catalogue, cluster, deployment
src/jev.py         the six questions, mock and live
src/policy.py      every operational decision. plain Python. no model.
src/routing.py     dry-run dispatch
src/app.py         webhook receiver
```

## What this is not

Not an AIOps platform, not correlation worth the name (same service + window,
deliberately), and not something to put in front of your pager without weeks of
shadow data. See [docs/architecture.md](docs/architecture.md) for the failure
modes, including what happens on untrusted alert text.

Built against `typesafe-sdk` 0.7.2 and the TypeSafe docs as of September 2026.
