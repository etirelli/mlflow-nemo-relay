# Demo script: 7 minutes

**Audience:** platform owners, ML engineers, risk and compliance, on OpenShift AI.
**Message:** *Before rolling out a guardrail change, evaluate it on OpenShift
AI: the same agent and the same labeled requests under each policy, with
correctness from MLflow and latency and resources from OpenShift AI
Observability, ending in a rollout decision.*

## Before you present (T-20 min)

```bash
cd demos/uc3-rhoai
make status && make port-forward && make demo   # expect "UC3 success criteria: MET" and "22/22 checks passed"
```

Open:
1. http://localhost:8000, the chat UI, on **v1 · $500/call**.
2. MLflow in OpenShift AI (`…/mlflow/?workspace=uc3-rhoai`) →
   **uc3-rhoai-policy-validation-eval**.
3. OpenShift AI dashboard → **Observe & monitor → Dashboard**.
4. The OpenShift console → Projects → `uc3-rhoai` → Workloads, showing three
   Deployments of the same image.

## 1. Same agent, three policies (45 s)

Show the three Deployments in the console. Same image, same agent, only
`POLICY_VERSION` differs.

> "We're not changing the agent. We're changing the NeMo Relay policy in front
> of its refund tool, and we want proof before rollout."

## 2. The gap and two fixes (75 s)

In the chat UI, send **$300 + $300 (one request)** under each policy:

| | v1 · $500/call | v2 · $500/request | v3 · $300/call |
|---|---|---|---|
| Result | Both refunds succeed: **$600** | One refund succeeds, one is blocked: "would bring this request's refunds to $600" | Both succeed: **$600** |

Then **Refund $450 (allowed)** under v3: it's blocked, a false block.

## 3. The evaluation in MLflow (2 min)

`uc3-rhoai-policy-validation-eval` → compare **policy-v1**, **policy-v2** and
**policy-v3**:

| | v1 | v2 | v3 |
|---|---|---|---|
| Prohibited actions allowed | 15% | **0%** | 15% |
| False blocks | 0% | 0% | **38%** |
| Task completion | 100% | 100% | **62%** |

Show the tags: v2 `rollout_decision = PROMOTE`, v3 `REJECT` ("adds false
blocks; completes fewer legitimate tasks").

> "The Job ran inside the cluster with its own service account. It used the
> same agents, the same 14 labeled requests, and the same load per policy. The
> judge's key never left the cluster."

## 4. Latency and resources from OpenShift AI Observability (90 s)

On the same runs: `latency_p95_s`, `guardrail_eval_p95_ms` (about 0.04 ms),
`cpu_seconds` and `memory_max_mb`.

> "The latency comes from OpenShift AI's own monitoring stack: one labelled
> ServiceMonitor and the agents are scraped. CPU and memory come from cluster
> monitoring, the same source the OpenShift AI dashboards use. The policy
> check itself costs microseconds. Latency is the LLM, and every block adds a
> turn."

Show the "Observe & monitor" dashboard.

## 5. What we found (45 s)

> "It's Technology Preview, and we found real gaps to report:
> - a public, unauthenticated Thanos route, which we restricted to an IP allowlist;
> - workload metrics relabeled to the monitoring namespace, so a project can't
>   query its own metrics through the tenant path;
> - no container metrics in the stack itself."

## 6. Close (30 s)

```bash
make verify     # 22/22
```

> "On OpenShift AI, a policy change becomes an evaluation with a rollout
> decision. MLflow holds the evidence, and the platform's own observability
> provides the operational context."
