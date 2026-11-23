# Troubleshooting

Start with `make status`. Most `uc1-rhoai` troubleshooting applies too:
`make check` errors, agents not becoming Ready, `otel_traces_export_failed`,
and port-forwards. See [uc1-rhoai/docs/troubleshooting.md](../../uc1-rhoai/docs/troubleshooting.md).

## `make eval`: the Job fails or hangs

```bash
oc get jobs,pods -n uc2-rhoai -l app=uc2-eval
oc logs -n uc2-rhoai job/uc2-eval-<id>
```

| Symptom | Cause / fix |
|---|---|
| `Could not find experiment` / 403 on `get-by-name` | Run `make bootstrap`, and check that `EVAL_EXPERIMENT` matches between `config.env` and the experiment |
| `403 … /mlflow-artifacts/artifacts/workspaces/…` | The evaluator Role was name-scoped. Keep the project-wide experiments rule from the template (see [configuration.md](configuration.md)). |
| `(MLflow evaluation datasets unavailable …)` | The evaluator lacks `datasets` permissions. The run continues with in-memory records. |
| `ChatCompletionError` with an HTML body | The judge URL. `evaluation.py` appends `/chat/completions` to `LLM_BASE_URL`. Check that `LLM_BASE_URL` ends in `/v1`. |
| Connection refused to `uc2-agent-v1:8000` | The agents aren't Ready. Run `make rollout`. |
| The Job takes more than 10 minutes | It makes 20 agent conversations plus 20 judge calls. Raise `EVAL_WORKERS`, or check the LLM's latency. |

## v1 is rarely blocked

Strong models sometimes decline large refunds on their own. The evaluation's
pressure and circumvention cases still separate v1 from v2. The chat UI's
**Refund $900** quick action reliably triggers the block with GLM 5.3.

## The "View the evaluation results at https://mlflow.redhat-ods-applications.svc…" link in the Job log

MLflow prints its in-cluster tracking URI. Open the same experiment from the
dashboard instead (workspace `uc2-rhoai`), or replace the host with the
`MLFLOW_PUBLIC_URI` that `make up` printed.

## Ports 8000/8001 in use

`uc2-community` or another demo's port-forwards hold them. Stop those
(`make down` / `make stop-port-forward` in that demo), or set
`V1_LOCAL_PORT`/`V2_LOCAL_PORT` in `config.env` and run
`make deploy rollout port-forward`.
