# Use case 1 (OpenShell) demo helpers.
#
# MLflow runs in compose. The two agents (redacted + baseline) run in NVIDIA
# OpenShell sandboxes created from the same image, with the same sandbox policy.
#
# Prerequisites: openshell CLI + gateway (`openshell status`), Docker or Podman
# (the same engine the OpenShell gateway uses), and uv (for scenarios/verify/test).

-include .env
export

# Container engine: must match the OpenShell gateway's compute driver.
ENGINE ?= $(shell if docker info >/dev/null 2>&1; then echo docker; elif command -v podman >/dev/null 2>&1; then echo podman; else echo docker; fi)
COMPOSE ?= $(ENGINE) compose
OPENSHELL ?= openshell
# OpenShell 0.1.9 has no `policy lint`. The policy prover parses the policy with the
# same strict schema (unknown fields are rejected), so checking the policy against
# itself as the boundary works as a linter.
OPENSHELL_PROVER ?= $(or $(shell command -v openshell-prover 2>/dev/null),/opt/homebrew/opt/openshell/bin/openshell-prover)

# Podman needs a fully qualified local image reference.
AGENT_IMAGE ?= $(if $(filter podman,$(ENGINE)),localhost/,)uc1-openshell-agent:latest
POLICY ?= openshell/policy.yaml

REDACTED_SANDBOX ?= uc1-agent-redacted
BASELINE_SANDBOX ?= uc1-agent-baseline
REDACTED_AGENT_PORT ?= 8000
BASELINE_AGENT_PORT ?= 8001
MLFLOW_PORT ?= 5000

MLFLOW_ADMIN_PASSWORD ?= mlflow-admin-demo-password
AGENT_MLFLOW_USERNAME ?= relay-agent
AGENT_MLFLOW_PASSWORD ?= relay-agent-demo-password
# How the sandboxed agents reach MLflow (through the OpenShell supervisor).
SANDBOX_MLFLOW_URI ?= http://host.openshell.internal:$(MLFLOW_PORT)

# LLM: ollama (default, native Ollama on the laptop) | scripted | nvidia
LLM ?= ollama
OLLAMA_MODEL ?= qwen2.5:7b
NVIDIA_PROVIDER ?= uc1-nvidia
ifeq ($(LLM),scripted)
  LLM_ENV := --env LLM_PROVIDER=scripted
else ifeq ($(LLM),nvidia)
  # The API key never enters the sandbox: the provider injects a placeholder and
  # the supervisor substitutes the real key on requests to integrate.api.nvidia.com.
  LLM_ENV := --env LLM_PROVIDER=openai --env LLM_BASE_URL=https://integrate.api.nvidia.com/v1 \
             --env LLM_MODEL=$(or $(NVIDIA_MODEL),meta/llama-3.3-70b-instruct) --provider $(NVIDIA_PROVIDER)
