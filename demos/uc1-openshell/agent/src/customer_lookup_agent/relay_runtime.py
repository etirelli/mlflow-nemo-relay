"""NeMo Relay activation, with traces leaving the sandbox through the OpenShell agent trace relay."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import nemo_relay

from customer_lookup_agent.settings import Settings

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")


def configure_relay_export(settings: Settings) -> str:
    """Check that the OpenShell agent trace relay is on; export the TOML variables.

    With ``[openshell.gateway.otlp.agent]`` enabled on the gateway, OpenShell sets
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` in every sandbox process, and the Relay policy file
    exports there. The supervisor accepts OTLP at that address, stamps
    ``openshell.sandbox.id`` on each resource, and forwards the traces to the demo's
    collector, which holds the MLflow credentials and routes each trace to the
    experiment of its Relay mode. The sandbox needs no MLflow credentials and no
    network route to MLflow.

    ``make sandboxes`` also sets ``OTEL_TRACES_EXPORTER=none`` (and the logs and metrics
    equivalents): with that endpoint set, Relay would otherwise add its automatic
    exporter and export every span a second time.

    Returns the MLflow experiment id, which is used only for UI links.
    """
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        raise RuntimeError(
            "OTEL_EXPORTER_OTLP_ENDPOINT is not set, so the OpenShell agent trace relay is off. "
            "Enable it on the gateway (make gateway-config), then recreate the sandbox."
        )
    os.environ.setdefault("RELAY_TELEMETRY_DIR", "/sandbox/telemetry")
    os.environ.setdefault("SANDBOX_NAME", "none")
    Path(os.environ["RELAY_TELEMETRY_DIR"]).mkdir(parents=True, exist_ok=True)
    return settings.mlflow_experiment_id


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
