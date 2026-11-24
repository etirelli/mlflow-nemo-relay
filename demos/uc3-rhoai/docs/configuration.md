# Configuration

## `config.env`

Everything cluster-specific lives in `config.env`, which is gitignored and
created from [`config.env.example`](../config.env.example). The Makefile
passes it to the OpenShift Templates with `oc process --param-file`.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `NAMESPACE` | ✅ | — | Project, and also the MLflow workspace |
| `LLM_BASE_URL` | ✅ | — | OpenAI-compatible base URL (`…/v1`), used by the agents and the judge |
| `LLM_MODEL` | ✅ | — | Model id from `GET $LLM_BASE_URL/models` |
| `LLM_API_KEY_SECRET` / `_KEY` | ✅ | — / `api-key` | Existing Secret in `NAMESPACE` |
| `REFUND_LIMIT` | | `500` | The business rule the labels follow (USD per request) |
| `LOAD_ROUNDS` / `EVAL_WORKERS` | | `1` / `4` | Equivalent load per policy |
| `LLM_PROVIDER` | | `openai` | `scripted` means no LLM; the evaluation then skips the judge |
| `TRACE_EXPERIMENT` / `EVAL_EXPERIMENT` / `NOT_GRANTED_EXPERIMENT` | | `uc3-rhoai-policy-validation` / `…-eval` / `uc3-rhoai-not-granted` | The agents' Role is generated from `TRACE_EXPERIMENT` |
| `PROMETHEUS_URL` | | derived from the `data-science-prometheus-route` | RHOAI monitoring stack, namespace proxy |
| `CLUSTER_PROMETHEUS_URL` | | derived from the `thanos-querier` route in `openshift-monitoring` | Used by `make verify` from the laptop (the Job uses the in-cluster tenancy port) |

The policy versions themselves are code (`policy.py`), one Deployment each.

## `openshift/template.yaml` (applied into `NAMESPACE`)

| Object | Purpose |
|---|---|
| `ServiceAccount uc3-agent` + `Role/RoleBinding uc3-trace-writer` | All three policy Deployments: `get`, `update` on `TRACE_EXPERIMENT` only |
| `ServiceAccount uc3-evaluator` + `Role/RoleBinding uc3-evaluator` | Evaluation Job: experiments and datasets in the workspace (project-wide because of the MLflow artifact-path issue; see `uc2-rhoai`) |
| `Role/RoleBinding uc3-metrics-reader` | Evaluation Job: `get pods`, `get pods.metrics.k8s.io` in `NAMESPACE` (the cluster Prometheus tenancy port) |
| `ConfigMap uc3-service-ca` | Injected service CA, trusted for MLflow and thanos-querier TLS |
| `ConfigMap uc3-llm` | `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `REFUND_LIMIT` |
| `ImageStream` + `BuildConfig uc3-agent` | In-cluster build (`make build`) |
| `Deployment`/`Service uc3-agent-policy-v1/v2/v3` | The agent under each policy (`POLICY_VERSION`) |
| `ServiceMonitor uc3-agents` | Labelled `monitoring.opendatahub.io/scrape: "true"`, so OpenShift AI Observability scrapes `/metrics` |

## `openshift/monitoring-access.yaml` (applied into `redhat-ods-monitoring`)

A `Role` and `RoleBinding` that give `uc3-evaluator` `get pods.metrics.k8s.io`
in `redhat-ods-monitoring`. This is needed because RHOAI 3.6 relabels
user-workload series to that namespace (OBS-2 in the repo's product gaps report). It's plain
YAML, not a Template, because `oc process` drops `metadata.namespace`.

Apply it with `make monitoring-access` (cluster admin). `make up` runs it.

## `openshift/eval-job.yaml`

`make eval` creates one Job per run (`uc3-eval-<timestamp>`, kept for 24 h):

| Setting | Value |
|---|---|
| Image / service account | `uc3-agent:latest` / `uc3-evaluator` |
| Policies | `http://uc3-agent-policy-v1:8000`, `…-v2`, `…-v3` (in-cluster) |
| Judge | `uc3-llm` ConfigMap plus the LLM Secret |
| MLflow | In-cluster URI, workspace, token file, service CA |
| RHOAI metrics | `PROMETHEUS_URL` (proxy route), `PROMETHEUS_NAMESPACE=redhat-ods-monitoring`, `AGENT_METRICS_SELECTOR=policy="{policy}",k8s_namespace_name="<ns>"`, token file |
| Cluster metrics | `CLUSTER_PROMETHEUS_URL=https://thanos-querier.openshift-monitoring.svc:9092`, `CLUSTER_PROMETHEUS_NAMESPACE=<ns>`, service CA |
| Load | `LOAD_ROUNDS`, `EVAL_WORKERS` |

Follow a run with `oc logs -n <ns> -f job/uc3-eval-<id>`.
