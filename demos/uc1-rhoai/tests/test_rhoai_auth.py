"""OpenShift AI specifics: rotating service account token, optional TLS block."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from conftest import plugins_file
from customer_lookup_agent.relay_runtime import BearerHeaderFile, render_plugins_file


def test_bearer_header_file_follows_token_rotation(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    token = tmp_path / "token"
    token.write_text("first-token\n")
    header = BearerHeaderFile(str(token), interval=3600)
    header.refresh()
    assert header.path.read_text() == "Bearer first-token"
    # The header file holds a credential: owner-only permissions.
    assert stat.S_IMODE(os.stat(header.path).st_mode) == 0o600

    token.write_text("rotated-token")  # kubelet rotates the projected token
    header.refresh()
    assert header.path.read_text() == "Bearer rotated-token"


def test_tls_block_is_optional(otlp_receiver, monkeypatch, tmp_path):
    # Without a CA (offline tests, plain-HTTP loopback receiver): no [tls] table.
    rendered = Path(render_plugins_file(plugins_file("redacted"))).read_text()
    assert "endpoints.tls" not in rendered

    # On OpenShift AI: the service CA is trusted explicitly.
    ca = tmp_path / "service-ca.crt"
    ca.write_text("dummy")
    monkeypatch.setenv("MLFLOW_OTLP_CA_CERT", str(ca))
    rendered = Path(render_plugins_file(plugins_file("redacted"))).read_text()
    assert "[components.config.opentelemetry.endpoints.tls]" in rendered
    assert f'certificate = "{ca}"' in rendered


def test_otlp_endpoint_is_not_under_the_static_prefix(monkeypatch):
    from dataclasses import replace

    from customer_lookup_agent.relay_runtime import otlp_traces_endpoint
    from customer_lookup_agent.settings import get_settings

    settings = replace(
        get_settings(), mlflow_tracking_uri="https://mlflow.redhat-ods-applications.svc:8443/mlflow"
    )
    assert otlp_traces_endpoint(settings) == "https://mlflow.redhat-ods-applications.svc:8443/v1/traces"
    assert otlp_traces_endpoint(replace(settings, mlflow_otlp_endpoint="https://x/otlp")) == "https://x/otlp"
