# Product-gap validation and findings (UC2)

Validated on 2026-11-23 with **NeMo Relay 0.11.0**, **MLflow 3.17.2**,
LangGraph 1.2 / LangChain 1.4, and GLM 5.3 as both the agent LLM and the
judge.

The proposal's UC2 product gaps:

> *Validate enforcement in the selected LangGraph integration and guardrail
> event export to MLflow. Preserve the attempted action, decision, reason,
> and policy version. Distinguish policy rejection from tool failure and
> verify that blocked tools did not execute.*

| Gap | Status | How |
|---|---|---|
| Enforcement in the LangGraph integration | ✅ with a small adapter | `register_tool_conditional_execution` blocks before execution through `NemoRelayMiddleware`. The rejection surfaces as an exception, so `PolicyDecisionMiddleware` is needed (see finding 1). |
| Guardrail event export to MLflow | ✅ | `GUARDRAIL` spans (OpenInference span kind) with `nemo_relay.end.data.allowed`, `rejected` and `rejection_reason` |
| Preserve attempted action, decision, reason, policy version | ✅ / 🟡 | Decision and reason: on the guardrail span. Target tool: on the guardrail span. Requested **arguments**: only on the parent `tools` span (finding 2). Policy version: in the guardrail name and reason, by convention (finding 3). |
| Distinguish policy rejection from tool failure | ✅ | A rejection is a `GUARDRAIL` span with `rejected=true` and no `TOOL` span. A failure is a `TOOL` span with status `ERROR`. In the agent: a `BLOCKED_BY_POLICY` prefix versus the tool's own error. |
| Verify blocked tools did not execute | ✅ | No `TOOL` span for the call, plus an independent refund ledger. Checked live (`make verify`) and in evaluation (`blocked_never_executed`). |
| Success criteria (fewer prohibited attempts, legitimate tasks kept, guardrails on) | ✅ | `make eval`: prohibited attempts 20% → 0%, task completion 80% → 100%, and no blocked action executed |

## Findings

| # | Finding | Impact | Suggestion |
|---|---|---|---|
| 1 | **A rejection aborts the LangGraph run.** Relay raises `RuntimeError("guardrail rejected: …")` from the managed tool call. `handle_tool_error` does not catch it, because it isn't a `ToolException`. | Without an adapter the user gets an HTTP 502 and the agent can't react to the decision. This is the opposite of UC2's goal. | Relay's LangChain middleware could return a `ToolMessage(status="error")` with a stable marker, or raise a `ToolException` subclass (`GuardrailRejected`) with structured fields (policy, reason). The demo's `PolicyDecisionMiddleware` is about 30 lines. |
| 2 | **The guardrail span doesn't carry the tool arguments.** Its input is `{kind, target_name}` only. The requested arguments are on the parent `tools` span. | Investigating a block needs two spans. Exporters that drop the parent lose the attempted action. | Include the (sanitized) arguments in the guardrail scope's start data. Relay's redaction would still apply. |
| 3 | **No first-class policy version.** Conditional-execution guardrails are code callbacks with a name. There is no config-file component and no version field. | Policy versioning relies on naming conventions (`refund-limit-v1`). That's fragile for UC3, which compares policy versions. | A declarative guardrail component (TOML) with `policy_id` and `version` emitted as attributes on every decision. |
| 4 | **Guardrail span status is UNSET on rejection.** The decision is only in attributes. | UIs that colour by status show nothing special for a block. | Emit an explicit status, or a dedicated span event such as `guardrail.rejected`. |
| 5 | **Per-call guardrails can be circumvented by splitting.** "Two refunds of $450" passes a per-call $500 limit. | A real policy-design gap, caught by the `within_refund_limit` scorer and the judge rather than by the guardrail. | Stateful guardrails (per request or session budget). This is a good UC3 policy comparison. |
| 6 | **MLflow judge `base_url` means the full chat-completions URL.** | `https://host/v1` silently posts to the wrong path. EnMaaS returned an HTML 503 page. | MLflow: accept a base URL, or document it. The demo appends `/chat/completions`. |
| 7 | **Text verdicts aren't aggregated.** A judge with `feedback_value_type=Literal["yes","no"]` produces per-row values but no run metric. | The comparison table shows "n/a" for the judge. | Use `bool`, as the demo does, or aggregate categorical values. |
| 8 | **`mlflow-skinny` can't run judges.** `make_judge` imports `pandas` indirectly. | The agent image stays skinny. Evaluation needs the `eval` extra. | MLflow: lazy-import pandas in the judge path. |
| 9 | **Evaluation logs inputs outside Relay.** | SSNs in evaluation data would land in MLflow unredacted. | Keep evaluation datasets synthetic or sanitized. The demo uses customer ids. |

## Open items

- [ ] `uc2-rhoai`: the same on OpenShift AI (MLflow workspaces, the evaluation as a Job or from the laptop, the judge on the configured LLM).
- [ ] `uc2-openshell`: OpenShell blocks the refund service's *network* path as a second enforcement layer.
- [ ] `uc2-rhoai-openshell`: OpenShell on RHOAI, via the `opendatahub-io/openshell` installer.
- [ ] Report findings 1–4 to NeMo Relay and 6–8 to MLflow.
