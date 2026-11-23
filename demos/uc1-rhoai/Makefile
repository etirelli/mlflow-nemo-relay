# UC1 on Red Hat OpenShift AI: demo helpers.
#
# Prerequisites: `oc` logged in to a cluster with OpenShift AI + MLflow, uv,
# a config.env (cp config.env.example config.env) and the LLM API key Secret.

CONFIG ?= config.env
-include $(CONFIG)
export

OC ?= oc
UV_RUN := cd agent && uv run --quiet
EVIDENCE_DIR := $(CURDIR)/telemetry
PF_DIR := $(CURDIR)/.port-forward

REDACTED_EXPERIMENT ?= uc1-rhoai-redacted
BASELINE_EXPERIMENT ?= uc1-rhoai-baseline
NOT_GRANTED_EXPERIMENT ?= uc1-rhoai-not-granted
REDACTED_LOCAL_PORT ?= 8000
BASELINE_LOCAL_PORT ?= 8001

# Browser/laptop-facing MLflow URL: the OpenShift AI data science gateway, unless set in config.env.
MLFLOW_PUBLIC_URI ?= $(shell h=$$($(OC) get route data-science-gateway -n openshift-ingress \
  -o jsonpath='{.spec.host}' 2>/dev/null); [ -n "$$h" ] && echo "https://$$h/mlflow")

# The laptop talks to MLflow as the logged-in OpenShift user.
define user_mlflow_env
MLFLOW_TRACKING_URI=$(MLFLOW_PUBLIC_URI) MLFLOW_TRACKING_TOKEN=$$($(OC) whoami -t) MLFLOW_WORKSPACE=$(NAMESPACE) MLFLOW_DISABLE_AGENT_HINT=1
endef

.PHONY: help check bootstrap deploy build rollout up port-forward stop-port-forward scenarios evidence \
        verify demo logs status down clean test lint

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-18s %s\n", $$1, $$2}'

check: ## Check config.env, cluster login, namespace, LLM Secret and MLflow
	@test -f $(CONFIG) || { echo "Missing $(CONFIG): cp config.env.example config.env and edit it"; exit 1; }
	@for v in NAMESPACE LLM_BASE_URL LLM_MODEL LLM_API_KEY_SECRET; do \
	  eval "val=\$$$$v"; test -n "$$val" || { echo "$$v is not set in $(CONFIG)"; exit 1; }; done
	@echo "cluster:    $$($(OC) whoami --show-server) as $$($(OC) whoami)"
	@$(OC) get namespace $(NAMESPACE) >/dev/null 2>&1 || { echo "namespace $(NAMESPACE) missing: oc new-project $(NAMESPACE)"; exit 1; }
	@$(OC) get secret $(LLM_API_KEY_SECRET) -n $(NAMESPACE) -o jsonpath='{.data.$(or $(LLM_API_KEY_SECRET_KEY),api-key)}' 2>/dev/null | grep -q . \
	  || { echo "Secret $(LLM_API_KEY_SECRET) (key $(or $(LLM_API_KEY_SECRET_KEY),api-key)) not found in $(NAMESPACE)"; exit 1; }
	@echo "LLM:        $(LLM_MODEL) @ $(LLM_BASE_URL) (key from Secret $(LLM_API_KEY_SECRET))"
	@test -n "$(MLFLOW_PUBLIC_URI)" || { echo "Cannot find the OpenShift AI gateway; set MLFLOW_PUBLIC_URI in $(CONFIG)"; exit 1; }
	@echo "MLflow:     $(MLFLOW_PUBLIC_URI) (workspace $(NAMESPACE))"
	@$(OC) get mlflow mlflow -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null | grep -q True \
	  || { echo "MLflow is not Available in OpenShift AI"; exit 1; }

bootstrap: ## Create the demo experiments in the MLflow workspace (as you, the cluster user)
	$(UV_RUN) env $(user_mlflow_env) python -m customer_lookup_agent.bootstrap_rhoai \
	  $(REDACTED_EXPERIMENT) $(BASELINE_EXPERIMENT) $(NOT_GRANTED_EXPERIMENT)

deploy: ## Apply the OpenShift Template with the parameters from config.env
	$(OC) process -f openshift/template.yaml --param-file=$(CONFIG) --ignore-unknown-parameters \
	  -p MLFLOW_PUBLIC_URI=$(MLFLOW_PUBLIC_URI) \
	  | $(OC) apply -n $(NAMESPACE) -f -

build: ## Build the agent image in-cluster from the local sources
	@rm -rf .build-ctx && mkdir -p .build-ctx/agent
	@cp -R agent/pyproject.toml agent/src agent/Containerfile .build-ctx/agent/ && cp -R relay .build-ctx/
	$(OC) start-build uc1-agent -n $(NAMESPACE) --from-dir=.build-ctx --follow --wait
	@rm -rf .build-ctx

