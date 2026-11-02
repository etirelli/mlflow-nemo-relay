# Product-gap validation and findings

The proposal lists three product gaps for use case 1. This page records what
we validated with **NeMo Relay 0.11.0**, **LangGraph 1.2 / LangChain 1.4**,
and **MLflow 3.17.2** (validated 2026-11-02), plus other findings that matter
for a productized version.

## Gap 1: SSN field redaction, including echoed inputs in results and error details

**Status: ✅ validated**

| Surface | Redacted? | How |
|---|---|---|
| Tool arguments (`{"ssn": …}`) | ✅ | Profile 1 (`/ssn` JSON pointer) and profile 2 |
| `ssn` echoed in the tool result | ✅ | Profile 1 (tool results are sanitized as JSON documents) |
| SSN echoed in the tool **error message** | ✅ | Profile 2 (regex) on `tool_output` |
| User message / LLM prompts / LLM responses | ✅ | Profile 2 on the managed LLM `input`/`output`, through the OpenAI chat codec |
| Agent request/response (root span, MLflow previews) | ✅ | Profile 2 on generic scope input/output |
| Relay's ATOF event file | ✅ | Same sanitized canonical stream |
| What the tool / LLM / user actually receive | Unchanged, by design | Sanitize guardrails, not intercepts |

Findings:
- **No built-in SSN detector.** Relay ships detectors for `email`, `phone`,
  `credit_card`, `api_key`, `jwt`, and others, but not SSN or other national
  IDs. We used a custom regex. *Suggestion:* add an `ssn` (or national-ID)
  detector with sensible masking defaults.
- **Regex pitfall.** A permissive pattern (`\d{3}-?\d{2}-?\d{4}`) matches
  unrelated 9-digit runs, such as nanosecond fractions in RFC 3339 timestamps.
  That over-redacts and causes false positives. Our checker hit this on Linux,
  where timestamps have nanosecond precision, but not on macOS, which records
  microseconds. The demo requires separators in free text and relies on the
  field-level profile for structured values. A built-in detector would avoid
  every user rediscovering this.
- The `target_paths` selector cannot be recursive (`**`). For tools whose
  results nest the SSN deeply, users must list the paths or use
  `target_path_globs` per level.

## Gap 2: Preserve span parentage and status during OTLP export

**Status: ✅ validated**, with one observation

- Relay derives OTel trace and span IDs deterministically from its scope
  UUIDs. The tree `customer-lookup-request → customer_lookup_agent → model/tools →
  LLM/TOOL` arrives intact in MLflow.
- With the `openinference` projection, MLflow maps span kinds to its span types
  (`AGENT`, `LLM`, `TOOL`) and fills inputs/outputs, so no custom mapping is needed.
- A timed-out tool arrives with status **ERROR** and the correct duration
  (about 2,000 ms vs about 200 ms for success).
- **Observation:** the ERROR span's `status.description` is empty, and there is
  no OTel exception event. The (sanitized) error text is available only in the
  span *outputs*. MLflow shows it, but tools that rely on status descriptions
  or exception events will not. *Suggestion:* Relay could populate the status
  description and an exception event from the sanitized error.
- **Integration requirement:** the LangChain tool must set
  `handle_tool_error = True`, or another error handler. Otherwise the exception
  aborts the whole graph run instead of producing an ERROR tool span plus a
  graceful agent reply.

## Gap 3: Authenticated routing to the correct MLflow project and experiment

**Status: ✅ validated on upstream MLflow** (basic auth plus experiment
permissions). RHOAI-specific auth is to be validated in the `uc1-rhoai`
permutation.

- MLflow's `/v1/traces` honors basic auth and per-experiment permissions.
  Unauthenticated requests get 401. The service account gets 403 on a
  non-granted experiment.
- Relay's `header_env` keeps the credential and the experiment id out of the
  config file. Relay snapshots them when it activates.
- **Friction:** MLflow routes OTLP by experiment **id** (`x-mlflow-experiment-id`),
  not by name, so the agent must resolve the id at startup with an MLflow
  client. For a productized version, consider accepting an experiment name
  header, or documenting a standard "resolve at deploy time" step. On RHOAI,
  workspace/project scoping must also be carried in the export, which is to be
  validated.
- **Transport:** Relay refuses plain HTTP to non-loopback hosts unless they
  are allow-listed (`insecure_http_hosts`). That is good secure-by-default
  behavior. The demo allow-lists the in-network `mlflow` host. The RHOAI
  permutation should use TLS routes and Relay's `tls` endpoint settings.
- Credential rotation: `header_env` is read once at activation. For
  rotating tokens (e.g. OpenShift service-account tokens), use `header_file`,
  which is re-read on every request.

## Other findings

| Area | Finding |
|---|---|
| Telemetry surface area | Without redaction, one simple trace contains the SSN **about 90 times**: `input.value`, `tool.parameters`, `tool_call.function.arguments`, `nemo_relay.start.*`, `nemo_relay.end.*`, LLM message attributes, previews, and more. This strongly supports redacting at the event level, before projection, which is what Relay does, rather than per exporter. |
| Versions | The GitHub `main` docs describe an unreleased `1.0.0` API, while PyPI's latest is `0.11.0`. The demo pins `0.11.0` and was built against the `0.11.0` tag's docs. |
| MLflow on small VMs | MLflow 3.17 with its default worker count and background job executor was OOM-killed on a 2 GiB colima/podman VM. The demo runs 1 worker and sets `MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false` (it is used for online scoring and judges, which this demo does not need). |
| MLflow auth API | The per-experiment permission REST paths changed in MLflow 3.x (unified `users/permissions/grant`). The bootstrap uses MLflow's own auth client, `get_app_client("basic-auth")`, to stay version-safe. |
| Hosted LLMs | Redaction applies to telemetry only. A hosted LLM still receives the SSN in the prompt. Customers who need to keep identifiers from the model need an execution-time control, which is in scope for UC2-style Relay intercepts. |

## Open items for the next permutations

- [ ] `uc1-rhoai`: MLflow in OpenShift AI (workspace/project isolation, OpenShift auth), with Relay exporting over TLS.
- [ ] Confirm the supported guardrail integration path for UC2. The NeMo Guardrails plugin is deprecated, so use Relay's conditional-execution guardrails instead.
- [ ] Decide whether masking (last 4 digits) is preferable to full redaction for support workflows.
