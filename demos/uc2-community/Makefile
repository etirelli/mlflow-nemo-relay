# Use case 2 (community) demo helpers. Works with Podman or Docker.
COMPOSE ?= $(shell if docker info >/dev/null 2>&1; then echo "docker compose"; elif command -v podman >/dev/null 2>&1; then echo "podman compose"; else echo "docker compose"; fi)

-include .env
export

MLFLOW_PORT ?= 5000
V1_AGENT_PORT ?= 8000
V2_AGENT_PORT ?= 8001
MLFLOW_ADMIN_PASSWORD ?= mlflow-admin-demo-password

.PHONY: help up up-scripted scenarios eval verify demo logs ps down clean test

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-13s %s\n", $$1, $$2}'

up: ## Build and start MLflow and both agent versions (LLM from .env)
	@test -f .env || { echo "Create .env first: cp .env.example .env (LLM endpoint, model, key)"; exit 1; }
	$(COMPOSE) up -d --build
	@echo "\nChat UI:  http://localhost:$(V1_AGENT_PORT)  (toggle v1 / v2)\nMLflow:   http://localhost:$(MLFLOW_PORT)  (admin / see .env)"

up-scripted: ## Start with the deterministic scripted model (no LLM needed)
	LLM_PROVIDER=scripted $(COMPOSE) up -d --build

scenarios: ## Send the demo scenarios to both agent versions
	$(COMPOSE) run --rm verify python -m support_agent.scenarios

eval: ## Evaluate v1 and v2 on the regression dataset (code scorers + LLM judge), log to MLflow
	cd agent && MLFLOW_TRACKING_URI=http://localhost:$(MLFLOW_PORT) \
	  MLFLOW_TRACKING_USERNAME=admin MLFLOW_TRACKING_PASSWORD=$(MLFLOW_ADMIN_PASSWORD) \
	  JUDGE_BASE_URL=$(LLM_BASE_URL) JUDGE_MODEL=$(LLM_MODEL) OPENAI_API_KEY=$(LLM_API_KEY) \
	  MLFLOW_GENAI_EVAL_MAX_WORKERS=$(or $(EVAL_WORKERS),4) MLFLOW_DISABLE_AGENT_HINT=1 \
	  uv run --quiet --extra eval python -m support_agent.evaluation \
	  --agent v1=http://localhost:$(V1_AGENT_PORT) --agent v2=http://localhost:$(V2_AGENT_PORT) \
	  $(if $(filter scripted,$(LLM_PROVIDER)),--no-judge,)

verify: ## Check the UC2 success criteria and product gaps against MLflow
	$(COMPOSE) run --rm verify

demo: scenarios eval verify ## Scenarios, evaluation, then verification

logs: ## Follow service logs
	$(COMPOSE) logs -f mlflow agent-v1 agent-v2

ps: ## Show service status
	$(COMPOSE) ps

down: ## Stop services (keep data)
	$(COMPOSE) --profile tools down

clean: ## Stop services and delete all demo data
	$(COMPOSE) --profile tools down -v

test: ## Run the offline test suite (no containers needed; uses uv)
	cd agent && uv run --extra test pytest -q
