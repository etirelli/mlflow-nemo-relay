# Configuration

## `config.env`: your cluster, your LLM

The demo code and manifests contain no endpoint, model, or credential.
Everything cluster-specific is in `config.env`, which is gitignored and
created from [`config.env.example`](../config.env.example). The Makefile
passes it to the OpenShift Template with
`oc process --param-file=config.env`.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `NAMESPACE` | ✅ | — | Project for the demo, and also the MLflow workspace |
| `LLM_BASE_URL` | ✅ | — | OpenAI-compatible base URL (`…/v1`) |
| `LLM_MODEL` | ✅ | — | Model id from `GET $LLM_BASE_URL/models` |
| `LLM_API_KEY_SECRET` | ✅ | — | Name of a Secret in `NAMESPACE` that holds the key |
| `LLM_API_KEY_SECRET_KEY` | | `api-key` | Key inside that Secret |
| `LLM_PROVIDER` | | `openai` | `scripted` runs without any LLM (deterministic rehearsals) |
| `MLFLOW_TRACKING_URI` | | `https://mlflow.redhat-ods-applications.svc:8443/mlflow` | In-cluster MLflow REST base URL |
| `MLFLOW_OTLP_ENDPOINT` | | derived: `https://<host>:8443/v1/traces` | Set it only if your MLflow serves OTLP elsewhere |
| `MLFLOW_PUBLIC_URI` | | derived from route `data-science-gateway` | Browser and laptop MLflow URL |
| `REDACTED_EXPERIMENT` / `BASELINE_EXPERIMENT` / `NOT_GRANTED_EXPERIMENT` | | `uc1-rhoai-redacted` / `-baseline` / `-not-granted` | Experiment names. The Role is generated from the first two. |
| `TOOL_TIMEOUT_SECONDS` | | `2.0` | Lookup timeout. The "legacy shard" customer takes 30 s. |

### Creating the API key Secret

The key goes straight from your terminal into the cluster. It never goes into
a file, the shell history, or the repo:

```bash
read -rs "K?LLM API key: "; echo                       # zsh; in bash: read -rsp "LLM API key: " K
oc create secret generic llm-credentials -n "$NAMESPACE" --from-literal=api-key="$K"; unset K
```

The Deployments read it as `LLM_API_KEY` through `secretKeyRef`.

### LLM requirements

- An OpenAI-compatible `chat/completions` API with **tool calling**.
- The cluster must be able to reach it (egress).
- Reasoning models work. Don't set a small `max_tokens`, because reasoning
  tokens count against it.

Validated: GLM 5.3 (`rits/zai-org/glm-5-3`) on a hosted endpoint answers the
lookup and explains the timeout well, at about 2–4 s per LLM call. Other
options: Models-as-a-Service on the same cluster, vLLM or NIM served by
KServe, or build.nvidia.com.

> **Note:** a hosted LLM receives the (synthetic) SSN in the prompt. That is
> real execution. Relay redacts telemetry, not the request to the model.

## What the template creates

| Object | Purpose |
|---|---|
| `ServiceAccount uc1-agent` | Agent identity in MLflow |
| `Role/RoleBinding uc1-trace-writer` | `get`, `update` on `experiments.mlflow.kubeflow.org`, limited by `resourceNames` to the two experiments |
| `ConfigMap uc1-service-ca` | OpenShift injects the service CA bundle, which is trusted for MLflow TLS |
| `ConfigMap uc1-llm` | `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL` |
| `ImageStream` + `BuildConfig uc1-agent` | Binary Docker build from your checkout (`make build`) |
| `Deployment` + `Service` `uc1-agent-redacted`, `uc1-agent-baseline` | The agents, with the restricted-v2 security context |

## Agent environment (set by the template)

| Variable | Value |
|---|---|
| `MLFLOW_WORKSPACE` | `NAMESPACE` |
| `MLFLOW_TRACKING_TOKEN_FILE` | `/var/run/secrets/kubernetes.io/serviceaccount/token` |
| `MLFLOW_TRACKING_SERVER_CERT_PATH` | `/etc/uc1/service-ca/service-ca.crt` |
| `MLFLOW_EXPERIMENT_NAME`, `RELAY_MODE`, `RELAY_PLUGINS_FILE` | Set per agent |
| `LLM_API_KEY` | From the Secret |

At startup, `relay_runtime.configure_mlflow_routing()` derives the variables
that the Relay TOML uses:
- `MLFLOW_OTLP_TRACES_ENDPOINT`
- `MLFLOW_OTLP_AUTH_HEADER_FILE`, the `Bearer` file
- `MLFLOW_OTLP_WORKSPACE`
- `MLFLOW_OTLP_EXPERIMENT_ID`
- `MLFLOW_OTLP_CA_CERT`

The `[tls]` table in the TOML is rendered only when a CA is configured
(`# begin-optional` block).

## Running another configuration

- **Another LLM:** edit `config.env`, then run `make deploy rollout`.
  Re-applying updates the `uc1-llm` ConfigMap and the restart picks it up.
- **Another project:** set `NAMESPACE`, create the project and the Secret,
  then run `make up`.
- **Several copies in one cluster:** use one project per copy. Each project
  is its own MLflow workspace.
