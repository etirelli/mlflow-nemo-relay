# UC3 on OpenShift AI: Validate guardrail changes before rollout

[`uc3-community`](../uc3-community) on **Red Hat OpenShift AI**. The same
support agent runs under three versions of a **NeMo Relay** refund policy, one
Deployment each. The agent never changes.

- **MLflow in OpenShift AI** evaluates each policy on the same labeled allowed
  and prohibited requests (correct blocks, false blocks, prohibited actions
  allowed, task completion), and tags each candidate PROMOTE or REJECT.
- **OpenShift AI Observability** adds latency and resource context under
  equivalent load.

The business rule: *a support agent may refund up to $500 per customer
request; anything more needs a supervisor.*

| Policy | Rule as implemented | Role |
|---|---|---|
| `refund-policy-v1` | $500 per refund **call** | In production (UC2's policy). Two refunds in one request each pass on their own. |
| `refund-policy-v2` | $500 per customer **request** | Candidate: the real fix |
| `refund-policy-v3` | $300 per refund call | Candidate: "just make it stricter" |

| Component | Version | Role |
|---|---|---|
| Red Hat OpenShift AI | 3.6.0-ea.2 | MLflow (workspaces, Kubernetes auth), **OpenShift AI Observability** (Technology Preview) |
| OpenShift | 4.22 (ROSA) | Builds, Deployments, RBAC, cluster monitoring |
| Cluster Observability Operator / Red Hat build of OpenTelemetry / Tempo | 1.5.5 / 0.158 / 0.22 | The RHOAI monitoring stack's prerequisites |
| NeMo Relay | 0.11.2 | The policy versions, decision telemetry, PII redaction, OTLP export |
| MLflow | 3.17.2 (client) | Traces, GenAI evaluation, rollout tags |
| Any OpenAI-compatible LLM | — | Agent and judge, configured locally. Validated with GLM 5.3. |

**Status:** ✅ validated live on 2026-11-24 on ROSA:
- `make verify` passes 22/22;
- the in-cluster evaluation promotes v2 and rejects v3;
- `make test` passes 19 offline tests.

## Results

Live run (GLM 5.3, 14 labeled cases plus one load round per policy, 4 workers,
one policy at a time, as an in-cluster Job):

| Metric | v1 (production) | v2 (budget) | v3 (stricter) | Source |
|---|---|---|---|---|
| Correct blocks | 46% | **62%** | 46% | MLflow evaluation |
| **Prohibited actions allowed** | 15% | **0%** | 15% | MLflow evaluation |
| **False blocks** | 0% | 0% | **38%** | MLflow evaluation |
| **Task completion** | 100% | 100% | **62%** | MLflow evaluation |
| Honest replies (LLM judge) | 100% | 100% | 100% | MLflow evaluation |
| Latency p50 / p95 (s) | 6.9 / 21.4 | 7.4 / 28.5 | 7.3 / 29.2 | **OpenShift AI Observability** (RHOAI monitoring stack) |
| Guardrail cost p95 (ms) | 0.030 | 0.044 | 0.045 | **OpenShift AI Observability** |
| CPU (s) / memory max (MB) | 1.4 / 163 | 1.3 / 164 | 1.3 / 163 | Cluster Prometheus (container metrics) |
| **Rollout gate** | baseline | ✅ **PROMOTE** | ❌ **REJECT**: adds false blocks; completes fewer legitimate tasks | MLflow run tags |

How to read it:
- v1's gap: "Refund $300 and $300" refunded $600. v2 blocked the second $300.
- v3 blocked legitimate $350, $450 and $500 refunds, and still let $300 + $300 through.
- The policy check costs about 0.03–0.05 ms. Latency differences come from
  the LLM and from the extra turn a block causes, and vary between runs.

## How the demo uses OpenShift AI Observability

- A `ServiceMonitor` labelled `monitoring.opendatahub.io/scrape: "true"` gets the
  agents' `/metrics` into the RHOAI monitoring stack, through its
  OpenTelemetry collector.
- Container CPU and memory come from the cluster Prometheus, which the RHOAI
  dashboards also use.
- "Observe & monitor → Dashboard" is turned on in the OpenShift AI dashboard.
- Two workarounds for RHOAI 3.6.0-ea.2 are part of the setup:
  - the evaluator gets a metrics read grant in `redhat-ods-monitoring`
    (`openshift/monitoring-access.yaml`);
  - the stack's Thanos route is restricted to an IP allowlist
    ([observability-setup.md](docs/observability-setup.md), step 4).

  The analysis is in the [product gaps report](../../docs/product-gaps.md)
  (OBS-1 to OBS-9).

## Quick start

Prerequisites:
- `oc` logged in as a cluster admin (for the one-time setup);
- OpenShift AI with MLflow;
- uv;
- an OpenAI-compatible LLM endpoint.

```bash
cd demos/uc3-rhoai
# One-time, per cluster: enable OpenShift AI Observability (operators + DSCI), see docs/observability-setup.md
cp config.env.example config.env                     # namespace, LLM endpoint/model, Secret name (gitignored)
oc new-project uc3-rhoai
read -rs "K?API key: "; oc create secret generic llm-credentials -n uc3-rhoai --from-literal=api-key="$K"; unset K
make up            # experiments, template, metrics grant, in-cluster build, rollout
make port-forward  # chat UI on http://localhost:8000 (policy toggle v1 / v2 / v3)
make demo          # scenarios, in-cluster policy comparison (Job), verification
```

| Where | What |
|---|---|
| http://localhost:8000 | Chat UI. Toggle the **policy**; the agent stays the same. |
| MLflow (`…/mlflow/?workspace=uc3-rhoai`) | `uc3-rhoai-policy-validation` has the traces; `uc3-rhoai-policy-validation-eval` has one run per policy, the labeled dataset and the `rollout_decision` tags. |
| OpenShift AI dashboard → Observe & monitor | The RHOAI monitoring stack's dashboards |

## Documentation

| Doc | For |
|---|---|
| [docs/observability-setup.md](docs/observability-setup.md) | One-time cluster setup of OpenShift AI Observability, including the security mitigation |
| [docs/demo-script.md](docs/demo-script.md) | Presenters: a 7-minute talk track |
| [docs/architecture.md](docs/architecture.md) | Deployments, identities, the metrics paths, the evaluation Job |
| [docs/configuration.md](docs/configuration.md) | `config.env`, templates and grants |
| [docs/evaluation.md](docs/evaluation.md) | Rates, load, queries, the gate (RHOAI specifics) |
| [docs/verification.md](docs/verification.md) | `make verify` (22 checks) and the offline tests |
| [Product gaps report](../../docs/product-gaps.md) | OpenShift AI Observability findings (consolidated, repo root) |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems |

## Layout

```
uc3-rhoai/
├── config.env.example          # namespace, LLM, business rule (copy to config.env, gitignored)
├── Makefile                    # up / monitoring-access / port-forward / scenarios / eval / verify / demo / down
├── openshift/
│   ├── template.yaml           # SAs, Roles, ConfigMaps, build, 3 policy Deployments + Services, ServiceMonitor
│   ├── eval-job.yaml           # the policy comparison as an in-cluster Job
│   └── monitoring-access.yaml  # evaluator read grant in redhat-ods-monitoring (see OBS-2 in the product gaps report)
├── relay/plugins.toml          # Relay: OTLP -> MLflow in OpenShift AI (bearer token, workspace) + pii_redaction
├── agent/src/support_agent/    # same agent and policies as uc3-community; RHOAI auth; RHOAI metrics queries
├── tests/                      # offline: the three policies, RHOAI auth
└── docs/
```
