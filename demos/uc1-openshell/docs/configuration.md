# Configuration

Every setting has a working default. Override settings in `.env`, which you
create by copying [`.env.example`](../.env.example), or on the `make` command
line. The Makefile passes agent settings into the sandboxes with
`openshell sandbox create --env`.

## LLM backends

Select the backend with `make up LLM=<backend>`. The model must support
**tool calling**.

| `LLM=` | What happens | Sandbox egress |
|---|---|---|
| `ollama` (default) | `LLM_BASE_URL=http://host.openshell.internal:11434/v1`, `LLM_MODEL=qwen2.5:7b` (on a 16 GB laptop, set `LLM_MODEL=qwen2.5:0.5b` in `.env`; validated live) | `local_llm` rule in `policy.yaml`: `POST /v1/chat/completions`, `GET /v1/models` |
| `scripted` | Deterministic stand-in that still emits real Relay LLM spans | none needed |
| `nvidia` | `https://integrate.api.nvidia.com/v1`, `NVIDIA_MODEL` (default `meta/llama-3.3-70b-instruct`), `--provider uc1-nvidia` | Contributed by the provider profile; the key is injected by the supervisor |

Ollama in compose (`make up-ollama`) publishes port 11434 on the laptop, so
the same `ollama` setting works.

### Using build.nvidia.com without giving the sandbox the key

```bash
export NVIDIA_API_KEY=nvapi-...     # laptop shell only; never in .env or the image
make provider-nvidia                # lint + import openshell/providers/nvidia-build.yaml, create provider
make up LLM=nvidia
make policy-show                    # the provider's endpoint rule shows up in the effective policy
```

Inside the sandbox, `NVIDIA_API_KEY` holds a placeholder of the form
`openshell:resolve:env:NVIDIA_API_KEY`. The agent sends it as a bearer token
(the agent's `settings.py` falls back from `LLM_API_KEY` to
`NVIDIA_API_KEY`). The supervisor replaces it with the real key only for
`integrate.api.nvidia.com:443`, and only for `/usr/local/bin/python3.12`.

### Another OpenAI-compatible endpoint

Set `LLM_BASE_URL` and `LLM_MODEL`, **and** allow the destination. You can add
a rule to `openshell/policy.yaml`, or, if the endpoint needs a key, write a
provider profile like `nvidia-build.yaml`. Without that, the sandbox denies
the connection. `make deny-log` shows it.

> **Note:** with a hosted LLM, the *prompt* that contains the SSN is sent to
> the provider. That is real execution. Relay redaction applies to telemetry,
> and the OpenShell policy decides *whether* the provider is reachable, not
> what the prompt contains.

## The OpenShell sandbox policy

[`openshell/policy.yaml`](../openshell/policy.yaml) is explained rule by rule
in [architecture.md](architecture.md#policy-rule-by-rule).

| Section | Takes effect | Change it with |
|---|---|---|
| `filesystem_policy`, `landlock`, `process` | At sandbox start | Edit, then `make sandboxes` |
| `network_policies` | Live | `openshell policy set <sandbox> --policy openshell/policy.yaml --wait`, or incrementally with `openshell policy update` |

Useful commands:

```bash
make lint                                       # offline schema check (openshell-prover; 0.1.9 has no `policy lint`)
make policy-show                                # effective policy (base + provider rules)
openshell policy list uc1-agent-redacted        # revision history
make deny-log                                   # what was denied, by which binary
```

Things to know:
- **`enforcement` defaults to `audit`.** Audit logs violations but allows the
  request. Every endpoint here sets `enforcement: enforce` explicitly.
- **Binary paths must be real paths, not symlinks.** In `python:3.12-slim`
  the interpreter is `/usr/local/bin/python3.12`. If you change the base
  image, update the policy and the provider profile.
- **Loopback and link-local destinations are never allowed outbound.** Use
  `host.openshell.internal` for services on the laptop.

## Environment variables

### Agent (set per sandbox by the Makefile)

| Variable | Default | Meaning |
|---|---|---|
| `SANDBOX_NAME` | sandbox name | Shown in the UI and API, and exported as the `demo.sandbox` span attribute and resource attribute |
| `LLM_PROVIDER` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | see above | OpenAI-compatible LLM settings |
| `TOOL_TIMEOUT_SECONDS` | `2.0` | Lookup timeout. The "legacy shard" customer takes 30 s. |
| `PARTNER_CRM_URL` | `https://partner-crm.example.com/v1/customers/notify` | Where `notify_partner_crm` posts. Not allowed by the policy. |
| `RELAY_MODE` / `RELAY_PLUGINS_FILE` | per sandbox | `redacted` / `baseline` and the matching Relay TOML |
| `MLFLOW_TRACKING_URI` | `http://host.openshell.internal:5000` | MLflow as seen from inside the sandbox. The OTLP endpoint is `<uri>/v1/traces`. |
| `MLFLOW_PUBLIC_URI` | `http://localhost:5000` | Browser-facing MLflow URL, used for links |
| `MLFLOW_EXPERIMENT_NAME` | `uc1-openshell-<mode>` | Resolved to an id at startup |
| `MLFLOW_TRACKING_USERNAME` / `_PASSWORD` | `relay-agent` / demo password | MLflow service account (see the note below) |
| `RELAY_TELEMETRY_DIR` | `/sandbox/telemetry` | Relay ATOF file sink. `make evidence` copies it out. |

> **Note on `--env`:** OpenShell treats `--env` values as non-secret
> configuration. The MLflow service-account password is demo-only. See
> [product-gaps.md](product-gaps.md) for the options to remove it from the
> sandbox.

### Makefile / `.env`

| Variable | Default |
|---|---|
| `ENGINE` | auto: `docker` if reachable, otherwise `podman`. Must match the gateway's compute driver. |
| `OPENSHELL` | `openshell` |
| `AGENT_IMAGE` | `uc1-openshell-agent:latest` (`localhost/…` for Podman) |
| `POLICY` | `openshell/policy.yaml` |
| `REDACTED_SANDBOX` / `BASELINE_SANDBOX` | `uc1-agent-redacted` / `uc1-agent-baseline` |
| `REDACTED_AGENT_PORT` / `BASELINE_AGENT_PORT` / `MLFLOW_PORT` | `8000` / `8001` / `5000` |
| `SANDBOX_MLFLOW_URI` | `http://host.openshell.internal:$(MLFLOW_PORT)` |
| `MLFLOW_ADMIN_PASSWORD`, `MLFLOW_SECRET_KEY`, `AGENT_MLFLOW_USERNAME`, `AGENT_MLFLOW_PASSWORD` | demo values, as in `uc1-community` |

## The Relay policy files

These are the same as in `uc1-community`. See that demo's
[configuration.md](../../uc1-community/docs/configuration.md#the-relay-policy-files)
for the field-level and regex profiles and the variations to try. The only
differences are the resource attributes:

```toml
[components.config.opentelemetry.endpoints.resource_attributes]
"demo.use_case" = "uc1"
"demo.relay_mode" = "redacted"
"demo.runtime" = "openshell"
"demo.sandbox" = "${SANDBOX_NAME}"
```

## Running without OpenShell

The image and the code still run outside a sandbox, which is useful for
debugging. Run the agent with `uvicorn` and point `MLFLOW_TRACKING_URI` at
`http://localhost:5000`. `notify_partner_crm` then fails with a DNS error
instead of a policy denial. It is still reported as `EgressBlocked`, but
`make deny-log` has nothing to show.

```bash
cd agent
uv run --extra test pytest -q    # offline suite: real Relay policy, in-process OTLP receiver,
                                 # simulated OpenShell policy_denied response
```
