# Verification

There are two layers. Both test the **real** Relay policy files and the real agent code.

| Layer | Command | Needs | What it checks |
|---|---|---|---|
| Live stack | `make verify` (after `make scenarios`) | The running compose stack | What MLflow actually stored, plus auth and routing |
| Offline | `make test` | Python + `uv` only | What Relay would export, captured by an in-process OTLP receiver |

## `make verify`: success criteria against MLflow

[`verify.py`](../agent/src/customer_lookup_agent/verify.py) runs in a
container on the compose network. It authenticates as the MLflow admin, reads
every trace back, and checks:

| # | Check | Proposal criterion / gap |
|---|---|---|
| 1 | The redacted experiment has traces | — |
| 2 | A `TOOL` span with status **OK** exists | *MLflow shows both lookup outcomes* |
| 3 | A `TOOL` span with status **ERROR** exists | *…both lookup outcomes* |
| 4 | Every tool span has a parent chain `lookup_customer ← tools ← customer_lookup_agent ← customer-lookup-request` | *Preserve span parentage during OTLP export* / *place in the agent run* |
| 5 | Tool spans have non-zero durations | *useful timing* |
| 6 | The error span's output still says `TimeoutError … did not respond` | *the failure remains understandable* / *error context* |
| 7 | **No SSN anywhere** in the exported traces: every span, attribute, input/output, event, tag and preview. It checks the known synthetic SSNs (dashed and bare digits) and any `NNN-NN-NNNN` value. | *The synthetic SSN is absent from exported telemetry* |
| 8 | `[REDACTED-SSN]` markers are present | Proves the sanitizer ran, rather than the data simply being absent |
| 9 | No SSN in Relay's local ATOF event file | The sanitized canonical stream is clean at the source |
| 10 | **Control:** the baseline experiment *does* contain SSNs | Proves check 7 is meaningful |
| 11 | `POST /v1/traces` without credentials gets **401** | *Authenticated routing* |
| 12 | The agent's service account posting to a non-granted experiment gets **403** | *…to the correct project and experiment* (project isolation) |

*"Redaction leaves the permitted lookup working"* is covered by
`make scenarios`. The API response returns the real customer record, which
proves the tool received the original SSN.

Example output:

```
Redacted experiment: uc1-customer-lookup-redacted
  [PASS] Redacted experiment has traces
  [PASS] MLflow shows a successful tool call (TOOL span, status OK)
  [PASS] MLflow shows a failed tool call (TOOL span, status ERROR)
  [PASS] Tool spans keep their place in the agent run (parent chain to the request root)
         lookup_customer <- tools <- customer_lookup_agent <- customer-lookup-request
  [PASS] Tool spans carry useful timing
         2007 ms, 205 ms
  [PASS] The failure stays understandable after redaction
         "TimeoutError: customer records service did not respond within 2.0s while looking up SSN [REDACTED-SSN]. ..."
  [PASS] No SSN appears in exported MLflow traces (spans, attributes, inputs/outputs, previews)
  [PASS] Redaction markers are present (sanitizer ran, data was not just missing)
  [PASS] No SSN appears in the redacted Relay ATOF event file
Baseline experiment (control, no redaction): uc1-customer-lookup-baseline
  [PASS] Control: without Relay redaction, the SSN DOES leak into MLflow
         194 SSN occurrence(s) across 2 baseline trace(s)
Authenticated routing
  [PASS] OTLP export without credentials is rejected
  [PASS] The agent's service account cannot write to an experiment it was not granted

12/12 checks passed.
```

The exit code is non-zero if any check fails, so `make demo` works as a smoke test.

## `make test`: offline suite

[`tests/`](../tests) starts a tiny OTLP/HTTP receiver in the test process. It
points the **unmodified** `plugins.redacted.toml` / `plugins.baseline.toml` at
that receiver and drives the agent with the scripted model:

- `test_redacted_export_contains_no_ssn`: the app still gets the real record,
  while the OTLP payloads and the ATOF file contain no SSN but do contain
  markers.
- `test_tool_outcomes_and_parentage_survive_export`: one OK and one ERROR tool
  span, positive durations, and a parent chain to the root.
- `test_export_is_authenticated_and_routed`: the `Authorization` and
  `x-mlflow-experiment-id` headers are sent.
- `test_baseline_control_leaks_ssn`: the control.
- `test_policy_files_render`: no unresolved `${VAR}` placeholders.

```bash
make test          # equivalent to: cd agent && uv run --extra test pytest -q
```

## Manual spot checks

```bash
# Relay's local sanitized event stream (ATOF JSONL)
make atof

# Search MLflow for the SSN yourself (as admin)
curl -s -u admin:mlflow-admin-demo-password \
  'http://localhost:5000/ajax-api/3.0/mlflow/traces/search' \
  -H 'content-type: application/json' -d '{"locations":[{"type":"MLFLOW_EXPERIMENT","mlflow_experiment":{"experiment_id":"1"}}]}' \
  | grep -c '900-12-0001'   # expect 0
```
