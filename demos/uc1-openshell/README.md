# UC1 (OpenShell): Observe tool calls without exposing sensitive inputs, from a sandboxed agent

This demo is [`uc1-community`](../uc1-community) with one change: the
LangGraph agent runs inside an **NVIDIA OpenShell** sandbox.

- **NeMo Relay** controls *what the telemetry contains*. It redacts the SSN
  from every span before export.
- **OpenShell** controls *where the agent can connect and what it can touch*.
  It allows the LLM, and nothing else: the traces leave through OpenShell's
  agent trace relay.
- **MLflow** shows the evidence: tool outcomes, timing, and errors, including
  the connection the sandbox refused.

| Component | Version | Role |
|---|---|---|
| [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) | 0.1.9 | Sandbox runtime: Landlock filesystem rules, a policy-enforced egress proxy (L7 for HTTP), credential injection through providers, the agent trace relay |
| [NeMo Relay](https://github.com/NVIDIA/NeMo-Relay) (`nemo-relay[langgraph]`) | 0.11.2 | Agent runtime: managed tool/LLM execution, `pii_redaction` plugin, OTLP export |
| [LangGraph](https://github.com/langchain-ai/langgraph) / LangChain | 1.2 / 1.4 | The agent (`create_agent` with `NemoRelayMiddleware`) |
| [MLflow](https://github.com/mlflow/mlflow) | 3.17.2 | Tracking server with basic auth and OTLP trace ingestion (`/v1/traces`), run in compose outside the sandbox |
| [OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector-contrib) (contrib) | 0.165.0 | Receives the traces from the OpenShell relay, adds the MLflow service account, routes each Relay mode to its experiment |
| Any OpenAI-compatible LLM | — | Native Ollama (default), build.nvidia.com through an OpenShell provider, or the built-in scripted model |

> **Status:** validated end to end on 2026-11-23. Setup: OpenShell 0.1.9 with
> the Homebrew gateway and the Podman driver (rootless Podman 5, Apple M2, VM
> kernel 6.9), native Ollama with `qwen2.5:0.5b`. Result: `make demo` passes
> 16/16, and `make test` passes 8 offline tests. Docker Desktop and colima
> have not been tried. Findings are in the consolidated
> [product gaps report](../../docs/product-gaps.md#nvidia-openshell).

## What the demo shows

1. **Run a customer lookup inside a sandbox.** The agent runs in the
   `uc1-agent-redacted` sandbox. It looks up a synthetic customer by SSN
   (success), then one on a slow "legacy shard" (a controlled **timeout**).
2. **Sanitize and export.** Relay's `pii_redaction` plugin replaces the SSN with
   `[REDACTED-SSN]` before the OTLP exporter sees the data. The export leaves
   the sandbox through OpenShell's **agent trace relay**: the supervisor stamps
   `openshell.sandbox.id` on it and forwards it to the collector, which adds the
   MLflow credentials and routes it to the experiment of its Relay mode. The
   agent has no network route to MLflow and holds no MLflow credentials.
3. **Block an exfiltration path.** You ask the agent to *"sync the record to
   the partner CRM"*. The agent calls `notify_partner_crm`, and the sandbox
   refuses the connection to `partner-crm.example.com` before any data leaves.
   The tool reports `EgressBlocked: …`, and the agent explains the problem.
4. **Inspect in MLflow.** Each trace shows `customer-lookup-request → agent →
   tools → lookup_customer / notify_partner_crm`, with status (OK / ERROR),
   duration, and readable errors. The SSN appears nowhere in a trace, not
   even in the echoed error of the blocked call. The root span carries
   `demo.sandbox = uc1-agent-redacted`.
5. **Before/after.** A second sandbox, `uc1-agent-baseline`, runs the same
   image and policy without redaction, and its traces leak the SSN.
6. **Keep the SSN from the LLM (opt-in).** Tick *Keep SSN from the LLM* in the
   chat UI (or send `"protect_llm": true`): two Relay request intercepts,
   registered on that request's scope only, replace the SSN with a reference
   such as `SSN_REF_1` before the model sees it and swap it back before the
   tool runs. The LLM span in MLflow then shows the reference the model
   received.
7. **Proof.** `make verify` collects evidence from the sandbox: the Relay ATOF
   file, the OpenShell deny log, and an egress probe. It then checks the UC1
   success criteria plus the sandbox criteria, 18 checks in all.

## Quick start

Prerequisites:
- **OpenShell 0.1.9** with a running gateway. On macOS, install it with
  `curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh`,
  which sets up a Homebrew service. Check it with `openshell status`.
- **Podman 5** (validated: give the machine 4 GiB, `podman machine set --memory 4096`)
  or **Docker** (Docker Desktop is the macOS runtime OpenShell qualifies; not tried
  here). It must be the same engine the gateway uses; pin it with
  `compute_driver` in `~/.config/openshell/gateway.toml`.
- **The OpenShell agent trace relay**, turned on once in the gateway config
  (`make gateway-config` prints the setting and where it goes).
- **uv**, for scenarios, verify and tests.
- Optionally, a local LLM.

```bash
cd demos/uc1-openshell
cp .env.example .env              # optional

# Option A: real LLM through native Ollama on your laptop
ollama pull qwen2.5:7b
make up                            # with Podman: make up ENGINE=podman
# Low-memory laptop (16 GB): ollama pull qwen2.5:0.5b and set LLM_MODEL=qwen2.5:0.5b in .env

# Option B: no LLM at all (deterministic scripted model, good for rehearsals)
make up-scripted

# Option C: build.nvidia.com; the API key stays outside the sandbox
export NVIDIA_API_KEY=nvapi-...
make provider-nvidia && make up LLM=nvidia

make demo                         # scenarios + evidence + 18 checks
```

| URL / command | What |
|---|---|
| http://localhost:8000 | Chat UI (toggle *Redacted* / *Baseline*), forwarded from sandbox `uc1-agent-redacted` |
| http://localhost:8001 | Baseline agent, forwarded from sandbox `uc1-agent-baseline` |
| http://localhost:5000 | MLflow UI. Log in as `admin` / `mlflow-admin-demo-password` |
| `make deny-log` | Connections the OpenShell policy denied |
| `make probe` | Run an egress probe inside the sandbox (PyPI, partner CRM, MLflow) |
| `make collector-logs` | The collector between the OpenShell relay and MLflow |
| `make policy-show` | The effective sandbox policy |
| `make term` | OpenShell TUI, with live `action=deny` events |

Stop with `make down`. `make clean` also deletes the MLflow data and the
collected evidence.

## Documentation

| Doc | For |
|---|---|
| [docs/demo-script.md](docs/demo-script.md) | Presenters: a 6-minute talk track with click-by-click steps |
| [docs/architecture.md](docs/architecture.md) | The three control layers, the data flow, and the sandbox boundary |
| [docs/configuration.md](docs/configuration.md) | LLM options, the OpenShell policy and provider, the Relay policy, variables |
| [docs/verification.md](docs/verification.md) | The automated checks and the offline test suite |
| [Product gaps report](../../docs/product-gaps.md) | Validation status and findings for Relay, MLflow and OpenShell (consolidated, repo root) |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems and fixes |

## Layout

```
uc1-openshell/
├── compose.yaml            # mlflow, mlflow-bootstrap, otel-collector, (ollama). The agents are NOT here.
├── Makefile                # up / up-scripted / demo / verify / evidence / deny-log / down / test
├── .env.example
├── openshell/
│   ├── policy.yaml             # sandbox policy: filesystem + L7 egress allow-list (no MLflow route)
│   ├── gateway-agent-relay.toml  # one-time gateway setting: the agent trace relay (`make gateway-config`)
│   └── providers/nvidia-build.yaml   # optional provider: build.nvidia.com with key injection
├── relay/
│   ├── plugins.redacted.toml   # Relay policy: OTLP→OpenShell agent trace relay + pii_redaction
│   └── plugins.baseline.toml   # same exporters, no redaction
├── otel/collector.yaml     # collector: relay -> MLflow, service account, one experiment per Relay mode
├── mlflow/                 # upstream MLflow with basic auth + bootstrap
├── agent/
│   ├── Containerfile           # OpenShell sandbox image (non-root, /sandbox workspace)
│   └── src/customer_lookup_agent/
│       ├── tools.py            # lookup_customer + notify_partner_crm (the egress the sandbox blocks)
│       ├── egress_probe.py     # run inside the sandbox: `make probe`
│       ├── llm_protection.py   # opt-in: Relay request intercepts keep the SSN out of the LLM request
│       ├── verify.py           # `make verify`
│       └── …                   # agent, app, relay_runtime, scripted model, scenarios, UI
├── tests/                  # offline pytest suite, including a simulated OpenShell denial and trace relay
└── docs/
```

## Differences from `uc1-community`

| | uc1-community | uc1-openshell |
|---|---|---|
| Where the agent runs | compose container, on the compose network | OpenShell sandbox (networking off, egress only through the supervisor) |
| How the traces reach MLflow | Relay exports to `http://mlflow:5000` with the service account | Through the OpenShell agent trace relay to the collector, which adds the service account; the agent has no route to MLflow |
| LLM credentials | `LLM_API_KEY` env var | Optional OpenShell provider; the sandbox sees only a placeholder |
| Extra tool | — | `notify_partner_crm`, blocked by policy |
| Scenarios / verify | run in a compose container | run on the laptop with `uv`; evidence pulled out with `openshell sandbox exec` / `logs` |
| Experiments | `uc1-customer-lookup-*` | `uc1-openshell-*` |
| Checks | 13 | 18 |
