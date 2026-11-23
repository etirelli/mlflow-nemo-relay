# Architecture

## Data flow

```mermaid
flowchart LR
    user["Support engineer<br/>(chat UI / REST)"] --> app["FastAPI<br/>agent v1 :8000 / v2 :8001"]

    subgraph proc["Agent process"]
        app --> agent_graph["LangGraph agent<br/>PolicyDecisionMiddleware<br/>+ NemoRelayMiddleware"]
        agent_graph -->|"managed LLM call"| llm[("LLM<br/>OpenAI-compatible")]
        agent_graph -->|"managed tool call<br/>issue_refund(amount=900)"| guard{"Relay guardrail<br/>refund-limit-v1"}
        guard -->|"allowed"| tool["issue_refund<br/>(refund ledger)"]
        guard -.->|"rejected: never executes"| blocked["BLOCKED_BY_POLICY<br/>tool result"]
        blocked --> agent_graph
        guard -. "decision event" .-> pii["Relay pii_redaction"]
        pii -. "sanitized events" .-> otel["OTLP exporter"]
    end

    otel -->|"POST /v1/traces"| mlflow["MLflow<br/>experiment uc2-refund-agent"]
    evalr["make eval<br/>(laptop)"] -->|"same requests"| app
    evalr -->|"runs, scores, dataset"| mlfeval["MLflow<br/>uc2-refund-agent-eval"]
```

## The policy lives in Relay; the agent changes

| | Where | v1 → v2 |
|---|---|---|
| **Policy** | `RefundPolicy`, registered with `nemo_relay.guardrails.register_tool_conditional_execution("refund-limit-v1", …)` | **Unchanged** |
| **Agent** | System prompt + tool definitions in `agent.py` / `tools.py` | **Changed**: v2 knows the limit and gets `request_supervisor_approval` |

Relay runs conditional-execution guardrails **before** the tool callback.
Returning a reason blocks the call. Returning `None` allows it.

```python
class RefundPolicy:
    def __call__(self, tool_name, args):
        if tool_name == "issue_refund" and float(args["amount"]) > self.limit:
            return f"{self.name}: refund of ${amount:,.2f} exceeds the ${limit:,.2f} limit ..."
        return None
```

Relay 0.11 has no config-file component for custom conditional-execution
guardrails (only `pii_redaction` and the deprecated NeMo Guardrails
component). So the policy is registered in code, and its version is part of
its name.

## From rejection to agent behavior

Relay signals a rejection by raising `RuntimeError("guardrail rejected: …")`
out of the managed tool call. Unhandled, that aborts the whole LangGraph run:
the user gets an error and the agent can't adapt. `PolicyDecisionMiddleware`
turns it into an ordinary tool result:

```
ToolMessage(status="error",
            content="BLOCKED_BY_POLICY: refund-limit-v1: refund of $900.00 exceeds ... The action was not executed.")
```

**Middleware order matters.** LangChain composes middleware first-defined =
outermost: `[PolicyDecisionMiddleware(), NemoRelayMiddleware()]`. Relay
records the decision first, and the policy middleware then converts the
exception on the way out.

## What MLflow receives

For a blocked refund:

```
support-request                       AGENT   demo.agent_version = v1, demo.policy = refund-limit-v1
└── support_agent_v1                  AGENT
    ├── model → <llm>                 LLM     decides to call issue_refund(amount=900)
    ├── tools                         AGENT   input: [{"name": "issue_refund", "args": {"amount": 900, ...}}]
    │   └── refund-limit-v1           GUARDRAIL
    │         start: kind=tool_conditional_execution, target_name=issue_refund
    │         end:   allowed=false, rejected=true, rejection_reason="refund-limit-v1: refund of $900.00 exceeds ..."
    │         (no issue_refund TOOL span: the tool never started)
    └── model → <llm>                 LLM     explains the block to the user
```

For an allowed refund, the `GUARDRAIL` span has `allowed=true` and an
`issue_refund` `TOOL` span follows. For a tool failure (lookup timeout) there
is a `TOOL` span with status `ERROR` and no rejection. That's how policy
rejections and tool failures stay distinguishable.

The **refund ledger** (`refunds.py`) is independent evidence. Every executed
refund is recorded with the id of the request that made it, and the chat API
returns `refunds_executed` per request. Evaluation and tests use it to prove
blocked refunds never ran. Requests are tagged with a context variable,
because the server handles requests concurrently, for example during
evaluation.

## Telemetry and redaction

As in UC1, `relay/plugins.toml` exports OpenInference-shaped OTLP to MLflow
(basic auth, `x-mlflow-experiment-id`), and `pii_redaction` removes SSNs
before export. Both agent versions write to one experiment,
`uc2-refund-agent`. The root span and resource attributes carry
`demo.agent_version` and `demo.policy`.

## Two agents, one image, one policy

`agent-v1` and `agent-v2` are the same image and the same Relay policy. They
differ only in `AGENT_VERSION`, which selects the system prompt and the tool
definitions.
