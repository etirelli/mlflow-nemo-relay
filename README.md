# Red Hat AI × NVIDIA NeMo Relay: joint demos

Self-contained demos for the joint use cases between **NVIDIA NeMo Relay**,
**MLflow** (the upstream project and MLflow in Red Hat OpenShift AI), and
**OpenShift AI Observability**.

Source proposal: *Red Hat AI and NVIDIA NeMo Relay Collaboration proposal: joint use cases for Relay, OpenShift AI Observability and MLflow*.
[docs/use-cases.md](docs/use-cases.md) summarizes it.

## Demo matrix

Each folder under [`demos/`](demos) is one *permutation*: one use case on one
product stack. Each folder runs on its own and has its own documentation.

| Folder | Use case | Stack | Status |
|---|---|---|---|
| [`demos/uc1-community`](demos/uc1-community) | **UC1** Observe tool calls without exposing sensitive inputs | Upstream MLflow 3.17 + NeMo Relay 0.11 (OSS) + LangGraph, on Podman/Docker Compose | ✅ Ready |
| [`demos/uc1-openshell`](demos/uc1-openshell) | **UC1**, with the agent running in an **NVIDIA OpenShell** sandbox (policy-enforced egress, blocked exfiltration shown in MLflow) | uc1-community + OpenShell 0.1.9 (Podman) | ✅ Ready (validated live 2026-11-23, 16/16) |
| [`demos/uc1-rhoai`](demos/uc1-rhoai) | **UC1** on Red Hat OpenShift AI: per-project MLflow workspace, service-account auth with least-privilege RBAC, TLS | MLflow in OpenShift AI 3.6 + NeMo Relay 0.11 on OpenShift 4.22; any OpenAI-compatible LLM (configured locally) | ✅ Ready (validated live 2026-11-23, 12/12) |
| [`demos/uc2-community`](demos/uc2-community) | **UC2** Use guardrail decisions to improve agent behavior: Relay blocks refunds above a limit, MLflow evaluates agent v1 vs v2 (code scorers + LLM judge) | Upstream MLflow 3.17 + NeMo Relay 0.11 + LangGraph, on Podman/Docker; any OpenAI-compatible LLM | ✅ Ready (validated 2026-11-23, 16/16) |
| [`demos/uc2-rhoai`](demos/uc2-rhoai) | **UC2** on Red Hat OpenShift AI: guardrail decisions in the project's MLflow workspace; v1 vs v2 evaluation (code scorers + LLM judge) as an in-cluster Job with its own service account | MLflow in OpenShift AI 3.6 + NeMo Relay 0.11 on OpenShift 4.22; any OpenAI-compatible LLM (configured locally) | ✅ Ready (validated live 2026-11-23, 16/16) |
| [`demos/uc2-openshell`](demos/uc2-openshell) | **UC2** with two enforcement layers: Relay blocks refunds above the limit; the **OpenShell** sandbox lets the agent call only `POST /v1/refunds` on the payments service, so a "credit instead" workaround is denied. MLflow shows both kinds of block distinctly, in one trace. | uc2-community + OpenShell 0.1.9 (Podman), payments service over HTTP, LLM key held by an OpenShell provider | ✅ Ready (validated live 2026-11-24, 26/26) |
| [`demos/uc3-community`](demos/uc3-community) | **UC3** Validate guardrail changes before rollout: the same agent under three Relay refund policies (production, a per-request budget, an over-strict limit); MLflow compares correct blocks, false blocks, prohibited actions allowed and task completion, Prometheus adds latency and resources under equivalent load, and a rollout gate promotes or rejects each candidate | Upstream MLflow 3.17 + NeMo Relay 0.11 + Prometheus 3.5 + LangGraph, on Podman/Docker; any OpenAI-compatible LLM | ✅ Ready (validated live 2026-11-24, 20/20) |
| [`demos/uc3-rhoai`](demos/uc3-rhoai) | **UC3** on Red Hat OpenShift AI: the three-policy comparison as an in-cluster Job in the project's MLflow workspace, with latency from **OpenShift AI Observability** (RHOAI monitoring stack) and CPU/memory from cluster monitoring; rollout gate per candidate | MLflow and OpenShift AI Observability (Tech Preview) in OpenShift AI 3.6 + NeMo Relay 0.11 on OpenShift 4.22; any OpenAI-compatible LLM (configured locally) | ✅ Ready (validated live 2026-11-24, 22/22) |

**Findings:** what the demos validated against the proposal's product gaps, and every
product finding (NeMo Relay, MLflow, MLflow in OpenShift AI, OpenShift AI Observability,
OpenShell), are consolidated in [docs/product-gaps.md](docs/product-gaps.md).

Naming convention: `uc<N>-<stack>`, where `<stack>` is `community` (upstream
projects only, easiest to package), `openshell` (community stack with the agent
in an OpenShell sandbox) or `rhoai` (productized Red Hat AI).

## Quick start (UC1)

```bash
cd demos/uc1-community
cp .env.example .env        # optional: pick your LLM endpoint
make up                     # or: make up-scripted (no LLM needed)
make demo                   # runs the scenarios and verifies the success criteria
open http://localhost:8000  # chat UI;  MLflow UI at http://localhost:5000
```

Then follow the [UC1 README](demos/uc1-community/README.md) and the
[5-minute demo script](demos/uc1-community/docs/demo-script.md).

## Repository layout

```
.
├── README.md                 # this file: demo matrix
├── docs/use-cases.md         # the three joint use cases, and how the demos map to them
├── docs/product-gaps.md      # consolidated product-gap validation and findings (all demos)
└── demos/
    ├── uc1-community/        # UC1 on upstream MLflow + NeMo Relay (see its README)
    ├── uc1-openshell/        # UC1 with the agent in an NVIDIA OpenShell sandbox
    ├── uc1-rhoai/            # UC1 on Red Hat OpenShift AI (MLflow workspaces, Kubernetes auth)
    ├── uc2-community/        # UC2: guardrail decisions -> evaluate and improve the agent
    ├── uc2-rhoai/            # UC2 on Red Hat OpenShift AI (evaluation as an in-cluster Job)
    ├── uc2-openshell/        # UC2 with a second layer: OpenShell egress policy on the payments service
    ├── uc3-community/        # UC3: compare policy versions with the agent fixed; rollout gate
    └── uc3-rhoai/            # UC3 on Red Hat OpenShift AI, with OpenShift AI Observability
```

All data in these demos is synthetic. The SSNs use the never-issued `900-xx-xxxx` range.
