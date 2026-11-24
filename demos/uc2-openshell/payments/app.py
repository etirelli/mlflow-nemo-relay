"""Synthetica payments service: the system of record for money movements.

It runs OUTSIDE the agent sandbox (compose, port 8090) and exposes:

    POST /v1/refunds   issue a refund         <- the ONLY path the sandbox policy allows
    POST /v1/credits   post an account credit <- a back door; the sandbox policy denies it
    GET  /v1/ledger    every movement that actually executed (?request_id=..., ?kind=...)
    GET  /healthz

The ledger is the independent evidence for the demo: a refund blocked by the
Relay guardrail, or a credit denied by OpenShell, never reaches this service, so
it never appears here. ``make verify`` reads the ledger from the laptop and
compares it with the decisions recorded in MLflow.

The service itself does not enforce the refund limit, on purpose: like many
real back-office APIs, it trusts its callers. That is why the limit is enforced
in front of it (Relay) and why the agent may reach only the refunds path
(OpenShell).

Standard library only. The ledger is persisted as JSON lines in LEDGER_FILE.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

LEDGER_FILE = Path(os.environ.get("LEDGER_FILE", "/data/ledger.jsonl"))
PORT = int(os.environ.get("PORT", "8090"))
_LOCK = threading.Lock()


def _append(entry: dict) -> None:
    with _LOCK:
        LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")


def _ledger() -> list[dict]:
    with _LOCK:
        if not LEDGER_FILE.exists():
            return []
        return [json.loads(line) for line in LEDGER_FILE.read_text().splitlines() if line.strip()]


class Handler(BaseHTTPRequestHandler):
    server_version = "synthetica-payments/1.0"

    def _send(self, status: int, body: dict | list) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _movement(self, kind: str) -> None:
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            amount = round(float(body["amount"]), 2)
            customer_id = str(body["customer_id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"error": "invalid_request", "detail": str(exc)})
            return
        if amount <= 0:
            self._send(400, {"error": "invalid_amount", "detail": f"amount must be positive, got {amount}"})
            return
        prefix = "RF" if kind == "refund" else "CR"
        entry = {
            "id": f"{prefix}-{uuid.uuid4().hex[:8].upper()}",
            "kind": kind,
            "customer_id": customer_id,
            "amount": amount,
            "reason": str(body.get("reason", "")),
            "request_id": self.headers.get("x-request-id"),
            "agent_version": self.headers.get("x-agent-version"),
            "executed_at": time.time(),
        }
        _append(entry)
        self._send(201, entry)

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/v1/refunds":
            self._movement("refund")
        elif path == "/v1/credits":
            self._movement("credit")
        else:
            self._send(404, {"error": "not_found"})

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/healthz":
            self._send(200, {"ok": True})
        elif url.path == "/v1/ledger":
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            rows = [r for r in _ledger() if all(str(r.get(k)) == v for k, v in query.items())]
            self._send(200, rows)
        else:
            self._send(404, {"error": "not_found"})

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    print(f"payments service on :{PORT}, ledger {LEDGER_FILE}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
