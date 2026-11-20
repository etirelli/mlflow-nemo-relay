"""OpenShell egress denial, checked offline.

A tiny HTTP server answers like the OpenShell supervisor does for a denied
plain-HTTP request: ``403`` with a ``policy_denied`` JSON body. The agent's
partner CRM sync must then

* produce an ERROR tool span that names the denial (so MLflow shows *why*),
* keep the SSN out of the exported telemetry, including the echoed error,
* carry the sandbox name on the root span (``demo.sandbox``).

The live demo checks the same things against MLflow and the real sandbox.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import nemo_relay
import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from conftest import plugins_file
from customer_lookup_agent.agent import build_agent
from customer_lookup_agent.customer_db import CRM_SSN
from customer_lookup_agent.relay_runtime import relay_activation
from customer_lookup_agent.settings import get_settings
from customer_lookup_agent.tools import EGRESS_BLOCKED

SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
DENIAL = {
    "error": "policy_denied",
    "detail": "POST partner-crm.example.com/v1/customers/notify not permitted by policy",
    "reason": "no network policy allows /usr/local/bin/python3.12 to reach partner-crm.example.com:443",
}


@pytest.fixture
def denying_proxy(monkeypatch):
    received: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received.append(self.rfile.read(int(self.headers.get("content-length", 0))))
            body = json.dumps(DENIAL).encode()
            self.send_response(403)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("PARTNER_CRM_URL", f"http://127.0.0.1:{server.server_address[1]}/v1/customers/notify")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    yield received
    server.shutdown()


async def run_crm_scenario() -> list:
    settings = replace(get_settings(), relay_mode="redacted", relay_plugins_file=plugins_file("redacted"))
    async with relay_activation(settings):
        agent = build_agent(settings)
        with nemo_relay.scope.scope(
            "customer-lookup-request",
            nemo_relay.ScopeType.Agent,
            input={"message": f"sync SSN {CRM_SSN}"},
            metadata={"demo.sandbox": "test-sandbox"},
        ):
            out = await agent.ainvoke(
                {"messages": [HumanMessage(f"Look up SSN {CRM_SSN} and sync it to the partner CRM.")]}
            )
    return out["messages"]


def span_attr(span: dict, key: str) -> str | None:
    for attr in span.get("attributes", []):
        if attr["key"] == key:
            return attr["value"].get("stringValue")
    return None


async def test_blocked_egress_is_a_readable_error_span(otlp_receiver, denying_proxy):
    messages = await run_crm_scenario()

    # The agent looked the customer up, then the sync was refused.
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    assert [m.name for m in tool_messages] == ["lookup_customer", "notify_partner_crm"]
    crm = tool_messages[1]
    assert crm.status == "error"
    assert EGRESS_BLOCKED in crm.content and "policy_denied" in crm.content

    # The tool really tried (the "proxy" saw the request) - that is the point:
    # the boundary, not the agent, stopped it.
    assert denying_proxy, "the tool never attempted the connection"

    tools = {s["name"]: s for s in otlp_receiver.spans if span_attr(s, "openinference.span.kind") == "TOOL"}
    span = tools["notify_partner_crm"]
    assert span.get("status", {}).get("code") == "STATUS_CODE_ERROR"
    exported = otlp_receiver.dump()
    assert EGRESS_BLOCKED in exported and "policy_denied" in exported

    # The SSN that the tool echoed in its error is redacted in telemetry.
    assert SSN_RE.findall(exported) == []
    assert "[REDACTED-SSN]" in exported


async def test_sandbox_name_is_exported(otlp_receiver, denying_proxy):
    await run_crm_scenario()
    assert "test-sandbox" in otlp_receiver.dump()
