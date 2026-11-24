# Product gaps and findings: consolidated report

This report collects what the demos validated against the proposal's product
gaps, and every product finding made while building and running them. The
demos under [`demos/`](../demos) are illustrations. This page is the analysis.

**Period:** November 2 to 24, 2026.

**Validated versions:**

| Component | Version |
|---|---|
| NVIDIA NeMo Relay | 0.11.0 (PyPI) |
| MLflow | 3.17.2 client, upstream server |
| MLflow in OpenShift AI | 3.15.2 server (`mlflow-kubernetes-plugins`) |
| Red Hat OpenShift AI | 3.6.0-ea.2, on OpenShift 4.22.22 (ROSA HCP, 2 × m5.2xlarge) |
| OpenShift AI Observability | Technology Preview. Cluster Observability Operator 1.5.5, Red Hat build of OpenTelemetry 0.158.0, Tempo Operator 0.22.0 |
| NVIDIA OpenShell | 0.1.9 (Homebrew gateway, rootless Podman 5, Apple M2) |
| LangGraph / LangChain | 1.2 / 1.4 |
| Prometheus | 3.5.0 |
| LLM | GLM 5.3 (agents and judge). Early UC1 runs used local Ollama models. |

**Finding IDs:** each ID names the product and a number, for example
`REL-3` or `OBS-2`. The demos link to these IDs. **Seen in** lists the demos
where a finding came up.

---

## Part 1: The proposal's product gaps

### UC1: Observe tool calls without exposing sensitive inputs

| Gap | Status | Evidence | Seen in |
|---|---|---|---|
| **1. SSN field redaction**, including inputs echoed in results and error details | ✅ | See the surface table below. No SSN in any exported trace or ATOF file; a baseline control without redaction leaks it. | uc1-community, uc1-openshell, uc1-rhoai |
| **2. Span parentage and status preserved through OTLP export** | ✅ (see REL-6) | The tree `request → agent → model/tools → LLM/TOOL` arrives intact. A timed-out tool arrives as `ERROR` with the right duration (about 2,000 ms vs about 200 ms). With the `openinference` projection, MLflow maps span kinds natively. | uc1-community, uc1-rhoai |
| **3. Authenticated routing to the right project and experiment** | ✅ upstream and on OpenShift AI | Upstream: basic auth plus per-experiment permissions (401 / 403). OpenShift AI: service-account bearer token, `X-MLFLOW-WORKSPACE`, a `resourceNames`-scoped Role (403 on a non-granted experiment), TLS with the service CA, rotating tokens through `header_file`. | uc1-community, uc1-rhoai |

Redaction coverage (gap 1):

| Surface | Redacted? | How |
|---|---|---|
| Tool arguments (`{"ssn": …}`) | ✅ | A field profile (`/ssn` JSON pointer) plus a regex profile |
| `ssn` echoed in the tool result | ✅ | Field profile (results are sanitized as JSON documents) |
| SSN echoed in the tool **error message** | ✅ | Regex profile on the tool output |
| User message, LLM prompts and responses | ✅ | Regex profile on the managed LLM input/output |
| Agent request and response (root span, MLflow previews) | ✅ | Regex profile on scope input/output |
| Relay's local ATOF event file | ✅ | The same sanitized stream |
| What the tool, LLM and user actually receive | Unchanged, by design | Sanitize guardrails, not intercepts (see REL-12) |

### UC2: Use guardrail decisions to improve agent behavior

