# Troubleshooting

Start with `make ps` and `make logs`.

## MLflow keeps restarting / `exit 137` / bootstrap fails with "connection aborted"

MLflow is being OOM-killed. The image already runs 1 worker and disables the
job executor. If it still happens, other containers are using the VM's memory.

```bash
docker stats --no-stream            # or: podman stats --no-stream
colima stop && colima start --memory 4          # colima
podman machine set --memory 4096                # podman (machine must be stopped)
```

## Agents never become healthy

The agents wait for `mlflow-bootstrap`, which must exit with code 0.

```bash
docker compose logs mlflow-bootstrap agent-redacted
```

- `Could not resolve MLflow experiment`: wrong agent credentials. If you
  changed `AGENT_MLFLOW_PASSWORD` after the first run, either run `make clean`
  or reset the password in MLflow.
- `environment variable X is not set`: a `${VAR}` in the Relay policy has no
  value. Check custom edits to `relay/*.toml`.
- A Relay activation error about an insecure endpoint: you pointed
  `MLFLOW_TRACKING_URI` at a remote HTTP host. Use HTTPS, or add the host to
  `insecure_http_hosts`.

## The agent replies, but no tool call happens / "the model did not call the tool"

The model does not support tool calling, or it is too small. Use
`qwen2.5:7b`, `llama3.1:8b`, or a hosted model, or run `make up-scripted`.

## `Connection refused` to the LLM

- **Native Ollama:** by default Ollama listens only on `127.0.0.1`, which
  containers can't reach. Start it with `OLLAMA_HOST=0.0.0.0 ollama serve`, or
  set it in the Ollama app's settings ("Expose Ollama to the network").
- Check from inside the agent container:
  `docker compose exec agent-redacted python -c "import urllib.request;print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').read()[:200])"`
- **Podman:** `host.docker.internal` works on Podman 5. On older versions, use
  `LLM_BASE_URL=http://host.containers.internal:11434/v1`.

## Traces don't show up in MLflow

- Relay batches spans and exports them within about 0.5 s. Click refresh in the Traces view.
- Check the agent logs for exporter warnings: `docker compose logs agent-redacted | grep -i otel`.
- Make sure you are looking at the right experiment: `uc1-customer-lookup-redacted` or `…-baseline`.

## The MLflow UI asks for a password repeatedly

Log in as `admin` with `MLFLOW_ADMIN_PASSWORD` (default
`mlflow-admin-demo-password`). The password is set only when the auth database
is first created. Run `make clean` after you change it.

## `make` uses the wrong container runtime

The Makefile picks Docker if `docker info` succeeds, otherwise Podman.
Override it: `make up COMPOSE="podman compose"`.

## Port already in use

Set `MLFLOW_PORT`, `REDACTED_AGENT_PORT`, and `BASELINE_AGENT_PORT` in `.env`.
