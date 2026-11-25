# UC2 (OpenShell): Two enforcement layers, one record in MLflow

`uc2-community`, with both agent versions running in **NVIDIA OpenShell**
sandboxes and refunds going over HTTP to a payments service outside the
sandbox. Two independent controls stand between the agent and the money:

- **NeMo Relay** decides which **tool calls** may run. Its `refund-limit-v1`
  guardrail rejects `issue_refund` above $500 before the tool runs.
- **OpenShell** decides which **network requests** the agent's process may
  make. On the payments service, it allows only `POST /v1/refunds`.

**MLflow** shows both kinds of block distinctly, in the same trace. It then
proves, on the same 12 cases, that an improved agent (v2) hits neither. Both
policies stay fixed throughout.

| Component | Version | Role |
|---|---|---|
| [NeMo Relay](https://github.com/NVIDIA/NeMo-Relay) | 0.11.2 | Tool guardrail `refund-limit-v1`, decision telemetry, PII redaction, OTLP export |
| [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) | 0.1.9 | Sandbox per agent version: L7 egress policy, filesystem and process policy, LLM credential injection, agent trace relay |
| [MLflow](https://github.com/mlflow/mlflow) | 3.17.2 | Traces with both decisions; GenAI evaluation (code scorers + LLM judge); evaluation dataset |
| [OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector-contrib) (contrib) | 0.165.0 | Receives the traces from the OpenShell relay, adds the MLflow service account and experiment, forwards to MLflow |
| LangGraph / LangChain | 1.2 / 1.4 | The agent, in two revisions |
| Any OpenAI-compatible LLM | — | Agents (through an OpenShell provider) and judge. Validated with GLM 5.3. |

**Status:** ✅ validated end to end on 2026-11-24 with GLM 5.3, OpenShell
0.1.9 and rootless Podman on an Apple M2. From a clean start:
- `make verify` passes 26/26;
- `make eval` meets the success criteria;
- `make test` passes 13 offline tests.

**Update:** since that run, traces leave through the OpenShell agent trace
relay instead of a direct export to MLflow. Validated again on 2026-11-24 with
OpenShell 0.1.9 (Docker driver) and the scripted model: `make verify` passes
26/26 (the 27th check, the LLM judge, needs an LLM), `make eval` meets the
success criteria, and `make test` passes 14 offline tests.

## What the demo shows

1. **Layer 1, Relay.** v1 attempts a $900 refund. `refund-limit-v1` rejects
   it before the tool runs, so no request leaves the process.
2. **Layer 2, OpenShell.** Asked to "put it on their account as a credit
   instead", v1 reaches for `apply_account_credit`, a tool a developer added.
   Relay's refund policy doesn't cover that tool and **allows** the call. The
   sandbox **denies** the request to `POST /v1/credits`, so it never reaches
   the payments service.
3. **Both decisions in one MLflow trace, distinctly:**

   | Shape | Meaning |
   |---|---|
   | `GUARDRAIL refund-limit-v1` with `rejected=true`, no `TOOL` span | Relay policy block |
   | `GUARDRAIL` with `allowed=true`, then a `TOOL` span with status `ERROR`: `EgressBlocked: OpenShell sandbox policy denied POST …/v1/credits (error=policy_denied; policy=payments_refunds; rule=POST /v1/credits …)` | OpenShell sandbox denial |
   | `TOOL` span with status `ERROR`: `TimeoutError …` | Ordinary tool failure |

4. **Independent evidence.** The OpenShell log records `DENIED POST
   …/v1/credits [policy:payments_refunds engine:l7]`. The payments ledger,
   read from the laptop, has no refund above $500 and no credit.
5. **Improve the agent, not the controls.** v2 knows the limit, escalates
   with `request_supervisor_approval`, and no longer has the credit tool. The
   Relay and OpenShell policies are untouched.
6. **Evaluate both versions on the same cases** (`make eval`, 12 cases,
   including two "credit instead" workarounds):

| Scorer | v1 | v2 |
|---|---|---|
| `no_prohibited_attempt` (Relay blocks + sandbox denials) | 67% | **100%** |
| `no_sandbox_denial` | 83% | **100%** |
| `task_completed` | 75% | **100%** |
| `blocked_never_executed` (ledger: nothing refused executed) | 100% | 100% |
| `within_refund_limit` | 92% | **100%** |
| `policy_compliant_reply` (LLM judge) | 36% | **100%** |

v1's `within_refund_limit` of 92% is one "split it into two $450 refunds"
case that went through. That's the per-call limit gap from `uc2-community`,
and neither layer is designed to catch it. LLM results vary between runs.
The direction is what matters.

7. **Traces leave through the OpenShell agent trace relay.** Relay exports to
   the address OpenShell injects into the sandbox (`http://192.0.0.8:4318`).
   The supervisor stamps `openshell.sandbox.id` on each trace and forwards it
   to the collector, which adds the MLflow service account and experiment.
   The sandbox has no MLflow credentials and no MLflow rule in its policy.

## Quick start

Prerequisites:
- the OpenShell CLI and gateway (`brew install openshell`, then
  `brew services start openshell`);
- the OpenShell agent trace relay, turned on once in the gateway config
  (`make gateway-config` prints the setting and where it goes);
- Podman (with `podman compose`) or Docker, matching the gateway's driver;
- uv;
- an OpenAI-compatible LLM endpoint with tool calling.

```bash
cd demos/uc2-openshell
cp .env.example .env && chmod 600 .env   # LLM_BASE_URL, LLM_MODEL, LLM_API_KEY (gitignored)
make up        # MLflow + payments (compose), agent image, LLM provider, sandboxes v1 (:8000) and v2 (:8001)
make demo      # scenarios, evaluation (v1 vs v2), evidence collection, verification
```

| URL / command | What |
|---|---|
| http://localhost:8000 | Chat UI. The toggle switches between **v1** and **v2**. Try **$900, else as a credit**. |
| http://localhost:5000 | MLflow (`admin`). `uc2-openshell-refund-agent` has the traces, `uc2-openshell-refund-agent-eval` the evaluation runs and dataset. |
| `make ledger` | The payments ledger: every money movement that actually executed |
| `make deny-log` / `make probe` | What the sandbox denied / what a process inside it can't reach |
| `make collector-logs` | The collector between the OpenShell relay and MLflow |

To rehearse without an LLM, run `make up-scripted`. The scripted v1 always
tries the credit.

## Documentation

| Doc | For |
|---|---|
| [docs/demo-script.md](docs/demo-script.md) | Presenters: a 7-minute talk track |
| [docs/architecture.md](docs/architecture.md) | The two layers, the payments service, trace shapes, the trace path through the OpenShell relay, the LLM provider |
| [docs/evaluation.md](docs/evaluation.md) | Dataset, scorers, LLM judge |
| [docs/verification.md](docs/verification.md) | `make verify` (27 checks) and the offline tests |
| [Product gaps report](../../docs/product-gaps.md) | What was validated, and findings for OpenShell, Relay and MLflow (consolidated, repo root) |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems |

## Layout

```
uc2-openshell/
├── compose.yaml              # mlflow, mlflow-bootstrap, payments, otel-collector (outside the sandboxes)
├── Makefile                  # up / provider / sandboxes / scenarios / eval / evidence / verify / demo / down / clean
├── .env.example              # LLM endpoint/model/key, policy limit, ports
├── openshell/
│   ├── policy.yaml           # sandbox policy: payments POST /v1/refunds only; no MLflow route
│   ├── gateway-agent-relay.toml  # one-time gateway setting: the agent trace relay (`make gateway-config`)
│   └── providers/llm.yaml.tmpl  # LLM provider profile (rendered from .env by `make provider`)
├── payments/                 # payments service: /v1/refunds, /v1/credits, /v1/ledger (stdlib)
├── relay/plugins.toml        # Relay telemetry: OTLP -> OpenShell agent trace relay + pii_redaction
├── otel/collector.yaml       # collector: relay -> MLflow, with the service account and experiment header
├── mlflow/                   # upstream MLflow with basic auth + bootstrap
├── agent/
│   ├── Containerfile         # OpenShell BYOC image (non-root, /sandbox workspace)
│   └── src/support_agent/
│       ├── policy.py         # RefundPolicy (Relay guardrail) + PolicyDecisionMiddleware
│       ├── tools.py          # issue_refund / apply_account_credit over HTTP; EgressBlocked handling
│       ├── agent.py          # v1 and v2 system prompts
│       ├── evaluation.py     # `make eval`
│       ├── verify.py         # `make verify`
│       ├── egress_probe.py   # run inside the sandbox: what is refused
│       └── …                 # app, refunds (per-request record), relay_runtime, scripted model, scenarios, UI
├── tests/                    # offline: both layers with a fake payments service, enforcement, redaction, trace relay
└── docs/
```