| Gap | Status | Evidence | Seen in |
|---|---|---|---|
| Enforcement in the LangGraph integration | ✅ with an adapter | `register_tool_conditional_execution` blocks the call before it runs, through `NemoRelayMiddleware`. A rejection is raised as an exception, so a small adapter is needed (REL-1). | uc2-* |
| Guardrail event export to MLflow | ✅ | `GUARDRAIL` spans with `allowed`, `rejected` and `rejection_reason` | uc2-* |
| Keep the attempted action, decision, reason and policy version | ✅ / 🟡 | Decision, reason and target tool are on the guardrail span. The requested **arguments** are only on the parent span (REL-2). The policy version is by naming convention only (REL-3). | uc2-* |
| Tell a policy rejection from a tool failure | ✅ | Rejection: `GUARDRAIL` `rejected=true`, no `TOOL` span. Failure: `TOOL` span with status `ERROR`. With OpenShell, a third, distinct shape: `GUARDRAIL` allowed, then a `TOOL` `ERROR` naming the sandbox policy and rule. | uc2-* |
| Verify that blocked tools didn't execute | ✅ | No `TOOL` span for the call, plus an independent ledger (in-process, or a payments service outside the sandbox) | uc2-* |
| Success criteria: fewer prohibited attempts, legitimate tasks kept, guardrails on | ✅ | v1 → v2, prohibited attempts: 20% → 0% (community), 40% → 0% (OpenShift AI), 42% → 0% and 33% → 0% (OpenShell, two runs). Task completion kept or improved. Nothing blocked ever executed. | uc2-* |

### UC3: Validate guardrail changes before rollout

| Requirement | Status | Evidence | Seen in |
|---|---|---|---|
| The same agent; the policy changes | ✅ | One image, one agent; one service or Deployment per policy version | uc3-* |
| Labeled allowed and prohibited set | ✅ | 14 cases labeled by the business rule, stored as an MLflow evaluation dataset | uc3-* |
| Compare correct blocks, false blocks, prohibited actions allowed, task completion in MLflow | ✅ | One MLflow run per policy with the four rates (computed by the runner, see MLF-5), per-row scorers and a judge | uc3-* |
| Latency and resource context under equivalent load | ✅ community / ✅ with caveats on OpenShift AI | Community: Prometheus. OpenShift AI: latency from OpenShift AI Observability, CPU and memory from cluster monitoring (OBS-2, OBS-3). | uc3-community, uc3-rhoai |
| Rollout decision (beyond the proposal) | ✅ | A gate tags each candidate PROMOTE or REJECT. The per-request budget was promoted; an over-strict limit was rejected (35–38% false blocks, and it still leaked "$300 + $300"). | uc3-* |

---

## Part 2: Findings by product

### NeMo Relay

