# Use case 3 (community) demo helpers. Works with Podman or Docker.
#
# Same agent, three refund policy versions (one service each), Prometheus for
# latency and resources, MLflow for decisions, evaluation and the rollout gate.
COMPOSE ?= $(shell if docker info >/dev/null 2>&1; then echo "docker compose"; elif command -v podman >/dev/null 2>&1; then echo "podman compose"; else echo "docker compose"; fi)

-include .env
export

MLFLOW_PORT ?= 5000
POLICY_V1_PORT ?= 8000
POLICY_V2_PORT ?= 8001
POLICY_V3_PORT ?= 8002
PROMETHEUS_PORT ?= 9090
MLFLOW_ADMIN_PASSWORD ?= mlflow-admin-demo-password
LOAD_ROUNDS ?= 1
EVAL_WORKERS ?= 4

.PHONY: help up up-scripted scenarios eval verify demo logs ps down clean test

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-13s %s\n", $$1, $$2}'

up: ## Build and start MLflow, Prometheus and the agent under policies v1, v2, v3 (LLM from .env)
	@test -f .env || { echo "Create .env first: cp .env.example .env (LLM endpoint, model, key)"; exit 1; }
	$(COMPOSE) up -d --build
	@echo "\nChat UI:     http://localhost:$(POLICY_V1_PORT)  (toggle policy v1 / v2 / v3)"
	@echo "MLflow:      http://localhost:$(MLFLOW_PORT)  (admin / see .env)"
	@echo "Prometheus:  http://localhost:$(PROMETHEUS_PORT)"

up-scripted: ## Start with the deterministic scripted model (no LLM needed)
	LLM_PROVIDER=scripted $(COMPOSE) up -d --build

scenarios: ## Send the demo scenarios to the agent under each policy
	$(COMPOSE) run --rm verify python -m support_agent.scenarios

eval: ## Compare the policies: labeled cases + equivalent load, metrics from Prometheus, rollout gate in MLflow
	cd agent && MLFLOW_TRACKING_URI=http://localhost:$(MLFLOW_PORT) \
	  MLFLOW_TRACKING_USERNAME=admin MLFLOW_TRACKING_PASSWORD=$(MLFLOW_ADMIN_PASSWORD) \
	  JUDGE_BASE_URL=$(LLM_BASE_URL) JUDGE_MODEL=$(LLM_MODEL) OPENAI_API_KEY="$$LLM_API_KEY" \
	  PROMETHEUS_URL=http://localhost:$(PROMETHEUS_PORT) \
	  MLFLOW_GENAI_EVAL_MAX_WORKERS=$(EVAL_WORKERS) MLFLOW_DISABLE_AGENT_HINT=1 \
	  uv run --quiet --extra eval python -m support_agent.evaluation \
	  --policy v1=http://localhost:$(POLICY_V1_PORT) --policy v2=http://localhost:$(POLICY_V2_PORT) \
	  --policy v3=http://localhost:$(POLICY_V3_PORT) --load-rounds $(LOAD_ROUNDS) \
	  $(if $(filter scripted,$(LLM_PROVIDER)),--no-judge,)

verify: ## Check the UC3 success criteria against MLflow and Prometheus
	$(COMPOSE) run --rm verify

demo: scenarios eval verify ## Scenarios, policy comparison, then verification

logs: ## Follow service logs
	$(COMPOSE) logs -f mlflow agent-policy-v1 agent-policy-v2 agent-policy-v3

ps: ## Show service status
	$(COMPOSE) ps

down: ## Stop services (keep data)
	$(COMPOSE) --profile tools down

clean: ## Stop services and delete all demo data
	$(COMPOSE) --profile tools down -v

test: ## Run the offline test suite (no containers needed; uses uv)
	cd agent && uv run --extra test pytest -q
