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

**Status: 🟡 built against the OpenShell v0.1.9 docs and examples. The offline
behaviour is validated; the live sandbox run is pending.**

| Item | Status | Notes |
|---|---|---|
| Agent code: blocked egress becomes an ERROR tool span with a readable, redacted reason | ✅ validated offline | `tests/test_sandbox_egress.py` simulates the supervisor's `403 policy_denied` body |
| Sandbox name exported in telemetry | ✅ validated offline | Root span metadata `demo.sandbox`, plus a resource attribute |
| Image meets the BYOC requirements (non-root `USER`, `/sandbox`, standard base) | 🟡 by inspection | Follows `examples/bring-your-own-container` |
| `policy.yaml` passes `openshell policy lint` | ⏳ pending | Needs the CLI (`make lint`) |
| MLflow reachable from the sandbox at `host.openshell.internal:5000` | ⏳ pending | Needs a live gateway. The macOS host-gateway path through Docker Desktop is unverified. |
| The MLflow client and Relay exporter use only the three allowed MLflow paths | ⏳ pending | If startup fails, `make deny-log` shows the missing path |
| Relay's OTLP exporter goes through the supervisor's egress path | ⏳ pending | The exporter runs in the Python process, so the `python3.12` binary rule should match |
| `sandbox create --detach -- <cmd>` followed by `forward start -d` | ⏳ pending | Flags confirmed in the CLI source; the combination is untested |
| `openshell logs` denial line format matches the verifier's match | ⏳ pending | The verifier matches the host plus `deni`/`deny` |
| NVIDIA provider profile: placeholder substitution for the Python client | ⏳ pending | Based on the built-in `nvidia` profile, with the binary changed to Python |
| Colima as the Docker runtime on macOS | ❓ unknown | OpenShell qualifies Docker Desktop on Apple Silicon. Colima and podman machine depend on VM kernel Landlock support (ABI v3+). |

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
- **The same tool fails differently inside and outside the sandbox.** Outside
  the sandbox, the CRM call fails with DNS resolution. Inside, it fails with
  `403 policy_denied`. The tool labels both `EgressBlocked`. Only the sandbox
  log proves the policy refused it, so `verify.py` checks that log.

### Next steps

- [ ] Run `make up-scripted && make demo` against a live OpenShell 0.1.9 gateway (Docker Desktop, Apple Silicon), and record the real `openshell logs` denial line in the docs.
- [ ] Validate colima and podman machine as runtimes. If they work, document the minimum VM kernel.
- [ ] Try the agent trace relay for the redacted agent only, to compare credential handling.
- [ ] RHOAI permutation (`uc1-rhoai-openshell`?): OpenShell on OpenShift 4.19+ (Helm chart), MLflow in OpenShift AI over TLS, bearer-token auth.