| ID | Finding | Impact | Suggestion | Seen in |
|---|---|---|---|---|
| REL-1 | **A guardrail rejection aborts the LangGraph run.** Relay raises `RuntimeError("guardrail rejected: …")` from the managed tool call. `handle_tool_error` doesn't catch it, because it isn't a `ToolException`. | Without an adapter, the user gets an HTTP 502 and the agent can't react to the decision. That's the opposite of UC2's goal. | The LangChain middleware could return `ToolMessage(status="error")` with a stable marker, or raise a `ToolException` subclass (`GuardrailRejected`) with structured fields. The demos' `PolicyDecisionMiddleware` is about 30 lines. | uc2-*, uc3-* |
| REL-2 | **The guardrail span doesn't carry the tool arguments.** Its input is `{kind, target_name}` only; the arguments are on the parent `tools` span. | Investigating a block takes two spans. Exporters that drop the parent lose the attempted action. | Include the sanitized arguments in the guardrail scope's start data. | uc2-*, uc3-* |
| REL-3 | **No first-class policy version.** Conditional-execution guardrails are code callbacks with a name. There's no config-file component and no version field. | Versioning relies on naming conventions (`refund-policy-v2`). UC3 depends on it for every comparison, and nothing stops two different rules from sharing a name. | A declarative guardrail component (TOML) with `policy_id` and `version` attributes on every decision. | uc2-*, uc3-* |
| REL-4 | **Guardrail callbacks get no request or session context.** Callbacks receive `(tool_name, args)` only. A per-request budget works only because Relay calls the Python callback in the caller's `contextvars` context, which is undocumented. | Stateful policies (budgets, rate limits, per-customer rules) rely on an implementation detail. | Pass a context object (scope stack, request scope id, metadata), or offer stateful guardrails with a per-scope store. | uc3-* |
| REL-5 | **No shadow or dry-run mode.** A candidate policy can't evaluate alongside production on the same traffic and record "would have blocked". | Policy comparisons need one deployment per policy and replayed traffic. | A `mode = "shadow"` that records `would_reject` without enforcing, so MLflow can compare policies on the same traces. | uc3-* |
| REL-6 | **ERROR spans have an empty `status.description` and no exception event.** The sanitized error text is only in the span outputs. | MLflow shows it, but tools that rely on status descriptions or exception events don't. | Populate the status description and an exception event from the sanitized error. | uc1-* |
| REL-7 | **Guardrail span status is UNSET on rejection.** The decision is only in attributes. | UIs that colour by status show nothing special for a block. | Emit an explicit status or a `guardrail.rejected` span event. | uc2-* |
| REL-8 | **Per-tool guardrails don't follow the money.** A policy keyed on `issue_refund` doesn't see a second tool that moves money (`apply_account_credit`); that call passes with `allowed=true`. | Adding a tool silently widens what the agent can do, and models do use it as a workaround (GLM 5.3 did, in the scenarios and in 2 of 12 evaluation cases). | Policy targets by tool category or tag, and a default-deny mode for tools no policy has reviewed. | uc2-openshell |
| REL-9 | **`header_file` has no prefix or template.** It sends the file content verbatim, but Kubernetes token files hold the raw token, without `Bearer `. | Pods can't point Relay at the service-account token directly. The demos run a refresher thread that writes `Bearer <token>`. | A value template (`header_file_prefix = "Bearer "`) or `auth = {type = "bearer", token_file = …}`. | uc1-rhoai, uc2-rhoai, uc3-rhoai |
| REL-10 | **No built-in SSN (or national ID) detector.** Relay ships `email`, `phone`, `credit_card`, `api_key`, `jwt` and others. | Every user writes a regex, and permissive ones bite: `\d{3}-?\d{2}-?\d{4}` matches nanosecond fractions in RFC 3339 timestamps (seen on Linux, not macOS). | Add an `ssn` / national-ID detector with masking defaults. The demos require separators in free text and rely on the field profile for structured values. | uc1-* |
| REL-11 | **`target_paths` can't be recursive (`**`).** | Deeply nested sensitive fields need every path listed, or `target_path_globs` per level. | Support recursive paths. | uc1-community |
| REL-12 | **Redaction is telemetry-only.** A hosted LLM still receives the SSN in the prompt. | Customers who must keep identifiers from the model need an execution-time control. | Position Relay intercepts or a pre-LLM sanitizer for that case. | uc1-* |
| REL-13 | **Credentials in `header_env` are read once at activation.** | Rotating tokens need `header_file`, which is re-read on every request. | Document it alongside REL-9. | uc1-* |
| REL-14 | **Docs and releases are out of step.** GitHub `main` documents an unreleased `1.0.0` API; PyPI's latest is `0.11.0`. | Easy to build against the wrong API. The demos pin `0.11.0` and use the tag's docs. | Version the docs. | all |
| REL-15 | **Positive: secure defaults and event-level redaction.** Relay refuses plain HTTP to non-loopback hosts unless allow-listed (`insecure_http_hosts`). Without redaction, one trace contains the SSN about 90 times across many attributes, and redacting once at the event level, before projection, covers them all. | — | Keep both. They make a good joint message. | uc1-* |

### MLflow (upstream)

