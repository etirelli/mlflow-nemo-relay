# Product-gap validation and findings (OpenShell permutation)

The Relay and MLflow findings below carry over unchanged from
`uc1-community`: same agent, same Relay policies, same MLflow. The new section
at the end covers OpenShell.

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

## OpenShell integration status

**Status: ✅ validated end to end on 2026-11-23.** Setup: OpenShell 0.1.9 with
the Homebrew gateway and the Podman driver (rootless Podman 5, Apple M2, VM
kernel 6.9.11 with Landlock), native Ollama with `qwen2.5:0.5b`. Result:
`make demo` passed 16/16.

| Item | Status | Notes |
|---|---|---|
| Blocked egress becomes an ERROR tool span with a readable, redacted reason | ✅ live | `EgressBlocked: could not connect to partner-crm.example.com (ConnectError …). The record for SSN [REDACTED-SSN] was not sent.` |
| Sandbox name exported in telemetry | ✅ live | `demo.sandbox` on the root span |
| Image meets the BYOC requirements | ✅ live | Runs as uid 1500. The interpreter is `/usr/local/bin/python3.12`, matching the policy. |
| Policy validates | ✅ | `openshell-prover check --boundary policy.yaml policy.yaml` (see the findings below) |
| MLflow reachable at `host.openshell.internal:5000` | ✅ live | Podman maps it to `192.168.127.254` (gvproxy), which reaches the Mac's published port |
| Only the allowed MLflow paths are used | ✅ live | The log shows only `GET …/experiments/get-by-name` and `POST /v1/traces`, both `ALLOWED … engine:l7` |
| Relay's OTLP exporter goes through the supervisor | ✅ live | Traces arrive, and each export is logged as an allowed L7 request |
| `sandbox create --detach -- <cmd>` + `forward start -d` | ✅ live | Needs the Makefile fixes below |
| Denial line format | ✅ live | `NET:OPEN [MED] DENIED /usr/local/bin/python3.12(0) -> partner-crm.example.com:443 [reason:transparent_tcp_policy_denied]` |
| L7 deny on an allowed host | ✅ live | `POST /api/pull` to Ollama → `403 {"error":"policy_denied","policy":"local_llm","rule":"POST /api/pull",…}` |
| Ollama bound to loopback only | ✅ live | `OLLAMA_HOST=0.0.0.0` is **not** needed with the Podman machine |
| NVIDIA provider profile | 🟡 | `provider profile lint` passes. Not run against build.nvidia.com. |
| Docker Desktop / colima | ❓ | Not tried |

### Issues found and fixed during the live run

| Issue | Fix |
|---|---|
| `openshell policy lint` does not exist in 0.1.9. Only provider profiles have `lint`. | `make lint` / `make check` use `openshell-prover check --boundary P P`. It applies the same strict schema (unknown fields are rejected) and exits 2 on an invalid policy. |
| The compose healthcheck never passed under Podman: the exec-form `python -c "import …; …"` was split on spaces, so the bootstrap never ran | `CMD-SHELL` form (`compose.yaml`). `uc1-community` has the same latent bug. |
| `openshell forward start -d` keeps the caller's stdout open, so `make sandboxes \| tail` hangs | Redirect the forward's output to `telemetry/forward-<sandbox>.log` |
| `openshell sandbox delete` is asynchronous and has no `--wait`, so re-creating failed with "already exists" | Poll `sandbox get` until the name is free |
| `make verify` got a 401: the env vars were set as a prefix to `cd agent`, not to `uv run` | Set the env vars after the `cd` |
| `qwen2.5:0.5b` skips the second tool call when asked casually ("…and sync the record to the partner CRM") | The CRM prompt names the tool: "…Then call notify_partner_crm with the customer_id and ssn from the result…" It worked 3/3 in testing. |

### Findings and design notes

- **`inference.local` is gone.** OpenShell 0.1.x removed managed inference
  routing (`openshell inference`, `inference.local`). The agent calls the
  native endpoint, and credentials come from **provider profiles** with
  endpoint-bound placeholder substitution. Older OpenShell write-ups are out
  of date on this.
- **`--from <Dockerfile>` no longer builds.** You build the image with the
  gateway's engine and pass the image reference.
