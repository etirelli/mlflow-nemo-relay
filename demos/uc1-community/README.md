# UC1 (community): Observe tool calls without exposing sensitive inputs

A LangGraph customer-support agent looks up customers by Social Security
number. **NVIDIA NeMo Relay** redacts the SSN from every piece of telemetry
before it leaves the process. **MLflow** then shows engineers which tool calls
succeeded or failed, with timing and error context, and never stores the SSN.

This permutation uses **only upstream community components**, so one
`compose up` on a laptop runs it.

| Component | Version | Role |
|---|---|---|
| [NeMo Relay](https://github.com/NVIDIA/NeMo-Relay) (`nemo-relay[langgraph]`) | 0.11.0 | Agent runtime: managed tool/LLM execution, `pii_redaction` plugin, OTLP export |
| [LangGraph](https://github.com/langchain-ai/langgraph) / LangChain | 1.2 / 1.4 | The agent (`create_agent` with `NemoRelayMiddleware`) |
| [MLflow](https://github.com/mlflow/mlflow) | 3.17.2 | Tracking server with basic auth and OTLP trace ingestion (`/v1/traces`) |
| Any OpenAI-compatible LLM | — | Ollama (default), vLLM, NVIDIA NIM / build.nvidia.com, OpenAI, or a built-in scripted model |

## What the demo shows

1. **Run a customer lookup.** You ask the agent, by chat UI or REST API, to
   look up a synthetic customer. It calls `lookup_customer(ssn=...)`, which
   returns the account. A second customer lives on a "legacy shard" that never
   answers, so that tool call **times out**, which is the controlled failure.
2. **Sanitize and export.** Relay's `pii_redaction` plugin replaces the SSN
   with `[REDACTED-SSN]` in tool arguments, tool results, error messages, LLM
   prompts and responses, and the request/response of the agent run, *before*
   the OTLP exporter sees the data. The tool and the LLM still receive the
   real value.
3. **Inspect in MLflow.** The trace shows `customer-lookup-request → agent →
   tools → lookup_customer` with status (OK / ERROR) and duration. The failure
   is still readable: *"TimeoutError: customer records service did not
   respond within 2.0s while looking up SSN [REDACTED-SSN]…"*.
4. **Before/after.** A second copy of the agent runs *without* redaction and
   writes to its own experiment, which shows the SSN leaking into telemetry
   about 90 times per trace.
5. **Proof.** `make verify` reads everything back from MLflow and checks the
   success criteria automatically (12 checks).

## Quick start

Prerequisites: Podman (with `podman compose`) or Docker (Desktop, colima,
etc.) with about 2 GB free memory. Optionally, a local LLM.

```bash
cd demos/uc1-community
cp .env.example .env            # optional; defaults work with native Ollama

# Option A: real LLM through Ollama on your machine (recommended on macOS)
ollama pull qwen2.5:7b          # once
OLLAMA_HOST=0.0.0.0 ollama serve   # if Ollama is not already running
make up

# Option B: no LLM at all (deterministic scripted model, good for rehearsals)
make up-scripted

make demo                       # sends both scenarios to both agents, then verifies
```

| URL | What |
|---|---|
| http://localhost:8000 | Chat UI (toggle *Redacted* / *Baseline*) and API of the redacted agent |
| http://localhost:8001 | Baseline agent (no redaction) |
| http://localhost:5000 | MLflow UI. Log in as `admin` / `mlflow-admin-demo-password` (from `.env`) |

API example:

```bash
curl -s localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"message": "Please look up the customer with SSN 900-12-0001."}' | jq
```

Stop with `make down`. `make clean` also deletes the MLflow data.

## Documentation

| Doc | For |
|---|---|
| [docs/demo-script.md](docs/demo-script.md) | Presenters: a 5-minute talk track with click-by-click steps |
| [docs/architecture.md](docs/architecture.md) | How the pieces fit: data flow, redaction boundary, auth and routing |
| [docs/configuration.md](docs/configuration.md) | LLM options, environment variables, the Relay policy explained |
| [docs/verification.md](docs/verification.md) | The automated checks, the offline test suite, and the mapping to the success criteria |
| [docs/product-gaps.md](docs/product-gaps.md) | What we validated against the proposal's product gaps, and the findings |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems and fixes |

## Layout

```
uc1-community/
├── compose.yaml            # mlflow, mlflow-bootstrap, agent-redacted, agent-baseline, verify, ollama
├── Makefile                # up / up-scripted / up-ollama / demo / verify / down / clean / test
├── .env.example
├── relay/
│   ├── plugins.redacted.toml   # Relay policy: OTLP→MLflow + pii_redaction (the demo)
│   └── plugins.baseline.toml   # same exporters, no redaction (the "before")
├── mlflow/
│   ├── Containerfile           # upstream MLflow with basic auth
│   ├── basic_auth.ini
│   └── bootstrap.py            # service account, experiments, least-privilege grants
├── agent/
│   ├── Containerfile
│   ├── pyproject.toml
│   └── src/customer_lookup_agent/
│       ├── agent.py            # LangGraph agent + NemoRelayMiddleware
│       ├── tools.py            # lookup_customer tool (echoes the SSN on purpose)
│       ├── customer_db.py      # synthetic records + slow "legacy shard"
│       ├── relay_runtime.py    # Relay activation, MLflow auth and experiment routing
│       ├── app.py              # FastAPI: /api/chat, /api/info, chat UI
│       ├── scripted_model.py   # offline stand-in for the LLM
│       ├── scenarios.py        # `make scenarios`
│       ├── verify.py           # `make verify`
│       └── static/index.html   # chat UI
├── tests/                  # offline pytest suite (no containers, no LLM)
└── docs/
```