rollout: ## Restart both agents on the latest image and wait until they are ready
	$(OC) rollout restart deployment/uc1-agent-redacted deployment/uc1-agent-baseline -n $(NAMESPACE)
	$(OC) rollout status deployment/uc1-agent-redacted -n $(NAMESPACE) --timeout=300s
	$(OC) rollout status deployment/uc1-agent-baseline -n $(NAMESPACE) --timeout=300s

up: check bootstrap deploy build rollout ## Everything: experiments, manifests, image build, agents
	@echo "\nNext:  make port-forward   (chat UI on http://localhost:$(REDACTED_LOCAL_PORT))"
	@echo "MLflow: $(MLFLOW_PUBLIC_URI)/?workspace=$(NAMESPACE)"

port-forward: stop-port-forward ## Forward both agents to localhost (background)
	@mkdir -p $(PF_DIR)
	@nohup $(OC) port-forward -n $(NAMESPACE) svc/uc1-agent-redacted $(REDACTED_LOCAL_PORT):8000 \
	  >$(PF_DIR)/redacted.log 2>&1 </dev/null & echo $$! > $(PF_DIR)/redacted.pid
	@nohup $(OC) port-forward -n $(NAMESPACE) svc/uc1-agent-baseline $(BASELINE_LOCAL_PORT):8000 \
	  >$(PF_DIR)/baseline.log 2>&1 </dev/null & echo $$! > $(PF_DIR)/baseline.pid
	@for p in $(REDACTED_LOCAL_PORT) $(BASELINE_LOCAL_PORT); do for i in $$(seq 1 20); do \
	  curl -fsS http://localhost:$$p/healthz >/dev/null 2>&1 && break; sleep 1; done; done
	@echo "Chat UI: http://localhost:$(REDACTED_LOCAL_PORT)   baseline: http://localhost:$(BASELINE_LOCAL_PORT)"

stop-port-forward: ## Stop the background port-forwards
	@for f in $(PF_DIR)/*.pid; do [ -f "$$f" ] && kill $$(cat $$f) 2>/dev/null; rm -f $$f; done; true

scenarios: ## Send the success and timeout scenarios to both agents (needs port-forward)
	$(UV_RUN) python -m customer_lookup_agent.scenarios \
	  --agent http://localhost:$(REDACTED_LOCAL_PORT) --agent http://localhost:$(BASELINE_LOCAL_PORT)

evidence: ## Copy Relay's local ATOF files out of the agent pods into ./telemetry
	@mkdir -p $(EVIDENCE_DIR)
	$(OC) exec -n $(NAMESPACE) deploy/uc1-agent-redacted -- cat /app/telemetry/atof-redacted.jsonl > $(EVIDENCE_DIR)/atof-redacted.jsonl
	$(OC) exec -n $(NAMESPACE) deploy/uc1-agent-baseline -- cat /app/telemetry/atof-baseline.jsonl > $(EVIDENCE_DIR)/atof-baseline.jsonl

verify: evidence ## Check the success criteria against MLflow in OpenShift AI
	$(UV_RUN) env $(user_mlflow_env) EVIDENCE_DIR=$(EVIDENCE_DIR) \
	  REDACTED_EXPERIMENT=$(REDACTED_EXPERIMENT) BASELINE_EXPERIMENT=$(BASELINE_EXPERIMENT) \
	  NOT_GRANTED_EXPERIMENT=$(NOT_GRANTED_EXPERIMENT) \
	  AGENT_TOKEN=$$($(OC) create token uc1-agent -n $(NAMESPACE) --duration=10m) \
	  python -m customer_lookup_agent.verify

demo: scenarios verify ## Run the scenarios, then verify

logs: ## Follow the redacted agent's logs
	$(OC) logs -n $(NAMESPACE) deploy/uc1-agent-redacted -f

status: ## Show the demo resources
	$(OC) get deploy,pods,svc,buildconfig,imagestream -n $(NAMESPACE) -l app.kubernetes.io/part-of=uc1-rhoai

down: stop-port-forward ## Delete the demo resources (keeps the namespace, LLM Secret and MLflow experiments)
	$(OC) process -f openshift/template.yaml --param-file=$(CONFIG) --ignore-unknown-parameters \
	  -p MLFLOW_PUBLIC_URI=$(or $(MLFLOW_PUBLIC_URI),unused) \
	  | $(OC) delete -n $(NAMESPACE) --ignore-not-found -f -

clean: down ## Also delete the collected evidence
	rm -rf $(EVIDENCE_DIR) $(PF_DIR) .build-ctx

test: ## Run the offline test suite (no cluster needed; uses uv)
	cd agent && uv run --extra test pytest -q

lint: ## Validate the OpenShift Template renders with config.env (client-side)
	$(OC) process -f openshift/template.yaml --param-file=$(CONFIG) --ignore-unknown-parameters \
	  -p MLFLOW_PUBLIC_URI=$(or $(MLFLOW_PUBLIC_URI),https://example/mlflow) \
	  | $(OC) apply --dry-run=server -n $(NAMESPACE) -f -
