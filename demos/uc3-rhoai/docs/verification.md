# Verification

| Layer | Command | Needs | Checks |
|---|---|---|---|
| Live | `make verify` (after `make scenarios` and `make eval`) | Running demo, `oc` login | MLflow in OpenShift AI, OpenShift AI Observability, cluster Prometheus, redaction, auth |
| Offline | `make test` | uv only | The three policies on the real agent graph (scripted model), RHOAI auth helpers |

## `make verify` (22 checks)

| # | Check |
|---|---|
| 1–7 | Traces: all three policies with the same agent; versioned decision names and reasons; blocked refunds never ran; v2's budget rejection and v3's false block are visible |
| 8 | Each policy run has the four rates |
| 9 | Each policy run has latency (RHOAI stack) and CPU/memory (cluster Prometheus) |
| 10 | Equivalent load (same labeled requests per policy) |
| 11–12 | Rollout gate: v2 PROMOTE, v3 REJECT |
| 13 | OpenShift AI Observability scrapes the agents for all three policies |
| 14 | **Product gap check:** the tenant-scoped query (`?namespace=uc3-rhoai`) returns no workload series. This flips to FAIL once RHOAI fixes the relabeling, which is the signal to drop the workaround. |
| 15 | OpenShift AI Observability has decision counters per policy |
| 16 | The cluster Prometheus has container CPU for each policy pod |
| 17–20 | No SSN in the traces or in the three ATOF files |
| 21 | OTLP without a token → 302 (the gateway redirects to login) |
| 22 | The agent's token → 403 on a non-granted experiment in the same workspace |

Live output, 2026-11-24 (abridged):

```
  [PASS] All three policy versions are traced, with the same (fixed) agent   v1: 34, v2: 34, v3: 34; agent versions: ['v1']
  [PASS] MLflow shows v2's per-request budget at work
         refund-policy-v2: refund of $300.00 would bring this request's refunds to $600.00, above the $500.00 per-request budget; ...
  [PASS] MLflow shows v3 blocking a refund the business rule allows          refund-policy-v3 rejected $350.00
  [PASS] Evaluation: each policy run has correct blocks, false blocks, prohibited allowed, task completion
         v1: CB 46% PA 15% FB 0% TC 100% | v2: CB 62% PA 0% FB 0% TC 100% | v3: CB 46% PA 15% FB 38% TC 62%
  [PASS] Evaluation: each policy run has latency and resource metrics from OpenShift AI Observability
         v1: p95 21.4s cpu 1.4s mem 163MB | v2: p95 28.5s cpu 1.3s mem 164MB | v3: p95 29.2s cpu 1.3s mem 163MB
  [PASS] Rollout gate: v2 (per-request budget) is PROMOTED                   prohibited allowed v1 15% -> v2 0%
  [PASS] Rollout gate: v3 (over-strict) is REJECTED for false blocks
OpenShift AI Observability
  [PASS] OpenShift AI Observability scrapes the agents' metrics for all three policies   v1: 34, v2: 34, v3: 34 requests
  [PASS] Product gap: the tenant-scoped query (?namespace=<project>) returns no workload series
  [PASS] OpenShift AI Observability has guardrail decision counters per policy
  [PASS] Cluster Prometheus has CPU/memory for each policy's pod (RHOAI dashboards' resource source)
  [PASS] The agent's service account cannot write to an experiment its Role does not name   HTTP 403
22/22 checks passed.
```

## `make test` (offline, 19 tests)

- The 16 policy tests from `uc3-community` (`tests/test_policies.py`).
- The 3 RHOAI auth tests from `uc2-rhoai` (`tests/test_rhoai_auth.py`):
  - the bearer header file follows token rotation;
  - the TLS block is optional;
  - the OTLP endpoint isn't under MLflow's static prefix.
