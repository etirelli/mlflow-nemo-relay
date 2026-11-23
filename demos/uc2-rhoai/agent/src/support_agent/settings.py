"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    # Which agent revision this process runs: "v1" (original) or "v2" (improved).
    agent_version: str = field(default_factory=lambda: _env("AGENT_VERSION", "v1"))

    # The refund policy enforced by Relay. It is the same for every agent version.
    policy_version: str = field(default_factory=lambda: _env("POLICY_VERSION", "v1"))
    refund_limit: float = field(default_factory=lambda: float(_env("REFUND_LIMIT", "500")))

    # "openai" = any OpenAI-compatible endpoint; "scripted" = deterministic offline model.
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "openai"))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", ""))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", ""))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", "not-needed"))

    relay_plugins_file: str = field(
        default_factory=lambda: _env("RELAY_PLUGINS_FILE", "/app/relay/plugins.toml")
    )

    # MLflow in OpenShift AI, as seen from inside the cluster (REST API under /mlflow).
    mlflow_tracking_uri: str = field(
        default_factory=lambda: _env(
            "MLFLOW_TRACKING_URI", "https://mlflow.redhat-ods-applications.svc:8443/mlflow"
        )
    )
    # OTLP endpoint. Empty = <scheme>://<host>/v1/traces (not under the /mlflow prefix).
    mlflow_otlp_endpoint: str = field(default_factory=lambda: _env("MLFLOW_OTLP_ENDPOINT", ""))
    # Browser-facing MLflow URL (OpenShift AI gateway), for links in the chat UI.
    mlflow_public_uri: str = field(default_factory=lambda: _env("MLFLOW_PUBLIC_URI", ""))
    # MLflow workspace = the Kubernetes namespace that holds the experiments.
    mlflow_workspace: str = field(default_factory=lambda: _env("MLFLOW_WORKSPACE", ""))
    mlflow_experiment_name: str = field(
        default_factory=lambda: _env("MLFLOW_EXPERIMENT_NAME", "uc2-rhoai-refund-agent")
    )
    # Bearer token file (the pod's rotating service account token) and the CA for MLflow TLS.
    mlflow_token_file: str = field(default_factory=lambda: _env("MLFLOW_TRACKING_TOKEN_FILE", ""))
    mlflow_ca_cert: str = field(default_factory=lambda: _env("MLFLOW_TRACKING_SERVER_CERT_PATH", ""))

    tool_timeout_seconds: float = field(default_factory=lambda: float(_env("TOOL_TIMEOUT_SECONDS", "2.0")))


def get_settings() -> Settings:
    return Settings()
