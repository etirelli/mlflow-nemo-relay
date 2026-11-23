# Verification

| Layer | Command | Needs | Checks |
|---|---|---|---|
| Live | `make demo` (= `make scenarios verify`) | The deployed demo, `make port-forward`, `oc` login | What MLflow in OpenShift AI stored, plus authentication and least privilege |
| Offline | `make test` | uv only | What Relay would export: headers, redaction, token rotation |

## `make verify`

`make evidence` first copies Relay's ATOF files out of the pods
(`oc exec … cat`). Then
[`verify.py`](../agent/src/customer_lookup_agent/verify.py) runs on the laptop
against the MLflow gateway (`MLFLOW_PUBLIC_URI`). It authenticates as **you**
(`oc whoami -t`), in workspace `NAMESPACE`:

| # | Check | Proposal criterion / gap |
|---|---|---|
| 1 | The redacted experiment has traces | — |
| 2 | A `TOOL` span with status **OK** | *MLflow shows both lookup outcomes* |
| 3 | A `TOOL` span with status **ERROR** | *…both lookup outcomes* |
| 4 | Parent chain `lookup_customer ← tools ← customer_lookup_agent ← customer-lookup-request` | *Preserve span parentage* |
| 5 | Non-zero durations | *Useful timing* |
| 6 | The error still says `TimeoutError … did not respond` | *The failure remains understandable* |
| 7 | **No SSN** anywhere in the redacted traces | *The synthetic SSN is absent from exported telemetry* |
| 8 | `[REDACTED-SSN]` markers are present | The sanitizer ran |
| 9 | No SSN in Relay's ATOF file, copied out of the pod | The sanitized stream is clean at the source |
| 10 | **Control:** the baseline experiment contains SSNs | Check 7 is meaningful |
| 11 | OTLP without a token is rejected (gateway: **302** to the OpenShift login) | *Authenticated routing* (gap 3) |
| 12 | The agent's service account token **cannot** write to `uc1-rhoai-not-granted` in the same workspace (**403**) | *…to the correct project and experiment* (gap 3, least privilege) |

Live output, 2026-11-23 (OpenShift AI 3.6.0-ea.2, GLM 5.3):

```
Redacted experiment: uc1-rhoai-redacted
  [PASS] Redacted experiment has traces
         2 trace(s)
  [PASS] MLflow shows a successful tool call (TOOL span, status OK)
  [PASS] MLflow shows a failed tool call (TOOL span, status ERROR)
  [PASS] Tool spans keep their place in the agent run (parent chain to the request root)
         lookup_customer <- tools <- customer_lookup_agent <- customer-lookup-request
  [PASS] Tool spans carry useful timing
         2001 ms, 202 ms
  [PASS] The failure stays understandable after redaction
         "TimeoutError: customer records service did not respond within 2.0s while looking up SSN [REDACTED-SSN]. ..."
  [PASS] No SSN appears in exported MLflow traces (spans, attributes, inputs/outputs, previews)
         scanned 135905 bytes
  [PASS] Redaction markers are present (sanitizer ran, data was not just missing)
         161 occurrence(s) of [REDACTED-SSN]
  [PASS] No SSN appears in the redacted Relay ATOF event file
Baseline experiment (control, no redaction): uc1-rhoai-baseline
  [PASS] Control: without Relay redaction, the SSN DOES leak into MLflow
         176 SSN occurrence(s) across 2 baseline trace(s)
Authenticated routing
  [PASS] OTLP export without credentials is rejected
         POST /v1/traces without a token -> HTTP 302
  [PASS] The agent's service account cannot write to an experiment its Role does not name
         POST /v1/traces to 'uc1-rhoai-not-granted' (same workspace) as the agent -> HTTP 403

12/12 checks passed.
```

Traces accumulate across runs. The checks hold for any number of traces.

## `make test` (offline)

The tests use the real Relay policies, the agent with the scripted model, and
an in-process OTLP receiver:

- `test_redacted_export_contains_no_ssn`, `test_tool_outcomes_and_parentage_survive_export`, `test_baseline_control_leaks_ssn`: as in uc1-community.
- `test_export_is_authenticated_and_routed`: `Authorization: Bearer <token from header_file>`, `x-mlflow-workspace` and `x-mlflow-experiment-id` are sent.
- `test_bearer_header_file_follows_token_rotation`: rotating the token file updates the header file, which has mode `0600`.
- `test_tls_block_is_optional`: the `[tls]` table appears only when a CA is set.
- `test_otlp_endpoint_is_not_under_the_static_prefix`: `…/mlflow` gives an OTLP endpoint of `…/v1/traces`.
- `test_policy_files_render`: no unresolved `${VAR}`.

## Manual spot checks

```bash
make status
oc logs -n uc1-rhoai deploy/uc1-agent-redacted | grep -c export_failed     # expect 0
oc auth can-i update experiments.mlflow.kubeflow.org/uc1-rhoai-redacted \
  --as=system:serviceaccount:uc1-rhoai:uc1-agent -n uc1-rhoai                # yes
oc auth can-i create experiments.mlflow.kubeflow.org \
  --as=system:serviceaccount:uc1-rhoai:uc1-agent -n uc1-rhoai                # no
```
