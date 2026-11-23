"""NeMo Relay activation and MLflow (OpenShift AI) routing setup.

Authentication: MLflow in OpenShift AI runs the ``kubernetes-auth`` app. Every
request carries a Kubernetes bearer token, and MLflow checks it with a
SelfSubjectAccessReview against ``experiments.mlflow.kubeflow.org`` in the
workspace (namespace). The agent uses its pod's service account token, which
Kubernetes rotates. Relay's ``header_file`` sends a file's content verbatim as
the header value, so a small background thread keeps ``Bearer <token>`` in a
private file, refreshed from the rotating token.

Routing: ``X-MLFLOW-WORKSPACE`` selects the workspace and
``x-mlflow-experiment-id`` the experiment. Both come from ``header_env``.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import nemo_relay

from support_agent.settings import Settings

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")
_OPTIONAL_BEGIN = re.compile(r"^\s*#\s*begin-optional:\s*([A-Z0-9_]+)\s*$")
_OPTIONAL_END = re.compile(r"^\s*#\s*end-optional\s*$")
TOKEN_REFRESH_SECONDS = 60


def _write_private(path: Path, content: str) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.replace(tmp, path)


class BearerHeaderFile:
    """Keeps ``Bearer <token>`` in a private file, refreshed from a rotating token file."""

    def __init__(self, token_file: str, interval: float = TOKEN_REFRESH_SECONDS) -> None:
        self.token_file = Path(token_file)
        self.path = Path(tempfile.gettempdir()) / "relay-mlflow-authorization"
        self.interval = interval
        self._stop = threading.Event()

    def token(self) -> str:
        return self.token_file.read_text().strip()

    def refresh(self) -> None:
        _write_private(self.path, f"Bearer {self.token()}")

    def start(self) -> None:
        self.refresh()
        threading.Thread(target=self._loop, name="mlflow-token-refresh", daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.refresh()
            except OSError as exc:  # keep the last good header; log and retry
                log.warning("Could not refresh the MLflow bearer token: %s", exc)


def resolve_experiment_id(settings: Settings, attempts: int = 30, delay: float = 2.0) -> str:
    """Return the id of the configured MLflow experiment.

    MLflow's OTLP endpoint routes traces by experiment *id*, through the
    ``x-mlflow-experiment-id`` header, so the name is resolved here. The
    experiments are created by ``make bootstrap`` (as an admin): the agent's
    Role can read and write its own experiments but cannot create new ones.
    """
    from mlflow import MlflowClient

    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            experiment = client.get_experiment_by_name(settings.mlflow_experiment_name)
            if experiment is not None:
                return experiment.experiment_id
            last_error = RuntimeError(
                f"experiment {settings.mlflow_experiment_name!r} does not exist (run `make bootstrap`)"
            )
        except Exception as exc:  # MLflow may still be starting
            last_error = exc
        log.info("Waiting for MLflow at %s (%s)", settings.mlflow_tracking_uri, last_error)
        time.sleep(delay)
    raise RuntimeError(f"Could not resolve MLflow experiment: {last_error}")


def otlp_traces_endpoint(settings: Settings) -> str:
    """MLflow's OTLP endpoint: explicit setting, else <scheme>://<host>[:port]/v1/traces.

    The /v1/traces route is not under MLflow's ``--static-prefix`` (OpenShift AI uses
    /mlflow), so it cannot be derived by appending to the tracking URI.
    """
    if settings.mlflow_otlp_endpoint:
        return settings.mlflow_otlp_endpoint
    parsed = urlparse(settings.mlflow_tracking_uri)
    return f"{parsed.scheme}://{parsed.netloc}/v1/traces"


def configure_mlflow_routing(settings: Settings) -> str:
    """Prepare MLflow client auth and export the env vars that the Relay TOML references."""
    os.environ.setdefault("RELAY_TELEMETRY_DIR", "/app/telemetry")
    os.environ.setdefault("AGENT_VERSION", settings.agent_version)
    os.environ.setdefault("POLICY_VERSION", settings.policy_version)
    Path(os.environ["RELAY_TELEMETRY_DIR"]).mkdir(parents=True, exist_ok=True)

    if settings.mlflow_workspace:
        os.environ["MLFLOW_WORKSPACE"] = settings.mlflow_workspace  # MLflow client
    # Relay header_env needs the variable to exist; servers without workspaces ignore it.
    os.environ["MLFLOW_OTLP_WORKSPACE"] = settings.mlflow_workspace or "default"
    if settings.mlflow_ca_cert:
        os.environ["MLFLOW_TRACKING_SERVER_CERT_PATH"] = settings.mlflow_ca_cert
        os.environ["MLFLOW_OTLP_CA_CERT"] = settings.mlflow_ca_cert

    if settings.mlflow_token_file:
        header = BearerHeaderFile(settings.mlflow_token_file)
        header.start()
        os.environ["MLFLOW_OTLP_AUTH_HEADER_FILE"] = str(header.path)
        os.environ["MLFLOW_TRACKING_TOKEN"] = header.token()  # MLflow client, startup calls only
    else:
        # Fallback: basic auth (upstream MLflow), as in the community demo.
        user = os.environ.get("MLFLOW_TRACKING_USERNAME")
        password = os.environ.get("MLFLOW_TRACKING_PASSWORD")
        if not (user and password):
            raise RuntimeError(
                "Set MLFLOW_TRACKING_TOKEN_FILE (OpenShift AI) or "
                "MLFLOW_TRACKING_USERNAME/MLFLOW_TRACKING_PASSWORD (basic auth)."
            )
        path = Path(tempfile.gettempdir()) / "relay-mlflow-authorization"
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        _write_private(path, f"Basic {token}")
        os.environ["MLFLOW_OTLP_AUTH_HEADER_FILE"] = str(path)

    experiment_id = resolve_experiment_id(settings)
    parsed = urlparse(settings.mlflow_tracking_uri)
    os.environ["MLFLOW_OTLP_HOST"] = parsed.hostname or "localhost"
    os.environ["MLFLOW_OTLP_TRACES_ENDPOINT"] = otlp_traces_endpoint(settings)
    os.environ["MLFLOW_OTLP_EXPERIMENT_ID"] = experiment_id
    return experiment_id


def render_plugins_file(template_path: str) -> str:
    """Expand ${VAR} placeholders in a plugins TOML file and return the rendered path.

    Blocks between ``# begin-optional: VAR`` and ``# end-optional`` are kept
    only when VAR is set and non-empty (used for the optional TLS CA).
    """

    def expand(match: re.Match) -> str:
        name = match.group(1)
        if name not in os.environ:  # fail fast on a missing variable
            raise KeyError(f"{template_path}: environment variable {name} is not set")
        return os.environ[name]

    out_lines: list[str] = []
    skipping = False
    for line in Path(template_path).read_text().splitlines(keepends=True):
        if m := _OPTIONAL_BEGIN.match(line):
            skipping = not os.environ.get(m.group(1), "").strip()
            continue
        if _OPTIONAL_END.match(line):
            skipping = False
            continue
        if skipping:
            continue
        out_lines.append(line if line.lstrip().startswith("#") else _PLACEHOLDER.sub(expand, line))
    out = Path(tempfile.gettempdir()) / f"relay-{Path(template_path).name}"
    out.write_text("".join(out_lines))
    return str(out)


@asynccontextmanager
async def relay_activation(settings: Settings):
    """Activate the Relay plugin host for the lifetime of the application."""
    plugins_file = render_plugins_file(settings.relay_plugins_file)
    log.info("Activating NeMo Relay for agent %s with %s", settings.agent_version, plugins_file)
    async with nemo_relay.plugin.activate({}, plugins_file) as activation:
        try:
            yield activation
        finally:
            await nemo_relay.subscribers.flush_async()
