# Product-gap validation and findings (OpenShift AI)

Validated on 2026-11-23 with **OpenShift AI 3.6.0-ea.2**, the MLflow 3.15.2
server (OpenShift AI build, `mlflow-kubernetes-plugins`), **NeMo Relay
0.11.0** and **GLM 5.3**, on OpenShift 4.22.22 (ROSA HCP, 2 × m5.2xlarge).

Gaps 1 and 2 (redaction coverage, span parentage and status) behave exactly
as in [uc1-community](../../uc1-community/docs/product-gaps.md). The same
agent and Relay policies passed the same checks. This page focuses on
**gap 3**, which uc1-community left open for OpenShift AI.

## Gap 3: Authenticated routing to the correct MLflow project and experiment

**Status: ✅ validated on OpenShift AI**

| Requirement | How it is met | Evidence |
|---|---|---|
| Authenticate without shared passwords | The pod's **service account token** as a bearer token. MLflow checks it with a SelfSubjectAccessReview. | Traces arrive. No credentials in config. |
| Route to the right project | `X-MLFLOW-WORKSPACE: <namespace>`. MLflow workspaces map 1:1 to namespaces. | Traces appear in workspace `uc1-rhoai` |
| Route to the right experiment | `x-mlflow-experiment-id`, resolved from the name at startup | Redacted and baseline traces land in separate experiments |
| Project and experiment isolation | Role on `experiments.mlflow.kubeflow.org` with **`resourceNames`** | 403 for a non-granted experiment in the same workspace (check 12) |
| Encrypted transport | HTTPS to `mlflow.redhat-ods-applications.svc:8443`, trusting the injected service CA through Relay `tls.certificate` | No `insecure_http_hosts` is needed |
| Rotating credentials | Relay `header_file`, refreshed every 60 s from the projected token | `test_bearer_header_file_follows_token_rotation` |

## Findings

| # | Finding | Impact | Suggestion |
|---|---|---|---|
| 1 | **The OTLP route is not under MLflow's `--static-prefix`.** OpenShift AI serves the REST API at `…:8443/mlflow/api/…` but OTLP at `…:8443/v1/traces`. `…/mlflow/v1/traces` returns 404 ("No Kubernetes authorization rule matched"). Through the gateway, `/mlflow/v1/traces` works because the route rewrites it. | Clients that build the OTLP URL as `<tracking_uri>/v1/traces` work through the gateway but fail in-cluster. We hit this. | MLflow: serve OTLP under the static prefix too (or both). OpenShift AI docs: state the in-cluster OTLP URL explicitly. The demo derives `<scheme>://<host>/v1/traces` and allows an override. |
| 2 | **Relay `header_file` has no prefix or template.** It sends the file content verbatim, but Kubernetes token files hold the raw token, without `Bearer `. | Pods can't point Relay straight at the service account token. A refresher has to write `Bearer <token>`. | Relay: support a value template (for example `header_file_prefix = "Bearer "`) or an `auth = { type = "bearer", token_file = … }` option. |
| 3 | **Experiments must be created by a privileged user.** Restricting the agent with `resourceNames` means it can't `create`, because Kubernetes can't restrict `create` by name. | One extra admin step, `make bootstrap` | This is the right default for least privilege. For self-service, OpenShift AI could offer a "trace writer" ClusterRole template. |
| 4 | **The built-in roles are broader than needed.** `mlflow-operator-mlflow-integration` grants datasets, registered models and gateway endpoints. `edit` grants even more. | An agent bound to them could change models or gateway configuration. | Document a minimal "trace writer" Role (experiments `get`/`update`, optionally with `resourceNames`), as this demo does. |
| 5 | **Unauthenticated gateway requests get a 302 to the OpenShift login, not a 401.** | Machine clients see a redirect instead of an auth error, which is confusing in logs. | The gateway could answer 401 for API or OTLP paths without a browser `Accept` header. |
| 6 | **Workspaces apply only to "regular" namespaces.** `X-MLFLOW-WORKSPACE: redhat-ods-applications` returns 404 "Workspace … not found". | — | Expected. Worth documenting which namespaces count as workspaces. |
| 7 | **Reasoning models:** `reasoning_content` is dropped by LangChain's `ChatOpenAI`. Traces contain only `reasoning_tokens` counts. | No extra leak surface today | If reasoning text is captured later, the regex profile already covers string leaves. |
| 8 | **MLflow UI deep links with workspaces** need `?workspace=<ns>` *before* the `#` route: `…/mlflow/?workspace=uc1-rhoai#/experiments/3/traces`. | Easy to get wrong when generating links | Document it. The demo's chat UI generates it correctly. |

## Platform notes from provisioning

- The guide's minimal install (dashboard and MLflow only) is enough for this
  demo. See the vault note "ROSA HCP Cluster + RHOAI Install", minimal
  variant.
- RHOAI 3.6's platform monitoring (`odh-observability`) needs cert-manager.
  Without it, a pod sticks in `ContainerCreating`. This doesn't affect MLflow.
- The `beta` channel is currently an early-access build (3.6.0-ea.2). Repeat
  on GA 3.5.x (`stable-3.x`) before customer-facing use.

## Open items

- [ ] Repeat on OpenShift AI 3.5 GA.
- [ ] UC2/UC3 on this cluster: guardrail decisions, and OpenShift AI Observability metrics for policy comparison.
- [ ] OpenShell on OpenShift 4.19+ (`uc1-rhoai-openshell`): the sandbox policy would add network-level confinement on top of RBAC.
- [ ] Report findings 1 and 2 upstream (MLflow and NeMo Relay).
