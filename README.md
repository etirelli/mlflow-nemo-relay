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
| `demos/uc1-rhoai` | UC1 | MLflow in Red Hat OpenShift AI + NeMo Relay on OpenShift | 🔜 Planned |
| `demos/uc2-community` | **UC2** Use guardrail decisions to improve agent behavior | Upstream MLflow + NeMo Relay | 🔜 Planned |
| `demos/uc3-rhoai` | **UC3** Validate guardrail changes before rollout | RHOAI + OpenShift AI Observability + NeMo Relay | 🔜 Planned |

Naming convention: `uc<N>-<stack>`, where `<stack>` is `community` (upstream
projects only, easiest to package) or `rhoai` (productized Red Hat AI).

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
└── demos/
    └── uc1-community/        # UC1 on upstream MLflow + NeMo Relay (see its README)
```

All data in these demos is synthetic. The SSNs use the never-issued `900-xx-xxxx` range.
