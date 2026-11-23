# UC2 on Red Hat OpenShift AI: demo helpers.
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

TRACE_EXPERIMENT ?= uc2-rhoai-refund-agent
EVAL_EXPERIMENT ?= uc2-rhoai-refund-agent-eval
NOT_GRANTED_EXPERIMENT ?= uc2-rhoai-not-granted
V1_LOCAL_PORT ?= 8000
V2_LOCAL_PORT ?= 8001

MLFLOW_PUBLIC_URI ?= $(shell h=$$($(OC) get route data-science-gateway -n openshift-ingress \
  -o jsonpath='{.spec.host}' 2>/dev/null); [ -n "$$h" ] && echo "https://$$h/mlflow")

define user_mlflow_env
MLFLOW_TRACKING_URI=$(MLFLOW_PUBLIC_URI) MLFLOW_TRACKING_TOKEN=$$($(OC) whoami -t) MLFLOW_WORKSPACE=$(NAMESPACE) MLFLOW_DISABLE_AGENT_HINT=1
endef

TEMPLATE_ARGS := --param-file=$(CONFIG) --ignore-unknown-parameters -p MLFLOW_PUBLIC_URI=$(or $(MLFLOW_PUBLIC_URI),unused)

.PHONY: help check bootstrap deploy build rollout up port-forward stop-port-forward scenarios eval \
        evidence verify demo logs status down clean test lint

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
	@echo "policy:     refund-limit-$(or $(POLICY_VERSION),v1), limit USD $(or $(REFUND_LIMIT),500)"
	@test -n "$(MLFLOW_PUBLIC_URI)" || { echo "Cannot find the OpenShift AI gateway; set MLFLOW_PUBLIC_URI in $(CONFIG)"; exit 1; }
	@echo "MLflow:     $(MLFLOW_PUBLIC_URI) (workspace $(NAMESPACE))"
	@$(OC) get mlflow mlflow -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null | grep -q True \
	  || { echo "MLflow is not Available in OpenShift AI"; exit 1; }

bootstrap: ## Create the trace, evaluation and not-granted experiments (as you, the cluster user)
	$(UV_RUN) env $(user_mlflow_env) python -m support_agent.bootstrap_rhoai \
	  $(TRACE_EXPERIMENT) $(EVAL_EXPERIMENT) $(NOT_GRANTED_EXPERIMENT)

deploy: ## Apply the OpenShift Template with the parameters from config.env
	$(OC) process -f openshift/template.yaml $(TEMPLATE_ARGS) | $(OC) apply -n $(NAMESPACE) -f -

build: ## Build the agent image in-cluster from the local sources
	@rm -rf .build-ctx && mkdir -p .build-ctx/agent
	@cp -R agent/pyproject.toml agent/src agent/Containerfile .build-ctx/agent/ && cp -R relay .build-ctx/
	$(OC) start-build uc2-agent -n $(NAMESPACE) --from-dir=.build-ctx --follow --wait
	@rm -rf .build-ctx

rollout: ## Restart both agents on the latest image and wait until they are ready
	$(OC) rollout restart deployment/uc2-agent-v1 deployment/uc2-agent-v2 -n $(NAMESPACE)
	$(OC) rollout status deployment/uc2-agent-v1 -n $(NAMESPACE) --timeout=300s
	$(OC) rollout status deployment/uc2-agent-v2 -n $(NAMESPACE) --timeout=300s

up: check bootstrap deploy build rollout ## Everything: experiments, manifests, image build, agents
	@echo "\nNext:  make port-forward   (chat UI on http://localhost:$(V1_LOCAL_PORT), v1/v2 toggle)"
	@echo "MLflow: $(MLFLOW_PUBLIC_URI)/?workspace=$(NAMESPACE)"

port-forward: stop-port-forward ## Forward both agents to localhost (background)
	@mkdir -p $(PF_DIR)
	@nohup $(OC) port-forward -n $(NAMESPACE) svc/uc2-agent-v1 $(V1_LOCAL_PORT):8000 \
	  >$(PF_DIR)/v1.log 2>&1 </dev/null & echo $$! > $(PF_DIR)/v1.pid
	@nohup $(OC) port-forward -n $(NAMESPACE) svc/uc2-agent-v2 $(V2_LOCAL_PORT):8000 \
	  >$(PF_DIR)/v2.log 2>&1 </dev/null & echo $$! > $(PF_DIR)/v2.pid
	@for p in $(V1_LOCAL_PORT) $(V2_LOCAL_PORT); do for i in $$(seq 1 20); do \
	  curl -fsS http://localhost:$$p/healthz >/dev/null 2>&1 && break; sleep 1; done; done
	@echo "Chat UI: http://localhost:$(V1_LOCAL_PORT)   (v2 on http://localhost:$(V2_LOCAL_PORT))"

