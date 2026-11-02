# Joint use cases: NeMo Relay, MLflow, and OpenShift AI Observability

This summarizes the collaboration proposal and maps each use case to the demos in this repo.

**Product responsibilities**

| Product | Contribution |
|---|---|
| NVIDIA NeMo Relay | Sanitization before export, conditional execution controls, guardrail decision telemetry |
| MLflow (upstream and in OpenShift AI) | Trace inspection, evaluation datasets, comparisons across agent and policy versions |
| OpenShift AI Observability | Telemetry routing, serving metrics, latency and resource context |

---

## Use case 1: Observe tool calls without exposing sensitive inputs  *(preferred first demo)*

**Customer problem.** A customer lookup tool needs a Social Security number to
do its job. Developers need to inspect tool-call outcomes without putting
that identifier into stored traces.

**Demonstration**
1. **Run a customer lookup.** A LangGraph agent receives a chat message or API
   request and calls a lookup tool with a synthetic SSN. Show a successful
   lookup and a controlled failure, a tool timeout.
2. **Sanitize and export.** NeMo Relay redacts the SSN from tool-call spans
   before exporting them to MLflow. The tool still receives the original input.
3. **Inspect in MLflow.** Show both tool calls with their status, duration, and
   place in the agent run. Confirm the SSN is redacted and the failure is
   still understandable.

**Product gaps to validate.** SSN field redaction, including echoed inputs in
results and error details. Span parentage and status preserved through OTLP
export. Authenticated routing to the correct MLflow project and experiment.

**Success criteria.** MLflow shows both lookup outcomes with useful timing and
error context. The synthetic SSN is absent from exported telemetry, and the
permitted lookup still works.

➡️ Implemented in [`demos/uc1-community`](../demos/uc1-community). Its
[product-gap findings](../demos/uc1-community/docs/product-gaps.md) record what
we validated.

---

## Use case 2: Use guardrail decisions to improve agent behavior

A guardrail stops an unauthorized action, but the agent keeps attempting it.
Relay blocks the restricted tool action before execution and exports the
decision. An engineer reviews the pattern in MLflow, updates the system prompt
or tool definitions, and evaluates both agent versions against the same
allowed and prohibited requests. The policy stays fixed, and the guardrails
stay on during evaluation.

**Gaps.** Enforcement in the LangGraph integration. Exporting guardrail events to
MLflow with the attempted action, decision, reason, and policy version.
Telling a policy rejection apart from a tool failure.

➡️ Planned: `demos/uc2-community`. It can reuse the UC1 agent and add a Relay
conditional-execution guardrail.

---

## Use case 3: Validate guardrail changes before rollout

Run the same agent and a labeled set of allowed and prohibited requests against
two policy versions. Compare correct blocks, false blocks, prohibited actions
allowed, and task completion in MLflow. OpenShift AI Observability adds latency
and resource context under equivalent load. The agent stays fixed while the
policy changes.

➡️ Planned: `demos/uc3-rhoai`. It needs OpenShift AI Observability.

---

## Roadmap from the proposal

- **First 30 days:** select tested LangGraph, Relay, and MLflow versions.
  Validate SSN redaction, authenticated export, and project isolation. Build
  the synthetic lookup demo and a 5-minute recording. *This repo's UC1 demo
  covers this.*
- **Days 31–60:** joint integration tutorial, an OpenShift AI deployment blog,
  and the guardrail-to-evaluation workflow (UC2).
- **Days 61–90:** a policy-validation workshop (UC3) and an event showcase.
