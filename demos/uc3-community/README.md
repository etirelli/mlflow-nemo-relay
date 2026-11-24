# UC3 (community): Validate guardrail changes before rollout

The same support agent runs under three versions of a **NeMo Relay** refund
policy. The agent never changes. **MLflow** evaluates each policy on the same
labeled allowed and prohibited requests: correct blocks, false blocks,
prohibited actions allowed, and task completion. **Prometheus** adds latency
and resource context under equivalent load. A rollout gate then promotes or
rejects each candidate against the policy in production.

The business rule: *a support agent may refund up to $500 per customer
request; anything more needs a supervisor.*

| Policy | Rule as implemented | Role |
|---|---|---|
| `refund-policy-v1` | $500 per refund **call** | In production (UC2's policy). Two refunds in one request each pass on their own. |
| `refund-policy-v2` | $500 per customer **request**, all refunds combined | Candidate: the real fix |
| `refund-policy-v3` | $300 per refund call | Candidate: "just make it stricter" |

| Component | Version | Role |
|---|---|---|
| [NeMo Relay](https://github.com/NVIDIA/NeMo-Relay) | 0.11.0 | The policy versions (conditional-execution guardrails), decision telemetry, PII redaction, OTLP export |
| [MLflow](https://github.com/mlflow/mlflow) | 3.17.2 | Traces with versioned decisions; GenAI evaluation (labeled dataset, code scorers, LLM judge); one run per policy with the comparison and the rollout decision |
| [Prometheus](https://prometheus.io) | 3.5.0 | Request latency, guardrail cost, decisions, CPU and memory per policy |
| LangGraph / LangChain | 1.2 / 1.4 | The agent (UC2's v1, fixed) |
| Any OpenAI-compatible LLM | — | Agent and judge. Validated with GLM 5.3. |

**Status:** ✅ validated end to end on 2026-11-24 with GLM 5.3, from a clean
start:
- `make verify` passes 20/20;
- `make eval` meets the success criteria (v2 promoted, v3 rejected);
- `make test` passes 16 offline tests.

## Results

Live run (GLM 5.3, 14 labeled cases plus one load round each, 4 workers, one
policy at a time):

| Metric | v1 (production) | v2 (budget) | v3 (stricter) |
|---|---|---|---|
| Correct blocks (prohibited requests kept within $500 by a block) | 67% | **75%** | 58% |
| **Prohibited actions allowed** | 17% | **0%** | 17% |
| **False blocks** (allowed requests blocked) | 0% | 0% | **35%** |
| **Task completion** (allowed requests fully served) | 100% | 100% | **65%** |
| Honest replies (LLM judge) | 100% | 100% | 100% |
| Latency p50 / p95 (s) | 9.8 / 28.9 | 11.8 / 39.0 | 12.2 / 28.8 |
| Guardrail cost p95 (ms) | 0.046 | 0.049 | 0.046 |
| CPU (s) / RSS max (MB) | 1.8 / 162 | 1.9 / 161 | 1.9 / 162 |
| **Rollout gate** | baseline | ✅ **PROMOTE** | ❌ **REJECT**: adds false blocks; completes fewer legitimate tasks |

How to read it:
- **v1's gap is real.** "Refund $300 and $300" refunded $600, because each
  call was within the per-call limit. v2 blocked the second $300.
- **Stricter isn't safer.** v3 blocked legitimate $350, $450 and $500
  refunds, and *still* let the $300 + $300 request through.
- Correct blocks don't add up to 100% with prohibited allowed. The
  remainder are requests the agent declined on its own (GLM 5.3 refused the
  openly worded "split it so it goes through").
- **The guardrail costs about 0.05 ms.** End-to-end latency is dominated by
  the LLM and varies between runs. v2's higher p95 is within the 1.5×
  budget. LLM results vary between runs; the direction is what matters.

## Quick start

Prerequisites: Podman (with `podman compose`) or Docker, uv, and an
OpenAI-compatible LLM endpoint with tool calling.

```bash
cd demos/uc3-community
cp .env.example .env          # LLM_BASE_URL, LLM_MODEL, LLM_API_KEY (gitignored)
make up                       # MLflow, Prometheus, the agent under policies v1 (:8000), v2 (:8001), v3 (:8002)
make demo                     # scenarios, policy comparison, verification
```

| URL | What |
|---|---|
| http://localhost:8000 | Chat UI. The toggle switches the **policy**; the agent stays the same. |
| http://localhost:5000 | MLflow (`admin`). `uc3-policy-validation` has the traces; `uc3-policy-validation-eval` has one run per policy, the labeled dataset, and the `rollout_decision` tags. |
| http://localhost:9090 | Prometheus. For example: `histogram_quantile(0.95, sum by (le, policy) (rate(uc3_chat_request_seconds_bucket[5m])))` |

To rehearse without an LLM, run `make up-scripted`, then `make demo
LLM_PROVIDER=scripted`. It's deterministic, and the judge is skipped.

## Documentation

| Doc | For |
|---|---|
| [docs/demo-script.md](docs/demo-script.md) | Presenters: a 6-minute talk track |
| [docs/architecture.md](docs/architecture.md) | Policy versions, the per-request budget, trace shapes, the comparison and the gate |
| [docs/evaluation.md](docs/evaluation.md) | Labeled set, the four rates, load, Prometheus queries, the gate |
| [docs/verification.md](docs/verification.md) | `make verify` (20 checks) and the offline tests |
| [Product gaps report](../../docs/product-gaps.md) | What was validated, and findings for Relay and MLflow (consolidated, repo root) |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems |

## Layout

```
uc3-community/
├── compose.yaml              # mlflow, mlflow-bootstrap, agent-policy-v1/v2/v3, prometheus, verify
├── Makefile                  # up / up-scripted / scenarios / eval / verify / demo / down / clean / test
├── .env.example              # LLM endpoint/model/key, business rule, ports, load
├── prometheus/prometheus.yml # one scrape job per policy service
├── relay/plugins.toml        # Relay telemetry: OTLP -> MLflow + pii_redaction
├── mlflow/                   # upstream MLflow with basic auth + bootstrap
├── agent/src/support_agent/
│   ├── policy.py             # the three policy versions (per call / per request budget)
│   ├── metrics.py            # Prometheus metrics
│   ├── evaluation.py         # `make eval`: labeled set, rates, load, Prometheus, rollout gate
│   ├── verify.py             # `make verify`
│   └── …                     # agent (UC2 v1), tools, app, relay_runtime, scripted model, scenarios, UI
├── tests/                    # offline: each policy on the real agent graph, budget, boundaries, metrics
└── docs/
```
