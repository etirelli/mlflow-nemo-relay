# Troubleshooting

Start with `make ps`, `make logs` and `make deny-log`.

## `make up`: "Set LLM_BASE_URL and LLM_API_KEY in .env"

Run `cp .env.example .env` (then `chmod 600 .env`) and set `LLM_BASE_URL`,
`LLM_MODEL` and `LLM_API_KEY`. The model must support tool calling. To try it
without an LLM, run `make up-scripted`.

## `openshell status` fails, or `sandbox create` hangs at "Requesting compute"

The gateway isn't running, or it uses a different engine than `make` does.

```bash
brew services start openshell        # Homebrew gateway (Podman driver here)
openshell status
podman machine list                  # the machine must be running
```

Set `ENGINE=podman` (or `docker`) in `.env` so the image is built where the
gateway can find it.

## The agent never gets ready ("timed out (see: make logs)")

- `make logs` shows the sandbox's own output. A Python traceback during
  startup usually means MLflow wasn't reachable: check `make ps` (MLflow
  healthy?) and `make deny-log` for a denied `host.openshell.internal:5000`.
- If you changed `MLFLOW_PORT` or `PAYMENTS_PORT`, also change the ports in
  `openshell/policy.yaml`. The policy names ports explicitly.

## The LLM call fails inside the sandbox

- `make deny-log` shows `DENIED … <llm-host>`: the provider rule doesn't match.
  Check `telemetry/provider-llm.yaml` (rendered by `make provider`): host,
  port and path must match `LLM_BASE_URL` + `/chat/completions`.
- HTTP 401 from the LLM: the provider has a stale key. Update `.env` and run
  `make provider` (it updates the provider's credential), then `make sandboxes`.
- Changed `LLM_BASE_URL` to another host? Run `make provider-reset`. The
  profile (which holds the host rule) is imported only once.
- The sandbox must be created **with** `--provider uc2-llm`. `make sandboxes`
  does that unless `LLM=scripted`.

## v1 doesn't try the credit

Strong models sometimes decline to move money another way after a blocked
refund. Use the **$900, else as a credit** quick action, which says so
explicitly, or run it a few times. The two `workaround` evaluation cases
measure how often it happens. The scripted model (`make up-scripted`)
always tries.

## A denied request shows up as `ConnectError` instead of `policy_denied`

The host isn't in the policy at all, so OpenShell refuses at TCP level without
an HTTP answer (see `uc1-openshell`). Only hosts with an L7 rule
(`protocol: rest`, `enforcement: enforce`) get the readable `403
policy_denied` body. Here that's the payments service and MLflow.

## `make verify`: "The OpenShell sandbox log records the denied POST /v1/credits" fails

`openshell logs` keeps a short buffer ("log buffer contains only the last N
lines"). If many requests ran after the denial, the line has scrolled out.
Run the **$900, else as a credit** scenario again, then `make verify`
immediately.

## `make verify`: the ledger check fails with credits or refunds above $500

Something reached the payments service that shouldn't have. Check
`make ledger` (each row has `agent_version` and `request_id`) and
`make policy-show`. A policy change through `openshell policy set` is
live, and the effective policy may differ from the file. `make clean`
resets the ledger.

## `make eval`: the judge fails, or `policy_compliant_reply` shows n/a

Same as `uc2-community`: the judge `base_url` must be the full
chat-completions URL (`evaluation.py` appends it), `pandas` comes from the
`eval` extra (use `make eval`), and the judge must return `bool`.

## Ports already in use

Ports 5000, 8000, 8001 and 8090 are shared with other demos (and with
`oc port-forward` for the RHOAI demos). Stop them, or change the ports in
`.env` **and** in `openshell/policy.yaml`.

## MLflow OOM / restarting

Give the Podman machine 4 GiB. Two sandboxes, MLflow and the payments
service fit, but not much else.
