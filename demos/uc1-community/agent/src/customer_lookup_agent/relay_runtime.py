"""NeMo Relay activation and MLflow routing setup."""

from __future__ import annotations

import base64
import logging
import os
import re
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import nemo_relay

from customer_lookup_agent.settings import Settings

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")


def resolve_experiment_id(settings: Settings, attempts: int = 30, delay: float = 2.0) -> str:
    """Return the id of the configured MLflow experiment, creating it if needed.

    MLflow's OTLP endpoint routes traces by experiment *id*, through the
    ``x-mlflow-experiment-id`` header. Humans think in experiment names, so we
    resolve the id here. The MLflow client reads the agent's basic-auth
    credentials from ``MLFLOW_TRACKING_USERNAME`` and ``MLFLOW_TRACKING_PASSWORD``.
    """
    from mlflow import MlflowClient

    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            experiment = client.get_experiment_by_name(settings.mlflow_experiment_name)
            if experiment is not None:
                return experiment.experiment_id
            return client.create_experiment(settings.mlflow_experiment_name)
        except Exception as exc:  # MLflow may still be starting
            last_error = exc
            log.info("Waiting for MLflow at %s (%s)", settings.mlflow_tracking_uri, exc)
            time.sleep(delay)
    raise RuntimeError(f"Could not resolve MLflow experiment: {last_error}")


def configure_mlflow_routing(settings: Settings) -> str:
    """Export the env vars that the Relay plugin TOML references."""
    experiment_id = resolve_experiment_id(settings)
    parsed = urlparse(settings.mlflow_tracking_uri)
    os.environ["MLFLOW_OTLP_HOST"] = parsed.hostname or "localhost"
    os.environ["MLFLOW_OTLP_TRACES_ENDPOINT"] = settings.mlflow_tracking_uri.rstrip("/") + "/v1/traces"
    os.environ["MLFLOW_OTLP_EXPERIMENT_ID"] = experiment_id
    user = os.environ.get("MLFLOW_TRACKING_USERNAME")
    password = os.environ.get("MLFLOW_TRACKING_PASSWORD")
    if user and password:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        os.environ["MLFLOW_OTLP_AUTHORIZATION"] = f"Basic {token}"
    else:
        raise RuntimeError(
            "MLFLOW_TRACKING_USERNAME and MLFLOW_TRACKING_PASSWORD are required: "
            "the demo MLflow server runs with basic authentication."
        )
    os.environ.setdefault("RELAY_TELEMETRY_DIR", "/app/telemetry")
    Path(os.environ["RELAY_TELEMETRY_DIR"]).mkdir(parents=True, exist_ok=True)
    return experiment_id


def render_plugins_file(template_path: str) -> str:
    """Expand ${VAR} placeholders in a plugins TOML file and return the rendered path."""

    def expand(match: re.Match) -> str:
        name = match.group(1)
        if name not in os.environ:  # fail fast on a missing variable
            raise KeyError(f"{template_path}: environment variable {name} is not set")
        return os.environ[name]

    lines = Path(template_path).read_text().splitlines(keepends=True)
    rendered = "".join(
        line if line.lstrip().startswith("#") else _PLACEHOLDER.sub(expand, line) for line in lines
    )
    out = Path(tempfile.gettempdir()) / f"relay-{Path(template_path).name}"
    out.write_text(rendered)
    return str(out)


@asynccontextmanager
async def relay_activation(settings: Settings):
    """Activate the Relay plugin host for the lifetime of the application."""
    plugins_file = render_plugins_file(settings.relay_plugins_file)
    log.info("Activating NeMo Relay (%s mode) with %s", settings.relay_mode, plugins_file)
    async with nemo_relay.plugin.activate({}, plugins_file) as activation:
        try:
            yield activation
        finally:
            await nemo_relay.subscribers.flush_async()
