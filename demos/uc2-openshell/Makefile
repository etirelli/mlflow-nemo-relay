# Use case 2 (OpenShell) demo helpers.
#
# MLflow and the payments service run in compose. The two agent versions (v1,
# v2) run in NVIDIA OpenShell sandboxes created from the same image, with the
# same sandbox policy and the same Relay refund policy.
#
# Prerequisites: openshell CLI + gateway (`openshell status`), Podman or Docker
# (the same engine the OpenShell gateway uses), uv, and a .env with the LLM
# endpoint (cp .env.example .env).

-include .env
export

# Container engine: must match the OpenShell gateway's compute driver.
ENGINE ?= $(shell if docker info >/dev/null 2>&1; then echo docker; elif command -v podman >/dev/null 2>&1; then echo podman; else echo docker; fi)
COMPOSE ?= $(ENGINE) compose
OPENSHELL ?= openshell
# OpenShell 0.1.9 has no `policy lint`; the policy prover applies the same strict schema.
OPENSHELL_PROVER ?= $(or $(shell command -v openshell-prover 2>/dev/null),/opt/homebrew/opt/openshell/bin/openshell-prover)

# Podman needs a fully qualified local image reference.
AGENT_IMAGE ?= $(if $(filter podman,$(ENGINE)),localhost/,)uc2-openshell-agent:latest
POLICY ?= openshell/policy.yaml

V1_SANDBOX ?= uc2-agent-v1
V2_SANDBOX ?= uc2-agent-v2
V1_AGENT_PORT ?= 8000
V2_AGENT_PORT ?= 8001
MLFLOW_PORT ?= 5000
PAYMENTS_PORT ?= 8090

POLICY_VERSION ?= v1
REFUND_LIMIT ?= 500
MLFLOW_ADMIN_PASSWORD ?= mlflow-admin-demo-password
AGENT_MLFLOW_USERNAME ?= relay-agent
AGENT_MLFLOW_PASSWORD ?= relay-agent-demo-password
TRACE_EXPERIMENT := uc2-openshell-refund-agent
# How the sandboxed agents reach the laptop (through the OpenShell supervisor).
SANDBOX_HOST ?= host.openshell.internal

# LLM: provider (default; endpoint from .env, key held by an OpenShell provider) | scripted
LLM ?= $(if $(filter scripted,$(LLM_PROVIDER)),scripted,provider)
LLM_OS_PROVIDER ?= uc2-llm
ifeq ($(LLM),scripted)
  LLM_ENV := --env LLM_PROVIDER=scripted
else
  # The API key never enters the sandbox: the provider injects a placeholder in
  # LLM_API_KEY and the supervisor substitutes the real key on requests to the
  # LLM host. See openshell/providers/llm.yaml.tmpl and `make provider`.
  LLM_ENV := --env LLM_PROVIDER=openai --env LLM_BASE_URL=$(LLM_BASE_URL) --env LLM_MODEL=$(LLM_MODEL) \
             --provider $(LLM_OS_PROVIDER)
endif

EVIDENCE_DIR := $(CURDIR)/telemetry
UV_RUN := cd agent && uv run --quiet

# $(call create_sandbox,<name>,<agent version>,<port>)
# Note: --env values are visible to `openshell sandbox get`; the MLflow service
# account password is demo-only (see OSH-5 in the repo's docs/product-gaps.md).
define create_sandbox
	-@$(OPENSHELL) forward stop $(3) $(1) >/dev/null 2>&1
	-@$(OPENSHELL) sandbox delete $(1) >/dev/null 2>&1
	@# Deletion is asynchronous (no --wait flag in 0.1.9): wait until the name is free.
	@for i in $$(seq 1 60); do $(OPENSHELL) sandbox get $(1) >/dev/null 2>&1 || exit 0; sleep 1; done; \
	  echo "sandbox $(1) still exists after 60s"; exit 1
	$(OPENSHELL) sandbox create --name $(1) --from $(AGENT_IMAGE) --policy $(POLICY) --detach \
	  --no-auto-providers $(LLM_ENV) \
	  --env SANDBOX_NAME=$(1) \
	  --env AGENT_VERSION=$(2) \
	  --env POLICY_VERSION=$(POLICY_VERSION) \
	  --env REFUND_LIMIT=$(REFUND_LIMIT) \
	  --env RELAY_PLUGINS_FILE=/app/relay/plugins.toml \
	  --env PAYMENTS_URL=http://$(SANDBOX_HOST):$(PAYMENTS_PORT) \
	  --env MLFLOW_TRACKING_URI=http://$(SANDBOX_HOST):$(MLFLOW_PORT) \
	  --env MLFLOW_PUBLIC_URI=http://localhost:$(MLFLOW_PORT) \
	  --env MLFLOW_EXPERIMENT_NAME=$(TRACE_EXPERIMENT) \
	  --env MLFLOW_TRACKING_USERNAME=$(AGENT_MLFLOW_USERNAME) \
	  --env MLFLOW_TRACKING_PASSWORD=$(AGENT_MLFLOW_PASSWORD) \
	  --env TOOL_TIMEOUT_SECONDS=$(or $(TOOL_TIMEOUT_SECONDS),2.0) \
	  --env PUBLIC_V1_AGENT_URL=http://localhost:$(V1_AGENT_PORT) \
	  --env PUBLIC_V2_AGENT_URL=http://localhost:$(V2_AGENT_PORT) \
	  -- uvicorn support_agent.app:app --host 127.0.0.1 --port $(3)
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

