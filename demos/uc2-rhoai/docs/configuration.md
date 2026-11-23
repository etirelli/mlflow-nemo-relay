# Configuration

## `config.env`

Everything cluster-specific lives in `config.env`, which is gitignored and
created from [`config.env.example`](../config.env.example). The Makefile
passes it to both OpenShift Templates with `oc process --param-file`.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `NAMESPACE` | ✅ | — | Project, and also the MLflow workspace |
| `LLM_BASE_URL` | ✅ | — | OpenAI-compatible base URL (`…/v1`), used by the agents and the judge |
| `LLM_MODEL` | ✅ | — | Model id from `GET $LLM_BASE_URL/models` |
| `LLM_API_KEY_SECRET` / `_KEY` | ✅ | — / `api-key` | Existing Secret in `NAMESPACE` |
| `POLICY_VERSION` | | `v1` | Relay policy id suffix, `refund-limit-<version>` |
| `REFUND_LIMIT` | | `500` | Refunds above this are blocked |
| `LLM_PROVIDER` | | `openai` | `scripted` means no LLM; the evaluation then skips the judge |
| `TRACE_EXPERIMENT` / `EVAL_EXPERIMENT` / `NOT_GRANTED_EXPERIMENT` | | `uc2-rhoai-refund-agent` / `…-eval` / `uc2-rhoai-not-granted` | The agents' Role is generated from `TRACE_EXPERIMENT` |
| `MLFLOW_TRACKING_URI` / `MLFLOW_OTLP_ENDPOINT` / `MLFLOW_PUBLIC_URI` | | derived | As in `uc1-rhoai` |

Changing the LLM or the policy means editing `config.env`, then running
`make deploy rollout`. The new `uc2-llm` ConfigMap is picked up when the
agents restart.

## `openshift/template.yaml`

| Object | Purpose |
|---|---|
| `ServiceAccount uc2-agent` + `Role/RoleBinding uc2-trace-writer` | Agents: `get`, `update` on `TRACE_EXPERIMENT` only |
| `ServiceAccount uc2-evaluator` + `Role/RoleBinding uc2-evaluator` | Evaluation Job: experiments `get`, `update` (project-wide, see below), plus datasets `get`, `list`, `create`, `update` |
| `ConfigMap uc2-service-ca` | Injected service CA, trusted for MLflow TLS |
| `ConfigMap uc2-llm` | `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `POLICY_VERSION`, `REFUND_LIMIT` |
| `ImageStream` + `BuildConfig uc2-agent` | In-cluster build (`make build`). The image includes the `eval` extra. |
| `Deployment`/`Service uc2-agent-v1`, `uc2-agent-v2` | The agents. `AGENT_VERSION` selects the prompt and tools. |

> **Why the evaluator's experiment grant is project-wide:** MLflow
> evaluation uploads trace artifacts to
> `/mlflow-artifacts/artifacts/workspaces/<ns>/<experiment_id>/…`. On OpenShift
> AI 3.6.0-ea.2, the MLflow auth plugin resolves the experiment only from
> paths that *start* with the id, so a `resourceNames` grant is denied with
> 403. The grant is still limited to the project (workspace). The agents
> aren't affected: OTLP ingestion resolves the experiment from a header.

## `openshift/eval-job.yaml`

`make eval` creates one Job per run (`uc2-eval-<timestamp>`, kept for 24 h):

| Setting | Source |
|---|---|
| Image | `uc2-agent:latest` (same as the agents) |
| Service account | `uc2-evaluator` |
| Agents | `http://uc2-agent-v1:8000`, `http://uc2-agent-v2:8000` (in-cluster) |
| Judge model / URL | `uc2-llm` ConfigMap (`LLM_MODEL`, `LLM_BASE_URL`) |
| Judge key | The LLM Secret (`OPENAI_API_KEY`) |
| MLflow | `MLFLOW_TRACKING_URI` (in-cluster), `MLFLOW_WORKSPACE`, the token file, the service CA |
| Concurrency | `EVAL_WORKERS` (default 4) |

Follow a run with `oc logs -n <ns> -f job/uc2-eval-<id>`. List runs with
`oc get jobs -n <ns> -l app=uc2-eval`.
