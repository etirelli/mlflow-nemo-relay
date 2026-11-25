"""Offline test harness: a tiny OTLP/HTTP receiver that stands in for the OpenShell agent trace relay.

The tests run the real agent, with the deterministic scripted model, against
the real Relay policy files. They capture what Relay exports to the relay (and
so, through the collector, to MLflow), which is the same telemetry boundary as
the live demo, without containers, an LLM, an MLflow server, or OpenShell.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

DEMO_DIR = Path(__file__).resolve().parents[1]


class OtlpCapture:
    def __init__(self) -> None:
        self.requests: list[dict] = []  # {"path": str, "headers": {...}, "body": dict}
        self._lock = threading.Lock()

    def add(self, path: str, headers: dict, body: dict) -> None:
        with self._lock:
            self.requests.append({"path": path, "headers": headers, "body": body})

    @property
    def spans(self) -> list[dict]:
        out = []
        for req in self.requests:
            for rs in req["body"].get("resourceSpans", []):
                for ss in rs.get("scopeSpans", []):
                    out.extend(ss.get("spans", []))
        return out

    def dump(self) -> str:
        return json.dumps([r["body"] for r in self.requests])


@pytest.fixture
def otlp_receiver(tmp_path, monkeypatch):
    capture = OtlpCapture()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            raw = self.rfile.read(int(self.headers.get("content-length", 0)))
            body = {}
            if self.path.endswith("/v1/traces"):
                msg = ExportTraceServiceRequest()
                msg.ParseFromString(raw)
                body = MessageToDict(msg)
            capture.add(self.path, {k.lower(): v for k, v in self.headers.items()}, body)
            self.send_response(200)
            self.send_header("content-type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    # What a sandbox gets: the OpenShell agent trace relay's address (the receiver plays
    # it; http://192.0.0.8:4318 inside a sandbox) and the switches `make sandboxes` passes.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{port}")
    for name in ("OTEL_TRACES_EXPORTER", "OTEL_LOGS_EXPORTER", "OTEL_METRICS_EXPORTER"):
        monkeypatch.setenv(name, "none")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_ID", "42")
    monkeypatch.setenv("RELAY_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("SANDBOX_NAME", "test-sandbox")
    monkeypatch.setenv("LLM_PROVIDER", "scripted")
    monkeypatch.setenv("TOOL_TIMEOUT_SECONDS", "0.5")
    yield capture
    server.shutdown()


def plugins_file(mode: str) -> str:
    return str(DEMO_DIR / "relay" / f"plugins.{mode}.toml")


os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
