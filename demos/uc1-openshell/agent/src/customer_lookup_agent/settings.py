"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    # "openai" = any OpenAI-compatible endpoint (Ollama, vLLM, NVIDIA NIM, OpenAI).
    # "scripted" = deterministic offline model for rehearsals and automated tests.
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "openai"))
    # Inside the OpenShell sandbox, the laptop is reachable as host.openshell.internal.
    llm_base_url: str = field(
        default_factory=lambda: _env("LLM_BASE_URL", "http://host.openshell.internal:11434/v1")
    )
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "qwen2.5:7b"))
    # With an OpenShell provider attached (openshell/providers/), NVIDIA_API_KEY holds an
    # opaque placeholder; the sandbox supervisor swaps in the real key on the wire.
    llm_api_key: str = field(
        default_factory=lambda: _env(
            "LLM_API_KEY", _env("NVIDIA_API_KEY", _env("OPENAI_API_KEY", "not-needed"))
        )
    )

    # "redacted" runs with the Relay pii_redaction policy; "baseline" exports raw telemetry.
    relay_mode: str = field(default_factory=lambda: _env("RELAY_MODE", "redacted"))
    relay_plugins_file: str = field(
        default_factory=lambda: _env("RELAY_PLUGINS_FILE", "/app/relay/plugins.redacted.toml")
    )

    mlflow_tracking_uri: str = field(
        default_factory=lambda: _env("MLFLOW_TRACKING_URI", "http://host.openshell.internal:5000")
    )
    # Browser-facing MLflow URL used for links in the chat UI.
    mlflow_public_uri: str = field(default_factory=lambda: _env("MLFLOW_PUBLIC_URI", "http://localhost:5000"))
    mlflow_experiment_name: str = field(
        default_factory=lambda: _env("MLFLOW_EXPERIMENT_NAME", "uc1-openshell-redacted")
    )

    tool_timeout_seconds: float = field(default_factory=lambda: float(_env("TOOL_TIMEOUT_SECONDS", "2.0")))

    # External system the agent is asked to sync records to. The OpenShell policy
    # does not allow this host, so the call is denied at the sandbox boundary.
    partner_crm_url: str = field(
        default_factory=lambda: _env("PARTNER_CRM_URL", "https://partner-crm.example.com/v1/customers/notify")
    )
    partner_crm_timeout_seconds: float = field(
        default_factory=lambda: float(_env("PARTNER_CRM_TIMEOUT_SECONDS", "5.0"))
    )


def get_settings() -> Settings:
    return Settings()
