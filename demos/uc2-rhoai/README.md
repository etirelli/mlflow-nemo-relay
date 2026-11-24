# UC2 (OpenShift AI): Use guardrail decisions to improve agent behavior

[`uc2-community`](../uc2-community) running on **Red Hat OpenShift AI**:

- A support agent can issue refunds. **NVIDIA NeMo Relay** blocks refunds
  above $500 *before* they execute and records every decision.
- **MLflow in OpenShift AI** shows the decisions in the project's workspace,
  stores the regression dataset, and evaluates agent **v1** against an
  improved **v2** with the policy unchanged.
- The evaluation runs as an **in-cluster Job** with its own service account
  and an **LLM judge**.

| Component | Version (validated) | Role |
|---|---|---|
| Red Hat OpenShift AI | 3.6.0-ea.2 on OpenShift 4.22 (ROSA HCP) | MLflow with workspaces and Kubernetes RBAC; in-cluster builds and Jobs |
| MLflow (OpenShift AI build) | 3.15.2 server, 3.17.2 client | Traces with `GUARDRAIL` spans; GenAI evaluation; evaluation dataset |
| [NeMo Relay](https://github.com/NVIDIA/NeMo-Relay) | 0.11.0 | `refund-limit-v1` tool guardrail, decision telemetry, PII redaction, OTLP over TLS |
| LangGraph / LangChain | 1.2 / 1.5 | The agent, v1 and v2 |
| Any OpenAI-compatible LLM | — | Agents and judge, configured locally. Validated with GLM 5.3. |

**Status:** ✅ validated end to end on 2026-11-23. The in-cluster
evaluation meets the UC2 success criteria (prohibited attempts 40% → 0%, task
completion 90% → 100%, no blocked action executed). See
[docs/verification.md](docs/verification.md).

## What the demo shows

1. **v1 hits the guardrail.** Asked for a $900 refund, v1 calls
   `issue_refund`. Relay's `refund-limit-v1` rejects it before the tool runs:
   nothing is refunded, and the agent explains the block.
2. **The decision is in MLflow, in the project's workspace.** A `GUARDRAIL`
   span carries `rejected: true` and the reason, and the attempted call is
   preserved. There is no executed tool span, which distinguishes a block
   from a tool failure (a timeout).
3. **v2 is fixed in the agent, not the policy.** The prompt and tool
   definitions explain the limit, and a new `request_supervisor_approval`
   tool gives a legitimate path.
4. **The evaluation runs on the platform.** `make eval` starts a Job:
   - 10 regression cases, stored as an MLflow dataset;
   - 4 code scorers plus an LLM judge;
   - one MLflow run per version.
   The judge's key comes from the Secret, and the Job authenticates to MLflow
   as its own service account.
5. **Least privilege.** The agents can write traces to their experiment only.
   The evaluator writes evaluation runs and datasets. Neither can create
   experiments; `make bootstrap` does that as you.

## Quick start

Prerequisites:
- OpenShift AI with MLflow enabled; admin on one project;
- `oc` logged in, and uv;
- an OpenAI-compatible LLM with tool calling.

```bash
cd demos/uc2-rhoai
cp config.env.example config.env        # NAMESPACE, LLM_BASE_URL, LLM_MODEL, LLM_API_KEY_SECRET
oc new-project uc2-rhoai
read -rs "K?LLM API key: "; echo; oc create secret generic llm-credentials -n uc2-rhoai --from-literal=api-key="$K"; unset K

make up              # check, experiments, template, in-cluster build, rollout
make port-forward    # chat UI on http://localhost:8000 (v1/v2 toggle)
make demo            # scenarios + in-cluster evaluation Job + verification
```

To see the results, open MLflow from the OpenShift AI dashboard and choose
workspace **`uc2-rhoai`**. `make up` also prints the direct link.

Stop with `make down`. It keeps the project, the Secret and the experiments.

## Configuration

As in `uc1-rhoai`, nothing cluster-specific is in the code. `config.env`
(gitignored) holds the endpoint, the model, the Secret name, and the policy
(`POLICY_VERSION`, `REFUND_LIMIT`). The values are passed to the OpenShift
Templates. See [docs/configuration.md](docs/configuration.md).

## Documentation

| Doc | For |
|---|---|
| [docs/demo-script.md](docs/demo-script.md) | Presenters: a 6-minute talk track |
| [docs/architecture.md](docs/architecture.md) | Guardrail mechanics, decision telemetry, identities and RBAC on OpenShift AI |
| [docs/evaluation.md](docs/evaluation.md) | The evaluation Job, dataset, scorers and LLM judge |
| [docs/configuration.md](docs/configuration.md) | `config.env`, the templates, the evaluator Job |
| [docs/verification.md](docs/verification.md) | `make verify` and the offline tests |
| [Product gaps report](../../docs/product-gaps.md) | The UC2 product gaps on OpenShift AI, and findings (consolidated, repo root) |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems |

## Layout

```
uc2-rhoai/
├── config.env.example        # copy to config.env (gitignored)
├── Makefile                  # check / bootstrap / deploy / build / rollout / up / port-forward / scenarios / eval / verify / down
├── openshift/
│   ├── template.yaml         # SAs uc2-agent + uc2-evaluator, Roles, service CA, BuildConfig, Deployments v1/v2, Services
│   └── eval-job.yaml         # evaluation Job (one per `make eval`)
├── relay/plugins.toml        # OTLP over TLS + header_file auth + workspace + pii_redaction
├── agent/src/support_agent/  # uc2-community agent + OpenShift AI auth/TLS/workspace wiring
└── tests/                    # offline: guardrail, decisions, v2, concurrency, token rotation, TLS
```
