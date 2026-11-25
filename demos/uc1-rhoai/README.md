# UC1 (OpenShift AI): Observe tool calls without exposing sensitive inputs

The UC1 demo running on **Red Hat OpenShift AI**:

- A LangGraph customer-support agent looks up customers by Social Security
  number. It runs as a Deployment in an OpenShift project.
- **NVIDIA NeMo Relay** redacts the SSN from all telemetry before it leaves
  the pod.
- **MLflow in OpenShift AI** stores the traces in the project's MLflow
  workspace. Engineers see tool outcomes, timing and errors, and never the SSN.

| Component | Version (validated) | Role |
|---|---|---|
| Red Hat OpenShift AI | 3.6.0-ea.2 on OpenShift 4.22 (ROSA HCP) | Platform. MLflow operator with workspaces and Kubernetes authorization. |
| MLflow (OpenShift AI build) | 3.15.2 server | Trace store. `kubernetes-auth`, one workspace per namespace, OTLP ingestion |
| [NeMo Relay](https://github.com/NVIDIA/NeMo-Relay) | 0.11.2 | Managed tool and LLM execution, `pii_redaction`, OTLP export over TLS |
| LangGraph / LangChain | 1.2 / 1.5 | The agent |
| Any OpenAI-compatible LLM with tool calling | — | Configured locally. Validated with GLM 5.3 on a hosted endpoint. |

**Status:** ✅ validated end to end on 2026-11-23. `make demo` passes 12/12,
and `make test` passes 9 offline tests.

## What the demo shows

1. **Run a customer lookup.** The chat UI or REST API sends a synthetic SSN.
   One lookup succeeds; one customer lives on a slow "legacy shard", so that
   lookup **times out**.
2. **Sanitize and export.** Relay's `pii_redaction` replaces the SSN with
   `[REDACTED-SSN]` in tool arguments, results, errors, LLM prompts and
   responses, before the OTLP exporter sees them. The tool and the LLM still
   get the real value.
3. **Inspect in MLflow (OpenShift AI).** In the project's workspace, the trace
   shows `customer-lookup-request → agent → tools → lookup_customer` with
   status, duration and a readable, redacted error.
4. **Before/after.** A baseline agent uses the same image without redaction
   and writes to its own experiment. Its traces leak the SSN.
5. **Secure by platform.** The agent authenticates to MLflow with its own
   **service account token**, which rotates automatically. There are no
   passwords. Traffic goes over TLS to the in-cluster service. The agent's
   Role allows writing to **its two experiments only**: it can't create
   experiments or touch others in the same workspace.
6. **Proof.** `make verify` reads everything back from MLflow and checks the
   success criteria, 12 checks in all.

## Quick start

Prerequisites:
- OpenShift with OpenShift AI, and MLflow enabled (`mlflowoperator: Managed`
  plus an `MLflow` CR). You need admin on one project.
- `oc` logged in, and [uv](https://docs.astral.sh/uv/).
- An OpenAI-compatible LLM endpoint with tool calling, and its API key.

```bash
cd demos/uc1-rhoai

# 1. Local, cluster-specific configuration (gitignored)
cp config.env.example config.env        # set NAMESPACE, LLM_BASE_URL, LLM_MODEL, LLM_API_KEY_SECRET

# 2. Project and API key Secret: the key never goes into a file or the repo
oc new-project uc1-rhoai
read -rs "K?LLM API key: "; echo
oc create secret generic llm-credentials -n uc1-rhoai --from-literal=api-key="$K"; unset K

# 3. Deploy and run
make up              # check, create experiments, apply template, build image in-cluster, roll out
make port-forward    # chat UI on http://localhost:8000 (baseline on :8001)
make demo            # scenarios + 12 checks
```

`make up` prints the MLflow link, which looks like
`https://rh-ai.apps.<cluster-domain>/mlflow/?workspace=uc1-rhoai`. You can
also open MLflow from the OpenShift AI dashboard: **Applications → MLflow**,
then choose the `uc1-rhoai` workspace.

Stop with `make down`. It removes the demo resources and keeps the project,
the Secret and the MLflow experiments.

## Configuration: nothing cluster-specific in the code

Everything that differs between clusters is in your local `config.env`. It's
passed as parameters to the OpenShift Template ([`openshift/template.yaml`](openshift/template.yaml)):

| Setting | Example | Notes |
|---|---|---|
| `NAMESPACE` | `uc1-rhoai` | It is also the MLflow workspace. |
| `LLM_BASE_URL` | `https://llm.example.com/v1` | Any OpenAI-compatible endpoint |
| `LLM_MODEL` | `my-model-id` | Must match `GET $LLM_BASE_URL/models` |
| `LLM_API_KEY_SECRET` / `_KEY` | `llm-credentials` / `api-key` | A Secret you create. The key never touches the repo. |
| `MLFLOW_*` | derived | The in-cluster service and gateway URL are found automatically. You can override them. |

See [docs/configuration.md](docs/configuration.md).

## Documentation

| Doc | For |
|---|---|
| [docs/demo-script.md](docs/demo-script.md) | Presenters: a 5-minute talk track |
| [docs/architecture.md](docs/architecture.md) | Data flow, MLflow workspaces and Kubernetes auth, token rotation, TLS |
| [docs/configuration.md](docs/configuration.md) | `config.env`, template parameters, LLM choices |
| [docs/verification.md](docs/verification.md) | The 12 checks and the offline tests |
| [Product gaps report](../../docs/product-gaps.md) | Proposal gap 3 on OpenShift AI, and findings (consolidated, repo root) |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems |

## Layout

```
uc1-rhoai/
├── config.env.example      # copy to config.env (gitignored): endpoint, model, Secret name
├── Makefile                # check / bootstrap / deploy / build / rollout / up / port-forward / demo / verify / down
├── openshift/template.yaml # SA, least-privilege Role, service CA ConfigMap, BuildConfig, 2 Deployments, Services
├── relay/                  # Relay policies: OTLP over TLS + header_file auth (+ pii_redaction)
├── agent/                  # same agent as uc1-community + OpenShift AI auth/workspace/TLS wiring
│   └── src/customer_lookup_agent/
│       ├── relay_runtime.py    # rotating SA token -> Bearer header file, workspace + experiment routing
│       ├── bootstrap_rhoai.py  # `make bootstrap`: creates experiments as the cluster user
│       └── verify.py           # `make verify`
├── tests/                  # offline: redaction, headers, token rotation, OTLP endpoint
└── docs/
```
