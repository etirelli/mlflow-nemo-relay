# Product-gap validation and findings (UC3, community)

Validated on 2026-11-24 with **NeMo Relay 0.11.0**, **MLflow 3.17.2**,
**Prometheus 3.5.0**, LangGraph 1.2 / LangChain 1.4, and GLM 5.3 as the agent
LLM and the judge.

The proposal's UC3:

> *Run the same agent and a labeled set of allowed and prohibited requests
> against two policy versions. Compare correct blocks, false blocks,
> prohibited actions allowed, and task completion in MLflow. OpenShift AI
> Observability adds latency and resource context under equivalent load. The
> agent stays fixed while the policy changes.*

| Requirement | Status | How |
|---|---|---|
| Same agent, policy changes | ✅ | One image, `AGENT_VERSION=v1` everywhere, `POLICY_VERSION` per service |
| Labeled allowed/prohibited set | ✅ | 14 cases labeled by the business rule ($500 per request), stored as an MLflow evaluation dataset |
| Compare correct blocks, false blocks, prohibited allowed, task completion in MLflow | ✅ | One run per policy with the four rates; per-row scorers and judge rationales |
| Latency and resource context under equivalent load | ✅ community / 🔜 RHOAI | Same cases, rounds and concurrency per policy; Prometheus queried per policy window. OpenShift AI Observability comes in `uc3-rhoai`. |
| Decide on rollout | ✅ (beyond the proposal) | A gate tags each candidate run `PROMOTE` or `REJECT`, with reasons |
| Two policy versions | ✅ +1 | Production (v1), the real fix (v2), and an over-strict candidate (v3) to show that the comparison catches a regression |

## Findings

| # | Area | Finding | Impact | Suggestion |
|---|---|---|---|---|
| 1 | **Relay** | **Guardrail callbacks get no request or session context.** `register_tool_conditional_execution` callbacks receive `(tool_name, args)` only. A per-request budget (v2) works because Relay calls the Python callback in the caller's `contextvars` context, which is undocumented behavior. | Stateful policies (budgets, rate limits, "at most one refund per customer per day") rely on an implementation detail. | Pass a context object (the scope stack, the agent/request scope id and its metadata) to the callback, or offer stateful guardrails with a per-scope store. |
| 2 | **Relay** | **No shadow or dry-run mode.** You can compare policies only by running one deployment per policy. A candidate can't evaluate alongside production on the same traffic and record "would have blocked". | Comparisons need separate deployments and replayed traffic. Real traffic can't be used safely. | A `mode = "shadow"` for guardrails: evaluate and record the decision (`would_reject`), but don't enforce. MLflow could then compare policies on the same traces. |
| 3 | **Relay** | **The policy version is a naming convention** (`refund-policy-v2`), as in UC2 finding 3. UC3 depends on it for every comparison. | Fragile; nothing stops two different rules from sharing a name. | Declarative guardrails with `policy_id` and `version` attributes on every decision. |
| 4 | **Policy design** | **Per-call limits can't express per-request rules, and tightening doesn't fix that.** v3 ($300 per call) is stricter than v1 but still allowed "$300 and $300" ($600). Meanwhile it blocked legitimate $350 and $450 refunds. | "Stricter" isn't "safer". Only the evaluation against labeled cases shows the trade-off. | This is the core UC3 message: evaluate the policy, don't reason about it. |
| 5 | **MLflow** | **No metrics per slice.** Correct blocks and false blocks are rates over *subsets* (prohibited vs allowed rows). Scorers can't be restricted to a slice, so a scorer's mean mixes both. | The demo computes the four rates itself and logs them as run metrics. Per-row scorers stay for drill-down. | Aggregate scorer results grouped by an expectation field (`label`), or let a scorer return "not applicable" for a row. |
| 6 | **MLflow** | **There's no first-class place for a deployment decision.** The gate result is a run tag (`rollout_decision`). | It works, but it isn't visible in the evaluation comparison view. | Show run tags in the evaluation-run comparison, or support "baseline vs candidate" assertions on evaluation runs. |
| 7 | **Prometheus client** | **Lazily created labeled series lose early increments.** `increase()` over a window can't count the increments before a series' first sample. The first scripted run counted 18 of 29 requests. | Wrong request counts and quantiles on fresh services. | Create the labeled series at startup (the demo does). |
| 8 | **Measurement** | **The guardrail costs microseconds. Behavior changes latency.** A block adds a model turn to explain it, and the LLM dominates end-to-end latency. | Latency differences between policies reflect how often they block, plus LLM noise. | Compare p95 with a generous budget (1.5×), and read `guardrail_eval_p95_ms` for the policy's own cost. |

## Open items

- [ ] `uc3-rhoai`: the same comparison on OpenShift AI, with latency and resources from **OpenShift AI Observability** (RHOAI Monitoring CR with metrics, plus Cluster Observability, OpenTelemetry and maybe Tempo operators). Research the 3.6 prerequisites, then show the install plan before any cluster change.
- [ ] Report findings 1–3 to NeMo Relay and 5–6 to MLflow.
