# Troubleshooting

Start with `make ps` (sandboxes, forwards, compose services) and `make logs`
(gateway and sandbox logs for the redacted agent).

## `openshell status` fails / no gateway

On macOS, the installer runs the gateway as a Homebrew service:

```bash
brew services restart openshell
openshell status
cat ~/.config/openshell/gateway.toml
```

If Docker and Podman are both installed, the gateway auto-detects Kubernetes,
then Podman, then Docker. Pin the driver so that it matches the engine that
builds the image (`ENGINE` in the Makefile):

```toml
# ~/.config/openshell/gateway.toml
[openshell]
version = 2
[openshell.gateway]
compute_driver = "docker"
```

## `sandbox create` fails: image not found

The image must exist in the **gateway's** engine. Build it with the same
engine (`make image ENGINE=docker` or `ENGINE=podman`). Podman needs the
`localhost/` prefix, which the Makefile adds.

## Sandbox fails to start: Landlock ABI

OpenShell needs Landlock ABI v3 or later (Linux 6.2+). On macOS that is the
kernel of the Docker Desktop or Podman VM. OpenShell qualifies Docker Desktop
on Apple Silicon. Other VMs (colima, older podman machines) may run an older
kernel. Check it:

```bash
docker run --rm alpine uname -r     # needs 6.2 or later
```

## Agent never becomes ready (`waiting for the agent on :8000 … timed out`)

```bash
openshell logs uc1-agent-redacted --since 10m --source all
```

- `Could not resolve MLflow experiment`, with `policy_denied` in the error: the
  MLflow client called an API that `policy.yaml` does not allow. Look for the
  denied method and path in `make deny-log` and add it to `mlflow_tracking`.
  Then run `openshell policy set uc1-agent-redacted --policy openshell/policy.yaml --wait`,
  which hot-reloads the policy.
- `Could not resolve MLflow experiment`, with a connection error: MLflow is
  not reachable at `host.openshell.internal:5000`. Check that `make infra`
  succeeded, that compose publishes port 5000 on all interfaces, and that
  `MLFLOW_ALLOWED_HOSTS` includes `host.openshell.internal` (MLflow answers
  `400 Invalid Host header` otherwise).
- A Relay activation error about an insecure endpoint:
  `insecure_http_hosts` is derived from `MLFLOW_TRACKING_URI`. Use the
  `host.openshell.internal` default, or HTTPS.
- A permission error writing `/sandbox/telemetry` or `/tmp`: the filesystem
  policy was changed. Both must stay in `read_write`.

## Port forward not working (`curl localhost:8000` refused)

```bash
openshell forward list
openshell forward stop 8000 uc1-agent-redacted
openshell forward start 8000 uc1-agent-redacted -d
```

uvicorn must listen on `127.0.0.1` inside the sandbox, which the Makefile
sets, because the forward connects to loopback in the sandbox.

## The LLM call is denied, or `Connection refused` to the LLM

- `make deny-log` shows a denial to `host.openshell.internal:11434`: the
  binary path in the policy does not match the interpreter. Check it with
  `openshell sandbox exec -n uc1-agent-redacted -- readlink -f $(which python3)`.
- **Native Ollama** listens on `127.0.0.1` by default. The supervisor
  reaches the laptop through the host gateway, so start Ollama with
  `OLLAMA_HOST=0.0.0.0 ollama serve`, or enable "Expose Ollama to the network".
- A different LLM endpoint is denied by design. Add a rule or a provider (see
  [configuration.md](configuration.md#another-openai-compatible-endpoint)).

## The CRM scenario does not show a denial

- `make deny-log` is empty, but the tool still failed: if the tool error says
  `ConnectError` / `nodename nor servname`, the agent is not running in a
  sandbox (DNS failure on a normal host). Check `sandbox:` in the UI header.
- A real LLM did not call `notify_partner_crm`. Small models sometimes skip
  the second tool. Use `qwen2.5:7b` or larger, a hosted model, or `make up-scripted`.
- The denial log format can differ between OpenShell versions. `verify.py`
  looks for lines that mention `partner-crm.example.com` and `deni`/`deny`.
  Run `openshell logs uc1-agent-redacted --since 30m --source sandbox` without
  `--level warn`, which hides policy events.

## Traces don't show up in MLflow

- Relay batches spans and exports them within about 0.5 s. Refresh the Traces view.
- Check the sandbox log for exporter warnings and for denials of `POST /v1/traces`.
- Look at the right experiment: `uc1-openshell-redacted` or `…-baseline`.

## MLflow keeps restarting / `exit 137`

This is the same as in `uc1-community`: MLflow is being OOM-killed. Give the
VM 4 GB of memory. The sandboxes run in the same VM, so they add to the load.

## `make verify` fails with `uv: command not found`

Scenarios, evidence checks and tests run on the laptop with
[uv](https://docs.astral.sh/uv/): `brew install uv`.

## Port already in use

`uc1-community` and `uc1-openshell` use the same ports. Stop one
(`make down`), or set `MLFLOW_PORT`, `REDACTED_AGENT_PORT` and
`BASELINE_AGENT_PORT` in `.env`.
