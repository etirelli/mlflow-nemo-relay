# Configuration

Every setting has a working default. Override settings in `.env`, which you
create by copying [`.env.example`](../.env.example), or as environment
variables on the `make` / `compose` command line.

## LLM backends

The agent uses LangChain's `ChatOpenAI` against any **OpenAI-compatible**
endpoint. The model must support **tool calling**.

| Backend | `.env` settings | Notes |
|---|---|---|
| Native Ollama (default) | `LLM_BASE_URL=http://host.docker.internal:11434/v1`<br/>`LLM_MODEL=qwen2.5:7b` | Best on macOS, where containers have no GPU. Run `ollama pull qwen2.5:7b`, then make sure Ollama listens on all interfaces: `OLLAMA_HOST=0.0.0.0 ollama serve`. |
| Ollama in compose | `make up-ollama` | Sets `LLM_BASE_URL=http://ollama:11434/v1` and pulls `OLLAMA_MODEL` (default `qwen2.5:7b`). CPU-only on macOS, so slow. |
| NVIDIA hosted (build.nvidia.com) | `LLM_BASE_URL=https://integrate.api.nvidia.com/v1`<br/>`LLM_MODEL=meta/llama-3.3-70b-instruct`<br/>`LLM_API_KEY=nvapi-…` | Fast, with reliable tool calls. Needs network access and a key. |
| vLLM / NIM / other | `LLM_BASE_URL=http://host:8000/v1`<br/>`LLM_MODEL=<served model>` | vLLM needs `--enable-auto-tool-choice --tool-call-parser <parser>`. |
| OpenAI | `LLM_BASE_URL=https://api.openai.com/v1`<br/>`LLM_MODEL=gpt-4o-mini`<br/>`LLM_API_KEY=sk-…` | |
| None (scripted) | `LLM_PROVIDER=scripted`, or `make up-scripted` | A deterministic stand-in that still emits real Relay LLM spans. Use it for rehearsals, recordings, and CI. |

Model guidance: `qwen2.5:7b` and larger work well. `qwen2.5:0.5b` calls the
tool correctly, but its explanations of the timeout are poor.

> **Note:** with a hosted LLM, the *prompt* that contains the SSN is sent to
> the provider. That is real execution, and Relay does not change it.
> Redaction applies to telemetry. The demo uses synthetic data, but take this
> into account for real workloads.

## Environment variables

### Agent (`agent-redacted`, `agent-baseline`)

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` (any OpenAI-compatible endpoint) or `scripted` |
| `LLM_BASE_URL` | `http://host.docker.internal:11434/v1` | Chat completions base URL |
| `LLM_MODEL` | `qwen2.5:7b` | Model name |
| `LLM_API_KEY` | `not-needed` | API key, if the endpoint needs one |
| `TOOL_TIMEOUT_SECONDS` | `2.0` | Lookup timeout. The "legacy shard" customer takes 30 s. |
| `RELAY_MODE` | set per service | `redacted` / `baseline`, shown in the UI and API |
| `RELAY_PLUGINS_FILE` | set per service | Relay policy TOML (see below) |
| `MLFLOW_TRACKING_URI` | `http://mlflow:5000` | Internal MLflow URL. The OTLP endpoint is `<uri>/v1/traces`. |
| `MLFLOW_PUBLIC_URI` | `http://localhost:5000` | Browser-facing MLflow URL, used for links |
| `MLFLOW_EXPERIMENT_NAME` | set per service | Experiment that receives the traces. Resolved to an id at startup. |
| `MLFLOW_TRACKING_USERNAME` / `_PASSWORD` | from `AGENT_MLFLOW_*` | The agent's MLflow service account |
| `RELAY_TELEMETRY_DIR` | `/app/telemetry` | Where the ATOF file sink writes. This is the shared `relay-telemetry` volume. |

At startup, `relay_runtime.configure_mlflow_routing()` derives the variables
that the policy files reference: `MLFLOW_OTLP_HOST`,
`MLFLOW_OTLP_TRACES_ENDPOINT`, `MLFLOW_OTLP_AUTHORIZATION` (a `Basic …`
header) and `MLFLOW_OTLP_EXPERIMENT_ID`.

### Compose-level (`.env`)

| Variable | Default |
|---|---|
| `MLFLOW_ADMIN_PASSWORD` | `mlflow-admin-demo-password` |
| `MLFLOW_SECRET_KEY` | `uc1-demo-secret-key-change-me` (Flask CSRF key, required by MLflow auth) |
| `AGENT_MLFLOW_USERNAME` / `AGENT_MLFLOW_PASSWORD` | `relay-agent` / `relay-agent-demo-password` |
| `MLFLOW_PORT`, `REDACTED_AGENT_PORT`, `BASELINE_AGENT_PORT` | `5000`, `8000`, `8001` |

The admin password is applied only when MLflow first creates its auth
database. To change it later, run `make clean`, or use MLflow's
update-password API.

## The Relay policy files

[`relay/plugins.redacted.toml`](../relay/plugins.redacted.toml) is the heart
of the demo. At startup, the agent expands `${VAR}` placeholders from its
environment and passes the result to `nemo_relay.plugin.activate()`.

```toml
[[components]]
kind = "observability"            # export
[components.config]
version = 4
insecure_http_hosts = ["${MLFLOW_OTLP_HOST}"]   # demo network only; use TLS in prod
[[components.config.opentelemetry.endpoints]]
type = "openinference"            # MLflow maps OpenInference span kinds to span types
endpoint = "${MLFLOW_OTLP_TRACES_ENDPOINT}"
[components.config.opentelemetry.endpoints.header_env]
authorization = "MLFLOW_OTLP_AUTHORIZATION"
"x-mlflow-experiment-id" = "MLFLOW_OTLP_EXPERIMENT_ID"

[[components]]
kind = "pii_redaction"            # sanitize before ANY exporter sees the event
[[components.config.profiles]]    # 1: the structured field, any format
[components.config.profiles.builtin]
action = "redact"
pattern = '(?s).+'
target_paths = ["/ssn"]
replacement = "[REDACTED-SSN]"
[[components.config.profiles]]    # 2: SSN-shaped text anywhere (echoes, errors, prompts)
[components.config.profiles.builtin]
action = "redact"
pattern = '\b\d{3}[- ]\d{2}[- ]\d{4}\b'
replacement = "[REDACTED-SSN]"
```

Variations to try:
- `action = "mask"` with `unmasked_suffix = 4` masks the SSN but keeps the last four digits for correlation.
- `action = "hash"` replaces matches with SHA-256 digests. Note that SSNs have a
  small keyspace, so a plain hash can be brute-forced.
- Add profiles for other data. Built-in detectors include `email`, `phone`,
  `credit_card`, `api_key`, and `jwt`.

[`relay/plugins.baseline.toml`](../relay/plugins.baseline.toml) is identical
but has no `pii_redaction` component.

> **Why not an undashed SSN regex?** A pattern like `\d{3}-?\d{2}-?\d{4}` also
> matches unrelated 9-digit numbers, such as nanosecond timestamp fractions
> (`…:41.411581132Z`). We found this during testing on Linux. Profile 1
> already covers the structured field whatever its format.

## Running without containers

```bash
cd agent
uv venv && uv pip install -e '.[test]'
uv run pytest -q          # offline suite: real Relay policy, in-process OTLP receiver
```

To run the service locally against your own MLflow, set the agent variables
above and run `uvicorn customer_lookup_agent.app:app --port 8000`.
