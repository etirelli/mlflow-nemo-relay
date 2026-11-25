"""Traces leave the sandbox through the OpenShell agent trace relay, not through a network rule.

The receiver from ``conftest`` plays the relay; the test checks what the agent sends it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

import nemo_relay
from langchain_core.messages import HumanMessage

from conftest import DEMO_DIR, plugins_file
from support_agent.agent import build_agent
from support_agent.relay_runtime import configure_relay_export, relay_activation
from support_agent.settings import get_settings

# What OpenShell sets in every sandbox process while the agent trace relay is on,
# besides the relay address (the conftest points that at the receiver).
INJECTED = {
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_COMPRESSION": "none",
    "OTEL_EXPORTER_OTLP_TRACES_COMPRESSION": "none",
}
EXPORTER_SWITCHES = ("OTEL_TRACES_EXPORTER", "OTEL_LOGS_EXPORTER", "OTEL_METRICS_EXPORTER")


def attrs(span: dict) -> dict:
    return {a["key"]: next(iter(a["value"].values()), None) for a in span.get("attributes", [])}


async def test_traces_reach_the_relay_once_without_mlflow_credentials(otlp_receiver, monkeypatch):
    for name, value in INJECTED.items():
        monkeypatch.setenv(name, value)
    settings = replace(get_settings(), relay_plugins_file=plugins_file())
    configure_relay_export(settings)
    message = "Look up the customer with SSN 900-12-0001."
    async with relay_activation(settings):
        agent = build_agent(settings)
        with nemo_relay.scope.scope(
            "support-request", nemo_relay.ScopeType.Agent, input={"message": message}
        ):
            await agent.ainvoke({"messages": [HumanMessage(message)]})

    # The sandboxes get the same switches as the conftest.
    makefile = (DEMO_DIR / "Makefile").read_text()
    assert all(f"--env {name}=none" in makefile for name in EXPORTER_SWITCHES)
    assert {r["path"] for r in otlp_receiver.requests} == {"/v1/traces"}
    spans = otlp_receiver.spans
    # One OpenInference export: no duplicate gen_ai copy of each span.
    assert spans and all(attrs(s).get("openinference.span.kind") for s in spans)
    assert max(Counter(s["spanId"] for s in spans).values()) == 1
    # The collector outside the sandbox adds these; the agent never has them.
    for request in otlp_receiver.requests:
        assert "authorization" not in request["headers"]
        assert "x-mlflow-experiment-id" not in request["headers"]
        assert request["headers"].get("content-encoding", "identity") == "identity"
