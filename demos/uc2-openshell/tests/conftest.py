"""Offline test harness: stand-ins for MLflow and for the sandboxed payments path.

* ``otlp_receiver``: a tiny OTLP/HTTP receiver that captures what Relay would
  export to MLflow.
* ``payments`` (autouse): a fake payments service that behaves like the real
  one *as seen from inside the sandbox*: ``POST /v1/refunds`` executes and is
  recorded in a ledger; ``POST /v1/credits`` gets the answer that OpenShell's
  L7 engine gives for a denied path (``403`` + ``policy_denied`` JSON) and is
  never recorded.

The tests run the real agent, with the deterministic scripted model, against
the real Relay policy file, without containers, an LLM, MLflow, or OpenShell.
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
    monkeypatch.setenv("MLFLOW_OTLP_CONNECTION", "close")
    monkeypatch.setenv("RELAY_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "scripted")
    monkeypatch.setenv("AGENT_VERSION", "v1")
    monkeypatch.setenv("POLICY_VERSION", "v1")
    monkeypatch.setenv("TOOL_TIMEOUT_SECONDS", "0.5")
    monkeypatch.setenv("SANDBOX_NAME", "test-sandbox")
    yield capture
    server.shutdown()


DENIAL = {
    "error": "policy_denied",
    "policy": "payments_refunds",
    "rule": "POST /v1/credits",
    "detail": "POST host.openshell.internal:8090/v1/credits not permitted by policy",
}


@pytest.fixture(autouse=True)
def payments(monkeypatch):
    """Fake payments service with OpenShell's view of it. Yields {"ledger": [...], "denied": [...]}."""
    state: dict[str, list] = {"ledger": [], "denied": []}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            if self.path == "/v1/refunds":
                entry = {
                    "id": f"RF-{len(state['ledger']):04d}",
                    "kind": "refund",
                    "customer_id": body["customer_id"],
                    "amount": round(float(body["amount"]), 2),
                    "request_id": self.headers.get("x-request-id"),
                }
                state["ledger"].append(entry)
                self._send(201, entry)
            else:  # what the OpenShell supervisor answers for a denied path
                state["denied"].append({"path": self.path, **body})
                self._send(403, DENIAL)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("PAYMENTS_URL", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    yield state
    server.shutdown()


def plugins_file() -> str:
    return str(DEMO_DIR / "relay" / "plugins.toml")


os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
