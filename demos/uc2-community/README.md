# UC2 (community): Use guardrail decisions to improve agent behavior

A support agent can issue refunds. **NVIDIA NeMo Relay** enforces a fixed
policy: support agents may refund up to $500, and anything larger needs a
supervisor. Relay blocks prohibited calls *before* they execute and records
every decision. **MLflow** shows engineers the repeated blocks, holds the
regression dataset, and compares the original agent (v1) with an improved one
(v2) on the same allowed and prohibited requests. The policy never changes,
so fewer blocks mean a better agent, not weaker protection.

| Component | Version | Role |
|---|---|---|
| [NeMo Relay](https://github.com/NVIDIA/NeMo-Relay) | 0.11.0 | Tool conditional-execution guardrail (`refund-limit-v1`), decision telemetry, PII redaction, OTLP export |
| [MLflow](https://github.com/mlflow/mlflow) | 3.17.2 | Traces with guardrail decisions; GenAI evaluation (code scorers + LLM judge); evaluation dataset |
| LangGraph / LangChain | 1.2 / 1.4 | The agent, in two revisions |
| Any OpenAI-compatible LLM | — | Agents and judge. Validated with GLM 5.3. |

**Status:** ✅ validated end to end on 2026-11-23 with GLM 5.3:
- `make verify` passes 16/16;
- `make eval` meets the UC2 success criteria;
- `make test` passes 10 offline tests.

## What the demo shows

1. **A guardrail blocks a restricted action.** Agent **v1** attempts a $900
   refund. Relay's `refund-limit-v1` guardrail rejects it before the tool
   runs. The refund ledger stays empty, and the agent explains the block
   instead of crashing.
2. **The decision reaches MLflow.** The trace has a `GUARDRAIL` span
   `refund-limit-v1` with `rejected: true` and the reason. The requested call
   is preserved (`issue_refund`, amount 900), and there is no executed
   `issue_refund` tool span. A lookup timeout, by contrast, shows up as a
   `TOOL` span with status `ERROR`, so policy rejections and tool failures
   are distinguishable.
3. **An engineer improves the agent.** Reviewing the repeated blocks, they
   write **v2**:
   - the system prompt and the `issue_refund` description explain the limit;
   - a new `request_supervisor_approval` tool gives a legitimate path.
   The Relay policy is untouched.
4. **Evaluate both versions on the same cases.** `make eval` runs MLflow GenAI
   evaluation on a 10-case regression dataset, stored in MLflow. The cases are
   allowed, boundary ($500), prohibited, "manager said it's fine" pressure,
   "split it into two refunds" circumvention, and an information question. It
   uses four code scorers plus an **LLM judge**.
5. **Success criteria.** v2 makes fewer prohibited attempts, completes
   legitimate tasks at least as often, and no blocked action ever executes in
   either version.

Live results (GLM 5.3, 2026-11-23):

| Scorer | v1 | v2 |
|---|---|---|
| `no_prohibited_attempt` | 80% | **100%** |
| `task_completed` | 80% | **100%** |
| `blocked_never_executed` | 100% | 100% |
| `within_refund_limit` | 100% | 100% |
| `policy_compliant_reply` (LLM judge) | 44% | **100%** |

The LLM responses vary from run to run, so the exact percentages vary too.
The direction is what matters.

## Quick start

Prerequisites: Podman (with `podman compose`) or Docker, uv, and an
OpenAI-compatible LLM endpoint with tool calling.

```bash
cd demos/uc2-community
cp .env.example .env          # LLM_BASE_URL, LLM_MODEL, LLM_API_KEY (gitignored)
make up                       # MLflow + agent v1 (:8000) + agent v2 (:8001)
make demo                     # scenarios, evaluation (v1 vs v2), verification
```

| URL | What |
|---|---|
| http://localhost:8000 | Chat UI. The toggle switches between **v1** and **v2**. |
| http://localhost:5000 | MLflow. Log in as `admin`. Experiment `uc2-refund-agent` has the traces, `uc2-refund-agent-eval` the evaluation runs and dataset. |

To rehearse without an LLM, run `make up-scripted`. Deterministic scripted
agents imitate v1 and v2, and `make eval` skips the judge.

## Documentation

| Doc | For |
|---|---|
| [docs/demo-script.md](docs/demo-script.md) | Presenters: a 6-minute talk track |
| [docs/architecture.md](docs/architecture.md) | Guardrail mechanics, decision telemetry, the v1 → v2 change |
| [docs/evaluation.md](docs/evaluation.md) | Dataset, scorers, LLM judge, reading the results in MLflow |
| [docs/verification.md](docs/verification.md) | `make verify` (16 checks) and the offline tests |
| [docs/product-gaps.md](docs/product-gaps.md) | The proposal's UC2 product gaps: what was validated, and findings |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems |

## Layout

```
uc2-community/
├── compose.yaml            # mlflow, mlflow-bootstrap, agent-v1, agent-v2, verify
├── Makefile                # up / up-scripted / scenarios / eval / verify / demo / down / clean / test
├── .env.example            # LLM endpoint/model/key, policy limit
├── relay/plugins.toml      # Relay telemetry: OTLP -> MLflow + pii_redaction
├── mlflow/                 # upstream MLflow with basic auth + bootstrap
├── agent/src/support_agent/
│   ├── policy.py           # RefundPolicy (Relay guardrail) + PolicyDecisionMiddleware
│   ├── tools.py            # lookup_customer, issue_refund, request_supervisor_approval (v2)
│   ├── agent.py            # v1 and v2 system prompts; middleware order
│   ├── refunds.py          # refund ledger: proves blocked refunds never ran
│   ├── evaluation.py       # `make eval`: dataset, scorers, LLM judge
│   ├── verify.py           # `make verify`
│   └── …                   # app, relay_runtime, scripted model, scenarios, UI
├── tests/                  # offline: enforcement, decision export, v2 behavior, concurrency
└── docs/
```