else
  LLM_ENV := --env LLM_PROVIDER=openai \
             --env LLM_BASE_URL=$(or $(LLM_BASE_URL),http://host.openshell.internal:11434/v1) \
             --env LLM_MODEL=$(or $(LLM_MODEL),$(OLLAMA_MODEL)) \
             --env LLM_API_KEY=$(or $(LLM_API_KEY),not-needed)
endif

EVIDENCE_DIR := $(CURDIR)/telemetry
UV_RUN := cd agent && uv run --quiet

# $(call create_sandbox,<name>,<mode>,<port>)
# Note: --env values are visible to `openshell sandbox get`; the MLflow service
# account password is demo-only. See docs/product-gaps.md for the provider-based
# alternative.
define create_sandbox
	-@$(OPENSHELL) forward stop $(3) $(1) >/dev/null 2>&1
	-@$(OPENSHELL) sandbox delete $(1) >/dev/null 2>&1
	@# Deletion is asynchronous (no --wait flag in 0.1.9): wait until the name is free.
	@for i in $$(seq 1 60); do $(OPENSHELL) sandbox get $(1) >/dev/null 2>&1 || exit 0; sleep 1; done; \
	  echo "sandbox $(1) still exists after 60s"; exit 1
	$(OPENSHELL) sandbox create --name $(1) --from $(AGENT_IMAGE) --policy $(POLICY) --detach \
	  $(LLM_ENV) \
	  --env SANDBOX_NAME=$(1) \
	  --env RELAY_MODE=$(2) \
	  --env RELAY_PLUGINS_FILE=/app/relay/plugins.$(2).toml \
	  --env MLFLOW_TRACKING_URI=$(SANDBOX_MLFLOW_URI) \
	  --env MLFLOW_PUBLIC_URI=http://localhost:$(MLFLOW_PORT) \
	  --env MLFLOW_EXPERIMENT_NAME=uc1-openshell-$(2) \
	  --env MLFLOW_TRACKING_USERNAME=$(AGENT_MLFLOW_USERNAME) \
	  --env MLFLOW_TRACKING_PASSWORD=$(AGENT_MLFLOW_PASSWORD) \
	  --env TOOL_TIMEOUT_SECONDS=$(or $(TOOL_TIMEOUT_SECONDS),2.0) \
	  --env PUBLIC_REDACTED_AGENT_URL=http://localhost:$(REDACTED_AGENT_PORT) \
	  --env PUBLIC_BASELINE_AGENT_URL=http://localhost:$(BASELINE_AGENT_PORT) \
	  -- uvicorn customer_lookup_agent.app:app --host 127.0.0.1 --port $(3)
	@mkdir -p $(EVIDENCE_DIR)
	@# The detached forward inherits stdout/stderr; redirect so it does not hold the caller's pipe open.
	$(OPENSHELL) forward start $(3) $(1) -d </dev/null >$(EVIDENCE_DIR)/forward-$(1).log 2>&1
endef

# $(call wait_agent,<port>)
define wait_agent
	@printf "waiting for the agent on :$(1) "; for i in $$(seq 1 90); do \
	  if curl -fsS http://localhost:$(1)/healthz 2>/dev/null | grep -q true; then echo " ready"; exit 0; fi; \
	  printf "."; sleep 2; done; echo " timed out (see: make logs)"; exit 1
endef

.PHONY: help check infra image sandboxes up up-scripted up-ollama provider-nvidia pull-model \
        scenarios evidence verify demo probe deny-log policy-show logs term ps atof down clean test lint

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-16s %s\n", $$1, $$2}'

check: ## Check the OpenShell gateway and lint the sandbox policy
	$(OPENSHELL) status
	$(OPENSHELL_PROVER) check --boundary $(POLICY) $(POLICY)

infra: ## Start MLflow (compose) and run its one-shot bootstrap
	$(COMPOSE) up -d --build mlflow
	$(COMPOSE) run --rm mlflow-bootstrap

image: ## Build the agent sandbox image with the gateway's container engine
	$(ENGINE) build -t $(AGENT_IMAGE) -f agent/Containerfile .

sandboxes: ## (Re)create both agent sandboxes and forward their ports
	$(call create_sandbox,$(REDACTED_SANDBOX),redacted,$(REDACTED_AGENT_PORT))
	$(call create_sandbox,$(BASELINE_SANDBOX),baseline,$(BASELINE_AGENT_PORT))
	$(call wait_agent,$(REDACTED_AGENT_PORT))
	$(call wait_agent,$(BASELINE_AGENT_PORT))

up: check infra image sandboxes ## Everything: MLflow, image, both sandboxes (LLM=ollama|scripted|nvidia)
	@echo "\nChat UI:  http://localhost:$(REDACTED_AGENT_PORT)   (agent in sandbox $(REDACTED_SANDBOX))"
	@echo "MLflow:   http://localhost:$(MLFLOW_PORT)   (admin / see .env)"
	@echo "Denials:  make deny-log    Policy: make policy-show"

up-scripted: ## Same as `up`, with the deterministic scripted model (no LLM needed)
	$(MAKE) up LLM=scripted

up-ollama: ## Start Ollama in compose, pull the model (the sandbox reaches it on :11434)
	$(COMPOSE) --profile ollama up -d ollama
	$(COMPOSE) exec ollama ollama pull $(OLLAMA_MODEL)

pull-model: ## Pull the model into a natively installed Ollama
	ollama pull $(OLLAMA_MODEL)

provider-nvidia: ## Import the build.nvidia.com provider profile and create the provider (needs NVIDIA_API_KEY)
	@test -n "$$NVIDIA_API_KEY" || { echo "export NVIDIA_API_KEY first"; exit 1; }
	$(OPENSHELL) provider profile lint -f openshell/providers/nvidia-build.yaml
	-$(OPENSHELL) provider profile import -f openshell/providers/nvidia-build.yaml
	-$(OPENSHELL) provider create --name $(NVIDIA_PROVIDER) --type uc1-nvidia-build --from-existing

scenarios: ## Send the success, timeout, and blocked-egress scenarios to both agents
	$(UV_RUN) python -m customer_lookup_agent.scenarios \
	  --agent http://localhost:$(REDACTED_AGENT_PORT) --agent http://localhost:$(BASELINE_AGENT_PORT)

evidence: ## Collect sandbox evidence into ./telemetry (ATOF files, OpenShell logs, egress probe)
	@mkdir -p $(EVIDENCE_DIR)
	$(OPENSHELL) sandbox exec -n $(REDACTED_SANDBOX) -- cat /sandbox/telemetry/atof-redacted.jsonl > $(EVIDENCE_DIR)/atof-redacted.jsonl
	$(OPENSHELL) sandbox exec -n $(BASELINE_SANDBOX) -- cat /sandbox/telemetry/atof-baseline.jsonl > $(EVIDENCE_DIR)/atof-baseline.jsonl
	$(OPENSHELL) logs $(REDACTED_SANDBOX) --since 2h --source sandbox > $(EVIDENCE_DIR)/openshell-$(REDACTED_SANDBOX).log
	-$(OPENSHELL) sandbox exec -n $(REDACTED_SANDBOX) -- python -m customer_lookup_agent.egress_probe \
	  > $(EVIDENCE_DIR)/egress-probe-$(REDACTED_SANDBOX).txt
	@echo "evidence in $(EVIDENCE_DIR)"; ls -1 $(EVIDENCE_DIR)

verify: evidence ## Check the success criteria against MLflow and the sandbox evidence
	cd agent && MLFLOW_TRACKING_URI=http://localhost:$(MLFLOW_PORT) \
	  MLFLOW_TRACKING_USERNAME=admin MLFLOW_TRACKING_PASSWORD=$(MLFLOW_ADMIN_PASSWORD) \
	  EVIDENCE_DIR=$(EVIDENCE_DIR) REDACTED_SANDBOX=$(REDACTED_SANDBOX) MLFLOW_DISABLE_AGENT_HINT=1 \
	  uv run --quiet python -m customer_lookup_agent.verify

demo: scenarios verify ## Run the scenarios, then verify

probe: ## Show that a process inside the sandbox cannot reach the internet
	-$(OPENSHELL) sandbox exec -n $(REDACTED_SANDBOX) -- python -m customer_lookup_agent.egress_probe

deny-log: ## Show the connections the OpenShell policy denied (last 30 minutes)
	@$(OPENSHELL) logs $(REDACTED_SANDBOX) --since 30m --source sandbox | grep -i -E 'denied|deny' || echo "(no denials yet - run the CRM scenario)"

policy-show: ## Show the effective sandbox policy (base policy + provider rules)
	$(OPENSHELL) policy get $(REDACTED_SANDBOX) --full

logs: ## Show the agent sandbox logs (gateway + sandbox sources)
	$(OPENSHELL) logs $(REDACTED_SANDBOX) --since 30m --source all

term: ## OpenShell TUI: live sandbox activity, including action=deny events
	$(OPENSHELL) term

ps: ## Show sandboxes, forwards and compose services
	$(OPENSHELL) sandbox list
	$(OPENSHELL) forward list
	$(COMPOSE) ps

atof: evidence ## Print the redacted Relay ATOF event stream (copied out of the sandbox)
	python3 -m json.tool --json-lines $(EVIDENCE_DIR)/atof-redacted.jsonl | less

down: ## Delete the sandboxes and stop MLflow (keep MLflow data)
	-$(OPENSHELL) forward stop $(REDACTED_AGENT_PORT) $(REDACTED_SANDBOX)
	-$(OPENSHELL) forward stop $(BASELINE_AGENT_PORT) $(BASELINE_SANDBOX)
	-$(OPENSHELL) sandbox delete $(REDACTED_SANDBOX)
	-$(OPENSHELL) sandbox delete $(BASELINE_SANDBOX)
	$(COMPOSE) --profile ollama down

clean: down ## Also delete all demo data (MLflow DB, collected evidence)
	$(COMPOSE) --profile ollama down -v
	rm -rf $(EVIDENCE_DIR)

test: ## Run the offline test suite (no containers or sandbox needed; uses uv)
	cd agent && uv run --extra test pytest -q

lint: ## Lint the OpenShell policy and the provider profile (needs the openshell CLI only)
	$(OPENSHELL_PROVER) check --boundary $(POLICY) $(POLICY)
	$(OPENSHELL) provider profile lint -f openshell/providers/nvidia-build.yaml
