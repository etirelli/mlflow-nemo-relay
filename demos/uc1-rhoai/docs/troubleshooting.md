# Troubleshooting

Start with `make status` and `oc logs -n <ns> deploy/uc1-agent-redacted`.

## `make check` fails

| Message | Fix |
|---|---|
| `Missing config.env` | `cp config.env.example config.env`, then edit it |
| `namespace … missing` | `oc new-project <ns>` |
| `Secret … not found` | Create it (see [configuration.md](configuration.md#creating-the-api-key-secret)). Check `LLM_API_KEY_SECRET_KEY`. |
| `Cannot find the OpenShift AI gateway` | Set `MLFLOW_PUBLIC_URI` in `config.env`. It's the dashboard's MLflow URL, ending in `/mlflow`. |
| `MLflow is not Available` | `oc get mlflow mlflow -o yaml`. Enable `mlflowoperator` in the DSC and create the `MLflow` CR. |

## `make bootstrap` gets 401 or 403

Your `oc` session expired (`oc login` again), or your user lacks `create` on
`experiments.mlflow.kubeflow.org` in the project. Project admins and editors
have it.

## Agent pods never become Ready

The readiness probe waits for the agent to resolve its MLflow experiment.

```bash
oc logs -n uc1-rhoai deploy/uc1-agent-redacted | grep -E "Waiting for MLflow|Could not resolve"
```

- `experiment … does not exist (run make bootstrap)`: run `make bootstrap`.
  If you changed the experiment names, also run `make deploy`, because the
  Role's `resourceNames` come from them.
- `PERMISSION_DENIED`: the Role or RoleBinding is missing, or the names don't
  match. Check with `oc auth can-i get experiments.mlflow.kubeflow.org/<name> --as=system:serviceaccount:<ns>:uc1-agent -n <ns>`.
- `CERTIFICATE_VERIFY_FAILED`: the `uc1-service-ca` ConfigMap has no
  `service-ca.crt` key yet. It is injected by OpenShift within seconds of
  creation. Run `oc get cm uc1-service-ca -n <ns> -o yaml`.
- `Workspace context is required`: `MLFLOW_WORKSPACE` is empty. It comes from
  `NAMESPACE`.

## No traces in MLflow, and `otel_traces_export_failed` in the agent log

Relay's error doesn't include the cause, so check MLflow's side:

```bash
oc logs -n redhat-ods-applications deploy/mlflow -c mlflow --since=10m | grep v1/traces
```

| MLflow log | Cause |
|---|---|
| `POST /mlflow/v1/traces … 404`, "No Kubernetes authorization rule matched" | The OTLP URL includes the `/mlflow` prefix. It must be `https://<svc>:8443/v1/traces`. Leave `MLFLOW_OTLP_ENDPOINT` empty, or fix it. |
| `POST /v1/traces … 403` | The service account isn't allowed to `update` that experiment. Check the Role's `resourceNames`. |
| `POST /v1/traces … 401` | No or expired token. Check that `/tmp/relay-mlflow-authorization` exists in the pod and starts with `Bearer `. |
| No `/v1/traces` lines at all | TLS or network. Check `MLFLOW_TRACKING_SERVER_CERT_PATH` and that the CA ConfigMap is mounted. |

## The agent replies but never calls the tool

The model doesn't support tool calling, or the endpoint doesn't pass `tools`
through. Test it:

```bash
curl -s "$LLM_BASE_URL/chat/completions" -H "Authorization: Bearer <key>" -H 'content-type: application/json' \
  -d '{"model":"<model>","tools":[{"type":"function","function":{"name":"f","parameters":{"type":"object","properties":{}}}}],"messages":[{"role":"user","content":"call f"}]}'
```

## Empty replies from a reasoning model

Reasoning models spend completion tokens on thinking. Don't set a small
`max_tokens`; the agent doesn't set one.

## `make port-forward` / chat UI unreachable

`make stop-port-forward && make port-forward`. Logs are in `.port-forward/*.log`.
After `make rollout`, run `make port-forward` again, because forwards follow
pods, not Services.

## `make build` is slow or fails

The first build pulls the UBI Python image and installs the dependencies
(about 1.5 min). Run `oc logs -n <ns> bc/uc1-agent` for build logs. The build
context is staged in `.build-ctx/` with only `agent/` and `relay/`, so local
virtualenvs aren't uploaded.

## `make verify`: check 11 shows 401 instead of 302

That's fine. 302 comes from the gateway's OpenShift login redirect, and 401
appears if you point `MLFLOW_PUBLIC_URI` at the service directly. Both count
as rejected.
