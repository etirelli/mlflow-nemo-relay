# Architecture

## Components and data flow

```mermaid
flowchart LR
    user["Support engineer<br/>(chat UI / REST)"] -->|"message with SSN"| api["FastAPI<br/>agent-redacted :8000"]

    subgraph proc["Agent process"]
        api --> scope["Relay agent scope<br/>customer-lookup-request"]
        scope --> graph["LangGraph agent<br/>create_agent + NemoRelayMiddleware"]
        graph -->|"managed LLM call"| llm[("LLM<br/>OpenAI-compatible")]
        graph -->|"managed tool call<br/>ssn=900-12-0001"| tool["lookup_customer"]
        tool --> db[("Synthetic records<br/>+ slow legacy shard")]

        graph -. "lifecycle events<br/>(raw values)" .-> pii["Relay pii_redaction<br/>sanitize guardrails"]
        pii -. "sanitized events<br/>[REDACTED-SSN]" .-> otel["OTLP exporter<br/>(OpenInference projection)"]
        pii -. "sanitized events" .-> atof["ATOF file sink<br/>/app/telemetry"]
    end

    otel -->|"HTTP/protobuf POST /v1/traces<br/>Authorization: Basic …<br/>x-mlflow-experiment-id"| mlflow["MLflow 3.17<br/>basic-auth server :5000"]
    mlflow --> ui["MLflow UI<br/>Traces"]
```

The solid lines are real execution: the LLM and the tool get the real SSN, and
so does the user, who is entitled to it. The dotted lines are telemetry. Every
telemetry event passes through the `pii_redaction` plugin before any
subscriber or exporter receives it.

## The redaction boundary

Relay records each unit of work as a **scope** with start/end events. Managed
LLM and tool calls get their own scopes. The request payload is on the start
event and the result on the end event. The `pii_redaction` plugin installs
**sanitize guardrails**, not execution intercepts:

- It changes only the *observable copy* of each event.
- The real tool arguments, LLM requests, and return values are unchanged.
- Each event is sanitized once, during queued publication. After that, every
  exporter (OTLP to MLflow, ATOF file) consumes the same sanitized stream.
  A new exporter cannot bypass the policy by accident.

Exporters project one event onto many attributes. In the baseline, a single
trace carries the SSN about 90 times: `input.value`, `tool.parameters`,
`tool_call.function.arguments`, `nemo_relay.start.data.*`,
`nemo_relay.end.output.*`, LLM message attributes, previews, and more. That is
why redaction must happen at the event level, before projection. Patching
individual span attributes in each backend does not scale.

The policy ([`relay/plugins.redacted.toml`](../relay/plugins.redacted.toml)) has two profiles:

| Profile | Selector | Catches |
|---|---|---|
| 1. field-level | JSON pointer `/ssn`, any value | The structured `ssn` argument and the `ssn` field echoed in the tool result, whatever their format |
| 2. pattern | regex `\b\d{3}[- ]\d{2}[- ]\d{4}\b` on every string leaf | The SSN in the user message, LLM prompts and responses, echoed text in results, tool **error messages**, and the agent request/response |

## Trace structure in MLflow

Relay's `openinference` projection sets `openinference.span.kind`. MLflow's
OTLP ingestion translates that into MLflow span types, so traces render
natively:

```
customer-lookup-request            AGENT   (root: request/response previews)
└── customer_lookup_agent          AGENT   (LangGraph graph run)
    ├── model                      AGENT   (graph node)
    │   └── <model name>           LLM
    ├── tools                      AGENT   (graph node)
    │   └── lookup_customer        TOOL    status OK | ERROR, duration
    └── model                      AGENT
        └── <model name>           LLM
```

Relay derives trace and span IDs deterministically from its lifecycle UUIDs,
so parentage is preserved across the export. The API response includes the
`trace_id`, and the chat UI links straight to the trace (`tr-<trace_id>` in
MLflow).

**Failure semantics.** The tool raises `ToolException`. With
`handle_tool_error = True`, LangChain turns it into a
`ToolMessage(status="error")`. Relay marks the tool span `ERROR`, and the agent
can still explain the failure to the user. Without that flag, the exception
would abort the whole agent run.

## Authentication and routing

| Concern | How |
|---|---|
| Who may write traces | MLflow runs with `--app-name basic-auth`. The OTLP endpoint `/v1/traces` is protected like the REST API. |
| Least privilege | `mlflow-bootstrap` creates a non-admin service account `relay-agent` (`default_permission = NO_PERMISSIONS`) and grants it `EDIT` only on the two demo experiments. |
| Which experiment | MLflow routes OTLP traces by the `x-mlflow-experiment-id` header. At startup the agent resolves the experiment *name* to its *id*. |
| Secrets handling | The Relay endpoint uses `header_env`. Relay reads `Authorization` and the experiment id from environment variables when it activates, so secrets never appear in the policy file. |
| Transport | Relay requires HTTPS for non-loopback OTLP endpoints. The compose network is private, so the policy allow-lists only the `mlflow` host via `insecure_http_hosts`. **In production, use TLS** (e.g. an OpenShift route) and remove that line. |

`make verify` proves the routing works: an unauthenticated OTLP post gets
**401**, and the service account posting to a non-granted experiment gets
**403**.

## Two agents, one image

`agent-redacted` and `agent-baseline` are the same container image. They
differ only in `RELAY_PLUGINS_FILE` (policy with or without `pii_redaction`)
and `MLFLOW_EXPERIMENT_NAME`. That makes the before/after comparison fair:
the only variable is the Relay policy.

## Why these choices

- **`create_agent` + `NemoRelayMiddleware` + `configure_graph`.** The middleware
  routes LLM and tool calls through Relay's managed pipeline, which is where
  sanitization happens. `configure_graph` adds graph and node scopes, so tool
  spans keep their place in the run.
- **OpenInference projection.** MLflow already understands it, so you get span
  types, inputs/outputs, and token counts with no custom mapping.
- **An ATOF file sink as well.** It is a local, inspectable copy of the
  canonical sanitized stream (`make atof`), and the verifier scans it too.
- **A scripted model.** It gives deterministic rehearsals, CI, and offline
  demos. It plays the LLM role and still emits real Relay LLM spans.