| ID | Finding | Impact | Suggestion | Seen in |
|---|---|---|---|---|
| MLF-1 | **The judge's `base_url` is the full chat-completions URL.** | `https://host/v1` silently posts to the wrong path (EnMaaS returned an HTML 503). | Accept a base URL, or document it. The demos append `/chat/completions`. | uc2-*, uc3-* |
| MLF-2 | **Text judge verdicts aren't aggregated.** `feedback_value_type=Literal["yes","no"]` gives per-row values but no run metric. | Comparison tables show "n/a" for the judge. | Aggregate categorical values. The demos use `bool`. | uc2-* |
| MLF-3 | **`mlflow-skinny` can't run judges.** `make_judge` imports `pandas` indirectly. | Evaluation needs a heavier install than tracing. | Lazy-import pandas in the judge path. | uc2-*, uc3-* |
| MLF-4 | **OTLP routes by experiment id, not name** (`x-mlflow-experiment-id`). | Agents must resolve the id at startup with an MLflow client. | Accept an experiment-name header, or document a standard "resolve at deploy time" step. | all |
| MLF-5 | **No metrics per slice.** Correct and false blocks are rates over *subsets* of rows (prohibited vs allowed). Scorers can't be restricted to a slice, so a scorer's mean mixes both. | The UC3 runner computes the four rates itself and logs them as run metrics. | Aggregate scorer results grouped by an expectation field, or let a scorer return "not applicable". | uc3-* |
| MLF-6 | **No first-class place for a deployment decision.** The gate result is a run tag (`rollout_decision`). | It works, but isn't visible in the evaluation comparison view. | Show run tags there, or support baseline-vs-candidate assertions. | uc3-* |
| MLF-7 | **Evaluation logs inputs outside Relay's redaction.** | Sensitive data in evaluation datasets lands in MLflow unredacted. | Keep evaluation data synthetic or sanitized. The demos use customer ids, never SSNs. | uc2-*, uc3-* |
| MLF-8 | **MLflow 3.17 is OOM-killed on a 2 GiB VM** with its default workers and job executor. | Laptop demos fail. | The demos run 1 worker and `MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false`. Worth documenting a small-footprint mode. | community, openshell |
| MLF-9 | **Per-experiment permission REST paths changed in MLflow 3.x.** | Hand-written bootstrap scripts break. | The demos use `get_app_client("basic-auth")` to stay version-safe. | community, openshell |
| MLF-10 | **The client prints the in-cluster tracking URI in result links.** | "View the evaluation results at https://mlflow.redhat-ods-applications.svc…" isn't clickable. | A public-URL setting for printed links. | uc2-rhoai, uc3-rhoai |

### MLflow in OpenShift AI

| ID | Finding | Impact | Suggestion | Seen in |
|---|---|---|---|---|
| RMF-1 | **Artifact authorization ignores workspace-prefixed paths.** Trace artifacts go to `/mlflow-artifacts/artifacts/workspaces/<ns>/<experiment_id>/…`, but the auth plugin's parser matches `^(\d+)/` only. The access review has no resource name, so **any `resourceNames`-scoped grant gets 403**. | Least-privilege service accounts can't run `mlflow.genai.evaluate` cleanly. The evaluator Roles are widened to project-wide experiments `get`/`update`. | `mlflow-kubernetes-plugins`: strip the `workspaces/<ns>/` prefix in `_get_experiment_id_from_artifact_request`. | uc2-rhoai, uc3-rhoai |
| RMF-2 | **The OTLP route isn't under MLflow's `--static-prefix`.** The REST API is at `…:8443/mlflow/api/…` but OTLP at `…:8443/v1/traces`; `…/mlflow/v1/traces` returns 404 in-cluster (the gateway rewrites it, so it works there). | Clients that build `<tracking_uri>/v1/traces` work through the gateway and fail in-cluster. | Serve OTLP under the prefix too, and document the in-cluster URL. | *-rhoai |
| RMF-3 | **Experiments must be created by a privileged user** when the agent's Role uses `resourceNames` (Kubernetes can't restrict `create` by name). | One admin step (`make bootstrap`). | The right default. A "trace writer" ClusterRole template would help self-service. | *-rhoai |
| RMF-4 | **The built-in roles are broader than needed.** `mlflow-operator-mlflow-integration` grants datasets, registered models and gateway endpoints; `edit` grants more. | An agent bound to them could change models or gateway configuration. | Document a minimal trace-writer Role (experiments `get`/`update`, optionally `resourceNames`). | *-rhoai |
| RMF-5 | **Unauthenticated gateway requests get a 302 to the login page, not a 401.** | Machine clients see a redirect instead of an auth error. | Answer 401 for API and OTLP paths without a browser `Accept` header. | *-rhoai |
| RMF-6 | **Workspaces apply only to regular namespaces.** `X-MLFLOW-WORKSPACE: redhat-ods-applications` returns 404. | — | Document which namespaces are workspaces. | uc1-rhoai |
| RMF-7 | **UI deep links need `?workspace=<ns>` before the `#` route.** | Generated links are easy to get wrong. | Document it. | *-rhoai |
| RMF-8 | **Evaluation datasets need `datasets` `get`, `list`, `create`, `update`.** | — | Document the permissions the evaluation APIs need. | uc2-rhoai, uc3-rhoai |
| RMF-9 | **Positive: evaluation works well as a platform Job.** The SA token, workspace header, service CA and a Secret-sourced judge key worked unchanged. | No credentials on laptops; results land in the project's workspace. | Offer it as a pattern or template, as pipelines do. | uc2-rhoai, uc3-rhoai |
| RMF-10 | **Reasoning text isn't captured.** `reasoning_content` is dropped by LangChain's `ChatOpenAI`; traces only count reasoning tokens. | No extra leak surface today. | If reasoning is captured later, the regex profile already covers string leaves. | uc1-rhoai |