.PHONY: help check infra image provider provider-reset sandboxes up up-scripted scenarios eval evidence verify demo \
        probe deny-log policy-show ledger logs term ps down clean test lint

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-13s %s\n", $$1, $$2}'

check: ## Check the OpenShell gateway and lint the sandbox policy
	$(OPENSHELL) status
	$(OPENSHELL_PROVER) check --boundary $(POLICY) $(POLICY)

infra: ## Start MLflow and the payments service (compose), run the MLflow bootstrap
	$(COMPOSE) up -d --build mlflow payments
	$(COMPOSE) run --rm mlflow-bootstrap

image: ## Build the agent sandbox image with the gateway's container engine
	$(ENGINE) build -t $(AGENT_IMAGE) -f agent/Containerfile .

provider: ## Register the LLM provider (endpoint + key from .env; the key never enters the sandbox)
	@test -n "$$LLM_BASE_URL" -a -n "$$LLM_API_KEY" || { echo "Set LLM_BASE_URL and LLM_API_KEY in .env"; exit 1; }
	@mkdir -p $(EVIDENCE_DIR)
	@python3 -c 'import os,sys; from urllib.parse import urlparse; u=urlparse(os.environ["LLM_BASE_URL"]); \
	  t=open("openshell/providers/llm.yaml.tmpl").read(); \
	  t=t.replace("$${LLM_HOST}",u.hostname).replace("$${LLM_PORT}",str(u.port or (443 if u.scheme=="https" else 80))); \
	  sys.stdout.write(t.replace("$${LLM_PATH_PREFIX}",u.path.rstrip("/")))' > $(EVIDENCE_DIR)/provider-llm.yaml
	@# `profile lint` rejects an id that already exists, and `profile update` needs the exported
	@# resource_version, so the profile is imported once. Changed LLM_BASE_URL: make provider-reset.
	@if $(OPENSHELL) provider profile describe uc2-llm >/dev/null 2>&1; then \
	  echo "provider profile uc2-llm already registered (after changing LLM_BASE_URL: make provider-reset)"; \
	else \
	  $(OPENSHELL) provider profile lint -f $(EVIDENCE_DIR)/provider-llm.yaml \
	  && $(OPENSHELL) provider profile import -f $(EVIDENCE_DIR)/provider-llm.yaml; fi
	@# --credential KEY reads the value from this process's environment (.env); it is not echoed.
	@$(OPENSHELL) provider get $(LLM_OS_PROVIDER) >/dev/null 2>&1 \
	  && $(OPENSHELL) provider update $(LLM_OS_PROVIDER) --credential LLM_API_KEY >/dev/null \
	  || $(OPENSHELL) provider create --name $(LLM_OS_PROVIDER) --type uc2-llm --credential LLM_API_KEY >/dev/null
	@echo "provider $(LLM_OS_PROVIDER) ready (profile: $(EVIDENCE_DIR)/provider-llm.yaml)"

provider-reset: ## Delete the LLM provider and its profile, then register them again from .env
	-$(OPENSHELL) provider delete $(LLM_OS_PROVIDER)
	-$(OPENSHELL) provider profile delete uc2-llm
	$(MAKE) provider

sandboxes: ## (Re)create both agent sandboxes and forward their ports
	$(call create_sandbox,$(V1_SANDBOX),v1,$(V1_AGENT_PORT))
	$(call create_sandbox,$(V2_SANDBOX),v2,$(V2_AGENT_PORT))
	$(call wait_agent,$(V1_AGENT_PORT))
	$(call wait_agent,$(V2_AGENT_PORT))

up: check infra image $(if $(filter scripted,$(LLM)),,provider) sandboxes ## Everything: MLflow, payments, image, provider, both sandboxes
	@echo "\nChat UI:   http://localhost:$(V1_AGENT_PORT)  (toggle v1 / v2; agents in sandboxes $(V1_SANDBOX), $(V2_SANDBOX))"
	@echo "MLflow:    http://localhost:$(MLFLOW_PORT)  (admin / see .env)"
	@echo "Payments:  http://localhost:$(PAYMENTS_PORT)/v1/ledger   Denials: make deny-log"

up-scripted: ## Same as `up`, with the deterministic scripted model (no LLM needed)
	$(MAKE) up LLM=scripted

scenarios: ## Send the demo scenarios to both agent versions
	$(UV_RUN) python -m support_agent.scenarios \
	  --agent http://localhost:$(V1_AGENT_PORT) --agent http://localhost:$(V2_AGENT_PORT)

