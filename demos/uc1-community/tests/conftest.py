"""Offline test harness: a tiny OTLP/HTTP receiver that stands in for MLflow.

The tests run the real agent, with the deterministic scripted model, against
the real Relay policy files. They capture what Relay would export to MLflow,
so they check the same telemetry boundary as the live demo without
containers, an LLM, or an MLflow server.
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
        self.requests: list[dict] = []  # {"headers": {...}, "body": dict}
        self._lock = threading.Lock()

    def add(self, headers: dict, body: dict) -> None:
        with self._lock:
            self.requests.append({"headers": headers, "body": body})

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
            msg = ExportTraceServiceRequest()
            msg.ParseFromString(raw)
            capture.add({k.lower(): v for k, v in self.headers.items()}, MessageToDict(msg))
            self.send_response(200)
            self.send_header("content-type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    # The same variables that relay_runtime.configure_mlflow_routing() exports.
    monkeypatch.setenv("MLFLOW_OTLP_HOST", "127.0.0.1")
    monkeypatch.setenv("MLFLOW_OTLP_TRACES_ENDPOINT", f"http://127.0.0.1:{port}/v1/traces")
    monkeypatch.setenv("MLFLOW_OTLP_AUTHORIZATION", "Basic cmVsYXktYWdlbnQ6dGVzdA==")
    monkeypatch.setenv("MLFLOW_OTLP_EXPERIMENT_ID", "42")
    monkeypatch.setenv("RELAY_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "scripted")
    monkeypatch.setenv("TOOL_TIMEOUT_SECONDS", "0.5")
    yield capture
    server.shutdown()


def plugins_file(mode: str) -> str:
    return str(DEMO_DIR / "relay" / f"plugins.{mode}.toml")


os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
