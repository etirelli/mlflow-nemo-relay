"""Runtime settings, read from environment variables.

Nothing cluster-specific is hard-coded here. On OpenShift AI, the values come
from the OpenShift Template parameters in ``config.env`` (see the Makefile).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    # "openai" = any OpenAI-compatible endpoint (EnMaaS, MaaS, vLLM, NIM, OpenAI, ...).
    # "scripted" = deterministic offline model for rehearsals and automated tests.
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "openai"))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", ""))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", ""))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", "not-needed"))

    # "redacted" runs with the Relay pii_redaction policy; "baseline" exports raw telemetry.
    relay_mode: str = field(default_factory=lambda: _env("RELAY_MODE", "redacted"))
    relay_plugins_file: str = field(
        default_factory=lambda: _env("RELAY_PLUGINS_FILE", "/app/relay/plugins.redacted.toml")
    )

    # MLflow in OpenShift AI, as seen from inside the cluster (includes the /mlflow prefix).
    mlflow_tracking_uri: str = field(
        default_factory=lambda: _env(
            "MLFLOW_TRACKING_URI", "https://mlflow.redhat-ods-applications.svc:8443/mlflow"
        )
    )
    # OTLP trace endpoint. Empty = derived from the tracking URI's scheme and host plus
    # /v1/traces. On OpenShift AI the REST API is served under the /mlflow static prefix
    # but the OTLP route is not (https://<svc>:8443/v1/traces).
    mlflow_otlp_endpoint: str = field(default_factory=lambda: _env("MLFLOW_OTLP_ENDPOINT", ""))
    # Browser-facing MLflow URL used for links in the chat UI.
    mlflow_public_uri: str = field(default_factory=lambda: _env("MLFLOW_PUBLIC_URI", ""))
    # MLflow workspace = the Kubernetes namespace that holds the experiments.
    mlflow_workspace: str = field(default_factory=lambda: _env("MLFLOW_WORKSPACE", ""))
    mlflow_experiment_name: str = field(
        default_factory=lambda: _env("MLFLOW_EXPERIMENT_NAME", "uc1-rhoai-redacted")
    )
    # Bearer token file, e.g. the pod's auto-rotated service account token.
    mlflow_token_file: str = field(default_factory=lambda: _env("MLFLOW_TRACKING_TOKEN_FILE", ""))
    # CA bundle that signs the MLflow server certificate (OpenShift service CA).
    mlflow_ca_cert: str = field(default_factory=lambda: _env("MLFLOW_TRACKING_SERVER_CERT_PATH", ""))

    tool_timeout_seconds: float = field(default_factory=lambda: float(_env("TOOL_TIMEOUT_SECONDS", "2.0")))


def get_settings() -> Settings:
    return Settings()