eval: ## Evaluate v1 and v2 on the regression dataset (code scorers + LLM judge), log to MLflow
	cd agent && MLFLOW_TRACKING_URI=http://localhost:$(MLFLOW_PORT) \
	  MLFLOW_TRACKING_USERNAME=admin MLFLOW_TRACKING_PASSWORD=$(MLFLOW_ADMIN_PASSWORD) \
	  JUDGE_BASE_URL=$(LLM_BASE_URL) JUDGE_MODEL=$(LLM_MODEL) OPENAI_API_KEY="$$LLM_API_KEY" \
	  MLFLOW_GENAI_EVAL_MAX_WORKERS=$(or $(EVAL_WORKERS),4) MLFLOW_DISABLE_AGENT_HINT=1 \
	  uv run --quiet --extra eval python -m support_agent.evaluation \
	  --agent v1=http://localhost:$(V1_AGENT_PORT) --agent v2=http://localhost:$(V2_AGENT_PORT) \
	  $(if $(filter scripted,$(LLM)),--no-judge,)

evidence: ## Collect sandbox evidence into ./telemetry (ATOF files, OpenShell logs, egress probe)
	@mkdir -p $(EVIDENCE_DIR)
	$(OPENSHELL) sandbox exec -n $(V1_SANDBOX) -- cat /sandbox/telemetry/atof-v1.jsonl > $(EVIDENCE_DIR)/atof-v1.jsonl
	$(OPENSHELL) sandbox exec -n $(V2_SANDBOX) -- cat /sandbox/telemetry/atof-v2.jsonl > $(EVIDENCE_DIR)/atof-v2.jsonl
	$(OPENSHELL) logs $(V1_SANDBOX) --since 2h --source sandbox > $(EVIDENCE_DIR)/openshell-$(V1_SANDBOX).log
	$(OPENSHELL) logs $(V2_SANDBOX) --since 2h --source sandbox > $(EVIDENCE_DIR)/openshell-$(V2_SANDBOX).log
	-$(OPENSHELL) sandbox exec -n $(V2_SANDBOX) -- python -m support_agent.egress_probe \
	  > $(EVIDENCE_DIR)/egress-probe-$(V2_SANDBOX).txt
	@echo "evidence in $(EVIDENCE_DIR)"; ls -1 $(EVIDENCE_DIR)

verify: evidence ## Check the success criteria against MLflow, the payments ledger, and the sandbox evidence
	cd agent && MLFLOW_TRACKING_URI=http://localhost:$(MLFLOW_PORT) \
	  MLFLOW_TRACKING_USERNAME=admin MLFLOW_TRACKING_PASSWORD=$(MLFLOW_ADMIN_PASSWORD) \
	  EVIDENCE_DIR=$(EVIDENCE_DIR) SANDBOXES=$(V1_SANDBOX),$(V2_SANDBOX) \
	  PAYMENTS_PUBLIC_URL=http://localhost:$(PAYMENTS_PORT) MLFLOW_DISABLE_AGENT_HINT=1 \
	  uv run --quiet python -m support_agent.verify

demo: scenarios eval verify ## Scenarios, evaluation, then verification

probe: ## Show what a process inside the sandbox cannot reach (internet, credits API, ledger)
	-$(OPENSHELL) sandbox exec -n $(V1_SANDBOX) -- python -m support_agent.egress_probe

deny-log: ## Show the requests the OpenShell policy denied (last 30 minutes)
	@for s in $(V1_SANDBOX) $(V2_SANDBOX); do echo "== $$s"; \
	  $(OPENSHELL) logs $$s --since 30m --source sandbox | grep -i -E 'denied|deny' || echo "(no denials)"; done

policy-show: ## Show the effective sandbox policy (base policy + provider rules)
	$(OPENSHELL) policy get $(V1_SANDBOX) --full

ledger: ## Show the payments ledger (every money movement that actually executed)
	@curl -fsS http://localhost:$(PAYMENTS_PORT)/v1/ledger | python3 -m json.tool

logs: ## Show the v1 agent sandbox logs (gateway + sandbox sources)
	$(OPENSHELL) logs $(V1_SANDBOX) --since 30m --source all

term: ## OpenShell TUI: live sandbox activity, including action=deny events
	$(OPENSHELL) term

ps: ## Show sandboxes, forwards and compose services
	$(OPENSHELL) sandbox list
	$(OPENSHELL) forward list
	$(COMPOSE) ps

down: ## Delete the sandboxes and stop compose services (keep data)
	-$(OPENSHELL) forward stop $(V1_AGENT_PORT) $(V1_SANDBOX)
	-$(OPENSHELL) forward stop $(V2_AGENT_PORT) $(V2_SANDBOX)
	-$(OPENSHELL) sandbox delete $(V1_SANDBOX)
	-$(OPENSHELL) sandbox delete $(V2_SANDBOX)
	$(COMPOSE) down

clean: down ## Also delete all demo data (MLflow DB, payments ledger, collected evidence)
	$(COMPOSE) down -v
	rm -rf $(EVIDENCE_DIR)

test: ## Run the offline test suite (no containers or sandbox needed; uses uv)
	cd agent && uv run --extra test pytest -q

lint: ## Lint the OpenShell policy (needs the openshell CLI only)
	$(OPENSHELL_PROVER) check --boundary $(POLICY) $(POLICY)
