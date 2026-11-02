# Use case 1 (community) demo helpers. Works with Podman or Docker.
# Uses whichever runtime is reachable (Docker/colima first, then Podman). Override with
# `make up COMPOSE="podman compose"`.
COMPOSE ?= $(shell if docker info >/dev/null 2>&1; then echo "docker compose"; elif command -v podman >/dev/null 2>&1; then echo "podman compose"; else echo "docker compose"; fi)
OLLAMA_MODEL ?= qwen2.5:7b

.PHONY: help up up-scripted up-ollama pull-model scenarios verify demo logs ps atof down clean test

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-13s %s\n", $$1, $$2}'

up: ## Build and start MLflow and both agents (LLM from .env)
	$(COMPOSE) up -d --build
	@echo "\nChat UI:  http://localhost:8000\nMLflow:   http://localhost:5000  (admin / see .env)"

up-scripted: ## Start with the deterministic scripted model (no LLM needed)
	LLM_PROVIDER=scripted $(COMPOSE) up -d --build

up-ollama: ## Start with Ollama inside compose and pull the model
	LLM_BASE_URL=http://ollama:11434/v1 $(COMPOSE) --profile ollama up -d --build
	$(COMPOSE) exec ollama ollama pull $(OLLAMA_MODEL)

pull-model: ## Pull the model into a natively installed Ollama
	ollama pull $(OLLAMA_MODEL)

scenarios: ## Send the success and timeout scenarios to both agents
	$(COMPOSE) run --rm verify python -m customer_lookup_agent.scenarios

verify: ## Check the success criteria against what MLflow stored
	$(COMPOSE) run --rm verify

demo: scenarios verify ## Run the scenarios, then verify

logs: ## Follow service logs
	$(COMPOSE) logs -f mlflow agent-redacted agent-baseline

ps: ## Show service status
	$(COMPOSE) ps

atof: ## Print the redacted Relay ATOF event stream (local copy of the export)
	$(COMPOSE) exec agent-redacted sh -c 'cat /app/telemetry/atof-redacted.jsonl' | python3 -m json.tool --json-lines | less

down: ## Stop services (keep data)
	$(COMPOSE) --profile tools --profile ollama down

clean: ## Stop services and delete all demo data (MLflow DB, telemetry)
	$(COMPOSE) --profile tools --profile ollama down -v

test: ## Run the offline test suite (no containers needed; uses uv)
	cd agent && uv run --extra test pytest -q
