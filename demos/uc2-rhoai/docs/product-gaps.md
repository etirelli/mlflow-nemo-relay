# Product-gap validation and findings (UC2 on OpenShift AI)

Validated on 2026-11-23 with **OpenShift AI 3.6.0-ea.2** (MLflow 3.15.2
server, `mlflow-kubernetes-plugins`), the **MLflow 3.17.2** client, **NeMo
Relay 0.11.0**, and **GLM 5.3** as the agent LLM and the judge.

The UC2 product gaps behave exactly as in
[uc2-community](../../uc2-community/docs/product-gaps.md): the same agent,
the same guardrail and the same decision telemetry. Findings 1–9 there
(Relay rejection semantics, guardrail span contents, policy versioning,
judge `base_url`, and so on) apply unchanged. This page adds what is
specific to OpenShift AI.

| UC2 gap | Status on OpenShift AI | Notes |
|---|---|---|
| Enforcement in the LangGraph integration | ✅ | Same `PolicyDecisionMiddleware` adapter |
| Guardrail event export to MLflow | ✅ | `GUARDRAIL` spans arrive in workspace `uc2-rhoai` over TLS, with service account auth |
| Attempted action, decision, reason, policy version | ✅ / 🟡 | As in community: the arguments are on the parent `tools` span; the policy version is by naming convention |
| Policy rejection vs tool failure | ✅ | |
| Blocked tools did not execute | ✅ | Tool spans plus the refund ledger; `blocked_never_executed` = 100% in the Job |
| Evaluate agent versions with the policy fixed | ✅ | In-cluster Job: prohibited attempts 40% → 0%, task completion 90% → 100%, judge 67% → 100% |
| Evaluation dataset retained for regression | ✅ | `uc2-refund-policy-regression` stored in the workspace by the evaluator service account |

## OpenShift AI-specific findings

| # | Finding | Impact | Suggestion |
|---|---|---|---|
| R1 | **Artifact authorization ignores workspace-prefixed paths.** With workspaces enabled, trace artifacts are uploaded to `/mlflow-artifacts/artifacts/workspaces/<ns>/<experiment_id>/traces/…`. The auth plugin's resource-name parser matches `^(\d+)/` only, so it can't resolve the experiment. The access review then has no resource name, and **any `resourceNames`-scoped grant is denied (403)**. | Least-privilege service accounts (scoped to named experiments) can't run `mlflow.genai.evaluate` cleanly: scores are logged, but trace artifacts fail. The demo widens the evaluator to project-wide experiments `get`/`update`. | `mlflow-kubernetes-plugins`: strip the `workspaces/<ns>/` prefix in `_get_experiment_id_from_artifact_request`, which is a small fix. Worth an upstream issue and a test. |
| R2 | **Evaluation works well as a platform Job.** The SA token, the workspace header, the service CA and the Secret-sourced judge key worked without code changes beyond reading the token file. | A clean story: no credentials on laptops, results in the project's workspace. | OpenShift AI could offer this as a pattern or template (an "evaluation job" with a scoped SA), much as pipelines do. |
| R3 | **The MLflow client prints the in-cluster tracking URI in result links.** | "View the evaluation results at https://mlflow.redhat-ods-applications.svc…" isn't clickable for users. | MLflow could support a `MLFLOW_UI_URI` or public-URL setting for printed links. |
| R4 | **Datasets RBAC.** `create_dataset`, `merge_records` and `search_datasets` needed `datasets` `get`, `list`, `create`, `update`. A name-scoped dataset grant wasn't attempted. | — | Document the permissions needed for the evaluation APIs. |
| R5 | **Same as uc1-rhoai.** The OTLP route isn't under `/mlflow`; Relay's `header_file` has no `Bearer` prefix support; experiments must be created by a privileged user. | — | See [uc1-rhoai findings](../../uc1-rhoai/docs/product-gaps.md). |

## Open items

- [ ] File R1 upstream (`mlflow-kubernetes-plugins`, the artifact experiment-id parser with workspaces).
- [ ] Repeat on OpenShift AI 3.5 GA.
- [ ] `uc2-openshell` (Podman) and `uc2-rhoai-openshell` (OpenShell on OpenShift AI, via the `opendatahub-io/openshell` installer).
