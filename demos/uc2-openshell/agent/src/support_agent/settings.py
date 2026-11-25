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

    # The agent never talks to MLflow: its traces leave through the OpenShell agent
    # trace relay, and the collector routes them. These only build UI links.
    mlflow_public_uri: str = field(default_factory=lambda: _env("MLFLOW_PUBLIC_URI", "http://localhost:5000"))
    mlflow_experiment_name: str = field(
        default_factory=lambda: _env("MLFLOW_EXPERIMENT_NAME", "uc2-openshell-refund-agent")
    )
    mlflow_experiment_id: str = field(default_factory=lambda: _env("MLFLOW_EXPERIMENT_ID", ""))

    tool_timeout_seconds: float = field(default_factory=lambda: float(_env("TOOL_TIMEOUT_SECONDS", "2.0")))

    # The payments service (refunds, credits, ledger) runs outside the sandbox.
    # Inside an OpenShell sandbox the laptop is host.openshell.internal.
    payments_url: str = field(
        default_factory=lambda: _env("PAYMENTS_URL", "http://host.openshell.internal:8090")
    )
    payments_timeout_seconds: float = field(
        default_factory=lambda: float(_env("PAYMENTS_TIMEOUT_SECONDS", "5.0"))
    )

    # Name of the OpenShell sandbox this process runs in (exported as demo.sandbox).
    sandbox_name: str = field(default_factory=lambda: _env("SANDBOX_NAME", "local"))


def get_settings() -> Settings:
    return Settings()