stop-port-forward: ## Stop the background port-forwards
	@for f in $(PF_DIR)/*.pid; do [ -f "$$f" ] && kill $$(cat $$f) 2>/dev/null; rm -f $$f; done; true

scenarios: ## Send the demo scenarios to both agent versions (needs port-forward)
	$(UV_RUN) python -m support_agent.scenarios \
	  --agent http://localhost:$(V1_LOCAL_PORT) --agent http://localhost:$(V2_LOCAL_PORT)

eval: ## Evaluate v1 vs v2 as an in-cluster Job (code scorers + LLM judge), logs to MLflow
	@run=$$(date +%Y%m%d%H%M%S); \
	$(OC) process -f openshift/eval-job.yaml --param-file=$(CONFIG) --ignore-unknown-parameters \
	  -p RUN_ID=$$run -p EVAL_ARGS="$(if $(filter scripted,$(LLM_PROVIDER)),--no-judge,)" \
	  | $(OC) create -n $(NAMESPACE) -f - && \
	echo "waiting for job uc2-eval-$$run ..." && \
	$(OC) wait -n $(NAMESPACE) --for=condition=Ready pod -l job-name=uc2-eval-$$run --timeout=300s >/dev/null 2>&1; \
	$(OC) logs -n $(NAMESPACE) -f job/uc2-eval-$$run | grep -v -E "it/s\]|Evaluating:"; \
	$(OC) wait -n $(NAMESPACE) --for=condition=Complete job/uc2-eval-$$run --timeout=60s >/dev/null 2>&1 \
	  && echo "job uc2-eval-$$run: Complete" || { echo "job uc2-eval-$$run: FAILED"; exit 1; }

evidence: ## Copy Relay's local ATOF files out of the agent pods into ./telemetry
	@mkdir -p $(EVIDENCE_DIR)
	$(OC) exec -n $(NAMESPACE) deploy/uc2-agent-v1 -- cat /app/telemetry/atof-v1.jsonl > $(EVIDENCE_DIR)/atof-v1.jsonl
	$(OC) exec -n $(NAMESPACE) deploy/uc2-agent-v2 -- cat /app/telemetry/atof-v2.jsonl > $(EVIDENCE_DIR)/atof-v2.jsonl

verify: evidence ## Check the UC2 success criteria and product gaps against MLflow in OpenShift AI
	$(UV_RUN) env $(user_mlflow_env) EVIDENCE_DIR=$(EVIDENCE_DIR) \
	  TRACE_EXPERIMENT=$(TRACE_EXPERIMENT) EVAL_EXPERIMENT=$(EVAL_EXPERIMENT) \
	  NOT_GRANTED_EXPERIMENT=$(NOT_GRANTED_EXPERIMENT) \
	  AGENT_TOKEN=$$($(OC) create token uc2-agent -n $(NAMESPACE) --duration=10m) \
	  python -m support_agent.verify

demo: scenarios eval verify ## Scenarios, in-cluster evaluation, then verification

logs: ## Follow agent v1's logs
	$(OC) logs -n $(NAMESPACE) deploy/uc2-agent-v1 -f

status: ## Show the demo resources
	$(OC) get deploy,pods,svc,jobs,buildconfig,imagestream -n $(NAMESPACE) -l app.kubernetes.io/part-of=uc2-rhoai

down: stop-port-forward ## Delete the demo resources (keeps namespace, LLM Secret, MLflow experiments)
	$(OC) delete jobs -n $(NAMESPACE) -l app=uc2-eval --ignore-not-found
	$(OC) process -f openshift/template.yaml $(TEMPLATE_ARGS) | $(OC) delete -n $(NAMESPACE) --ignore-not-found -f -

clean: down ## Also delete the collected evidence
	rm -rf $(EVIDENCE_DIR) $(PF_DIR) .build-ctx

test: ## Run the offline test suite (no cluster needed; uses uv)
	cd agent && uv run --extra test pytest -q

lint: ## Server-side dry run of the OpenShift Template with config.env
	$(OC) process -f openshift/template.yaml $(TEMPLATE_ARGS) | $(OC) apply --dry-run=server -n $(NAMESPACE) -f -