- **The image `CMD` does not run.** The supervisor replaces it, so the start
  command goes after `--`.
- **L7 least privilege on the trace store works well with MLflow.** The
  policy allows the agent only `POST /v1/traces` and experiment lookup. Even
  with valid MLflow credentials, a compromised agent cannot read other
  traces, artifacts, or models. This complements MLflow's per-experiment
  permissions.
- **OpenShell does not replace Relay redaction.** MLflow is an *allowed*
  destination, so the baseline sandbox still leaks the SSN into traces. The
  layers are complementary: OpenShell controls where data goes, and Relay
  controls what the telemetry contains. This makes a clear joint message.
- **MLflow credential inside the sandbox.** The demo passes the MLflow
  service-account password with `--env`, which OpenShell treats as
  non-secret. There are two better options, both to validate:
  1. **OpenShell agent trace relay** (`[openshell.gateway.otlp.agent]`, since
     v0.1.7). The gateway holds the MLflow endpoint and headers, and the
     sandbox exports to `192.0.0.8:4318` without credentials or an egress rule.
     The limitation is that headers are per gateway, so per-sandbox experiment
     routing (`x-mlflow-experiment-id`) needs a gateway feature or a collector
     in between. *Suggestion:* per-sandbox (or per-provider) OTLP header
     overrides.
  2. **A provider profile for MLflow** with `auth_style: basic`. This needs
     placeholder substitution to work inside a Basic header that Relay
     base64-encodes in-process, which probably does not work today. A bearer
     token (for example an OpenShift service-account token on RHOAI) avoids
     this.
- **The denial reaches MLflow only as a tool error.** OpenShell can export its
  own policy decisions (`openshell.policy.evaluate` spans and OCSF events) over
  OTLP, but those land in a separate trace, not inside the agent's trace.
  *Suggestion for UC2:* correlate the supervisor's decision with the agent
  span, for example by propagating `traceparent` through the egress proxy, or
  by attaching the denial `reason` to the client-visible error.
- **A disallowed host is refused at TCP level, without an HTTP body.** OpenShell
  0.1.9 intercepts transparently. The client gets `ConnectError`/`EACCES`, not
  the documented `403 policy_denied` JSON, which appears only for L7 denials on
  allowed hosts. The agent therefore cannot tell a policy denial from a network
  failure. Only the sandbox log can, which is why `verify.py` checks it.
  *Suggestion for UC2:* surface a machine-readable denial to the workload, for
  example a TCP-level signal or a resolvable error endpoint, so agents and
  MLflow can classify "blocked by policy" separately from "tool failure". The
  UC2 proposal asks for exactly this distinction.
- **`openshell logs` keeps a short buffer.** We saw "log buffer contains only
  the last 36–60 lines". `make evidence` runs right after the scenarios. On a
  busy sandbox the denial line could scroll out before it is collected.
  Exporting OCSF events over OTLP (`[openshell.gateway.otlp.ocsf]`) would be
  the robust option.
- **OpenShell warns about `--env` credentials.** `sandbox create` prints
  "MLFLOW_TRACKING_PASSWORD looks like a credential passed as a plain
  environment variable… use a provider". This confirms the credential note
  below.
- **The gateway logs a recurring warning on Podman.** `Compute driver watch
  stream failed to start … timeout after 60s` repeats about every minute. It
  had no visible effect: the sandboxes reached `Ready`, and status and logs
  worked.

### Next steps

- [x] Live run on OpenShell 0.1.9 + Podman (2026-11-23): 16/16.
- [ ] Validate Docker Desktop and colima as runtimes.
- [ ] Run the NVIDIA provider against build.nvidia.com, and confirm placeholder substitution for the Python OpenAI client.
- [ ] Report upstream: no `policy lint` CLI, asynchronous `sandbox delete` without `--wait`, `forward start -d` holding stdout, transparent denials without a client-visible reason.
- [ ] Try the agent trace relay for the redacted agent only, to compare credential handling.
- [ ] RHOAI permutation (`uc1-rhoai-openshell`?): OpenShell on OpenShift 4.19+ (Helm chart), MLflow in OpenShift AI over TLS, bearer-token auth.