### OpenShift AI Observability (RHOAI 3.6.0-ea.2, Technology Preview)

These issues are known to the product team and are being worked on.

| ID | Severity | Finding | Evidence | Suggestion | Seen in |
|---|---|---|---|---|---|
| OBS-1 | **Security** | **`data-science-thanos-querier-route` is unauthenticated and public.** Edge TLS goes straight to the Thanos querier, with no kube-rbac-proxy. Anyone on the internet can query every metric in the stack, including all tenants' forwarded workload metrics. | Unauthenticated `GET /api/v1/query` → 200 with data; the sibling `data-science-prometheus-route` → 401. | Put kube-rbac-proxy in front, or don't expose a route by default. Workaround: `haproxy.router.openshift.io/ip_whitelist` (the operator didn't revert it in our test). | uc3-rhoai |
| OBS-2 | High (multi-tenancy) | **User-workload series are relabeled to `namespace="redhat-ods-monitoring"`.** The last scrape (Prometheus scraping the collector's re-export) doesn't honor labels, so the project moves to `exported_namespace` / `k8s_namespace_name`. The namespace proxy returns **nothing** for `?namespace=<project>`. | `uc3_*` series carry `namespace=redhat-ods-monitoring`, `exported_namespace=uc3-rhoai`; a tenant query returns `[]`. | `honorLabels: true` on the collector's ServiceMonitor, or relabel `k8s_namespace_name` → `namespace`. Until then, the only path is read access in `redhat-ods-monitoring`, which exposes **every** tenant's forwarded metrics. | uc3-rhoai |
| OBS-3 | Medium | **No container CPU or memory in the stack.** The collector has no kubeletstats or cAdvisor receiver, so resources come from cluster monitoring (the RHOAI "Cluster Prometheus" Perses datasource uses it too). | Collector config and RBAC. | Document the split, or add a kubeletstats receiver scoped to data science projects. | uc3-rhoai |
| OBS-4 | Medium | **Any pod can push OTLP to the collector, unauthenticated.** The RHOAI NetworkPolicy allows 4317/4318 only from `redhat-ods-monitoring`, but the OpenTelemetry operator's generated policy allows them from all sources, and NetworkPolicies add up. | Both policies, read on the cluster. | Decide the intended model. If pushing is allowed, authenticate it; if not, the operator's policy must not open the ports. | uc3-rhoai |
| OBS-5 | Low | **The target allocator logs `secrets is forbidden` every few seconds.** Its SA can't list secrets in `redhat-ods-monitoring`. ServiceMonitor discovery still works. | Target allocator logs; `oc auth can-i`. | Grant read on secrets (needed for ServiceMonitor TLS/auth), or turn off that watch. | uc3-rhoai |
| OBS-6 | Info | **The ServiceMonitor path works across namespaces.** The target allocator selects monitors labelled `monitoring.opendatahub.io/scrape: "true"` with an empty namespace selector. The pod-label path hard-codes port 8080 (in the source, not tried). | `prometheusCR` in the OpenTelemetryCollector spec. | Document the ServiceMonitor path as recommended for custom workloads. | uc3-rhoai |
| OBS-7 | Info | **Two 30-second scrape hops** (target → collector → Prometheus). | Queries need to wait about 70 s, with windows of 2 minutes or more. | — | uc3-rhoai |
| OBS-8 | Info | **Resource limits can't be configured in 3.6** (Prometheus 512Mi, collector 256Mi). The 3.4 docs show `metrics.resources`, which the 3.6 CRD lacks. | CRD and chart defaults. | Expose resources again before GA. | uc3-rhoai |
| OBS-9 | Info | **cert-manager is required** before the RHOAI operator. Otherwise `odh-observability` sticks in `ContainerCreating`. | Provisioning. | Document it as a prerequisite. | uc1-rhoai |

### NVIDIA OpenShell

| ID | Finding | Impact | Suggestion | Seen in |
|---|---|---|---|---|
| OSH-1 | **A second request on a kept-alive plain-HTTP connection is dropped.** The L7 engine logs it as `ALLOWED … request_sequence:1`, but it never reaches the upstream. | **Silent telemetry loss** that looks like a Relay or MLflow bug: 6 of 32 traces lost their root spans, and one trace disappeared. | Fix keep-alive handling in the L7 HTTP path. Workaround: Relay sends `Connection: close` through `header_env`; afterwards 34/34 traces arrived complete. | uc2-openshell |
| OSH-2 | **Disallowed hosts are refused at TCP level, with no reason.** The client gets `ConnectError`/`EACCES`, not the documented `403 policy_denied` JSON, which appears only for L7 denials on allowed hosts. | Agents can't tell a policy denial from a network failure; only the sandbox log can. | A machine-readable denial for all refusals. Pattern that works today: put every backend under an L7 rule, even a one-path allow, to get a readable `403 {"error":"policy_denied","policy","rule",…}`. | uc1-openshell, uc2-openshell |
| OSH-3 | **Denials reach MLflow only as a tool's error text.** The supervisor's decision (an OCSF event) isn't linked to the agent's span. | Fragile: a tool that swallows the body loses the reason. | Propagate `traceparent` through the proxy and stamp it on the OCSF decision, or export OCSF over OTLP with the agent's trace context. | uc1-openshell, uc2-openshell |
| OSH-4 | **`openshell logs` keeps a short buffer** ("log buffer contains only the last N lines"). | Denial lines can scroll out before collection. | Export OCSF events over OTLP for durable evidence. | uc1-openshell, uc2-openshell |
| OSH-5 | **The MLflow password must be passed with `--env`**, which OpenShell treats as non-secret (and warns about). | MLflow basic auth needs a Basic header built in-process, so a provider placeholder can't be substituted inside it. | The agent trace relay with per-sandbox headers, or bearer-token auth to MLflow. | uc1-openshell, uc2-openshell |
| OSH-6 | **Positive: credential injection works with a Python OpenAI client over TLS.** `--credential LLM_API_KEY` stores the key; the sandbox sees a placeholder; the supervisor substitutes the real key. | The LLM key never enters the sandbox. | — | uc2-openshell |
| OSH-7 | **Provider profiles: `rules` and `access` are mutually exclusive** on an endpoint. | Good least privilege, but undocumented. | Document it. | uc2-openshell |
| OSH-8 | **Re-registering a provider profile isn't idempotent.** `profile lint` fails once the id exists; `profile update -f` needs the exported `resource_version`. | Scripts can't just "apply" a profile file. | An apply-style command, or a lint mode that ignores the gateway. | uc2-openshell |
| OSH-9 | **CLI friction:** no `openshell policy lint` (use `openshell-prover check --boundary P P`); `sandbox delete` is asynchronous with no `--wait`; `forward start -d` keeps the caller's stdout open. | Scripts need workarounds (polling, redirects). | Add `policy lint`, `--wait`, and detach stdout. | uc1-openshell, uc2-openshell |
| OSH-10 | **Older write-ups are out of date.** `inference.local` and managed inference routing are gone (use providers); `--from <Dockerfile>` no longer builds; the image `CMD` doesn't run (the command goes after `--`). | Following older guides fails. | Refresh docs and examples. | uc1-openshell |
| OSH-11 | **The gateway logs a recurring warning on Podman** (`Compute driver watch stream failed to start … timeout after 60s`). | No visible effect. | — | uc1-openshell |
| OSH-12 | **Positive: L7 least privilege on the trace store and payments API works well.** Agents can only `POST /v1/traces` and resolve their experiment, or only `POST /v1/refunds`. | A compromised agent can't read other traces or call other APIs, even with valid credentials. | — | uc1-openshell, uc2-openshell |
| OSH-13 | **OpenShell doesn't replace Relay redaction.** MLflow is an allowed destination, so an unredacted agent still leaks the SSN into traces. | The layers complement each other: OpenShell controls where data goes, Relay controls what telemetry contains. | Use as a joint message. | uc1-openshell |

### Policy design and measurement (product-independent)

| ID | Finding | Seen in |
|---|---|---|
| DES-1 | **Per-call limits can't express per-request rules, and tightening doesn't fix that.** "Two refunds of $450" or "$300 and $300" pass a per-call $500 limit. A $300 per-call limit still let "$300 and $300" through while blocking legitimate $350–$500 refunds. Stricter isn't safer. Evaluate the policy against labeled cases. | uc2-*, uc3-* |
| DES-2 | **Two layers cover each other's blind spots.** A tool-level policy understands business meaning but only for the tools it knows. A network policy is tool-agnostic but can't see business meaning. | uc2-openshell |
| DES-3 | **The guardrail itself costs microseconds; behavior changes latency.** A block adds a model turn to explain it, and the LLM dominates end-to-end latency. Compare p95 with a generous budget, and read the guardrail's own cost separately. | uc3-* |
| DES-4 | **Back-office APIs that trust their callers** (the payments service doesn't enforce the limit) show why enforcement in front of them matters. In production the service should also enforce its own limits. | uc2-openshell |
| DES-5 | **Masking vs full redaction** (for example, the last 4 SSN digits) for support workflows is still undecided. | uc1-* |

### Tooling and demo engineering

| ID | Finding | Seen in |
|---|---|---|
| ENG-1 | **Prometheus client: lazily created labeled series lose early increments.** `increase()` can't count the increments before a series' first sample. Create labeled series at startup. | uc3-community |
| ENG-2 | **`oc process` drops `metadata.namespace`.** Objects meant for another namespace land in the current project. Use plain YAML for cross-namespace objects. | uc3-rhoai |
| ENG-3 | **Podman compose splits exec-form healthchecks that contain spaces.** Use `CMD-SHELL`. Rootless Podman also can't resolve `host-gateway`. | community, openshell |
| ENG-4 | **Small models skip a casually worded second tool call** (`qwen2.5:0.5b` in early UC1 runs). Naming the tool in the prompt fixed it. | uc1-openshell |

---

## Open items

- [ ] Repeat the OpenShift AI demos on OpenShift AI 3.5 GA (`stable-3.x`) before customer-facing use. These were validated on the 3.6.0-ea.2 early-access build.
- [ ] `uc2-rhoai-openshell`: OpenShell on OpenShift AI, via the `opendatahub-io/openshell` installer.
- [ ] Re-test OSH-1 on a newer OpenShell build and with Docker; validate Docker Desktop and colima as runtimes.
- [ ] Try the OpenShell agent trace relay (OSH-5) and OCSF export over OTLP (OSH-3, OSH-4).
- [ ] Report upstream: REL-1 to REL-5, REL-9 (NeMo Relay); MLF-1, MLF-3, MLF-5 (MLflow); RMF-1, RMF-2 (MLflow in OpenShift AI); OSH-1 to OSH-3, OSH-7 to OSH-9 (OpenShell). The OBS findings are known to the product team.
