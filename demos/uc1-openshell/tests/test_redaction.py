"""Use case 1 success criteria, checked offline against the exported OTLP payloads."""

from __future__ import annotations

import re
from dataclasses import replace

import nemo_relay
import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from conftest import plugins_file
from customer_lookup_agent.agent import build_agent
from customer_lookup_agent.customer_db import SUCCESS_SSN, TIMEOUT_SSN
from customer_lookup_agent.relay_runtime import relay_activation
from customer_lookup_agent.settings import get_settings

SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
STATUS_ERROR = "STATUS_CODE_ERROR"


async def run_scenarios(mode: str) -> list[list]:
    settings = replace(get_settings(), relay_mode=mode, relay_plugins_file=plugins_file(mode))
    results = []
    async with relay_activation(settings):
        agent = build_agent(settings)
        for ssn in (SUCCESS_SSN, TIMEOUT_SSN):
            with nemo_relay.scope.scope(
                "customer-lookup-request", nemo_relay.ScopeType.Agent, input={"message": f"SSN {ssn}"}
            ):
                out = await agent.ainvoke({"messages": [HumanMessage(f"Look up SSN {ssn}")]})
            results.append(out["messages"])
    return results  # leaving the activation flushes and shuts down the exporters


def tool_spans(capture) -> list[dict]:
    def kind(span):
        for attr in span.get("attributes", []):
            if attr["key"] == "openinference.span.kind":
                return attr["value"].get("stringValue")

    return [s for s in capture.spans if kind(s) == "TOOL"]


async def test_redacted_export_contains_no_ssn(otlp_receiver, tmp_path):
    results = await run_scenarios("redacted")

    # 1. The tool received the original input: the lookup worked.
    tool_messages = [m for msgs in results for m in msgs if isinstance(m, ToolMessage)]
    assert SUCCESS_SSN in tool_messages[0].content  # real value returned to the app
    assert tool_messages[1].status == "error"

    # 2. Nothing SSN-shaped reached the exporter, but redaction markers did.
    exported = otlp_receiver.dump()
    assert otlp_receiver.spans, "no spans were exported"
    assert SSN_RE.findall(exported) == []
    assert "[REDACTED-SSN]" in exported

    # 3. The local ATOF copy is clean too.
    atof = (tmp_path / "atof-redacted.jsonl").read_text()
    assert SSN_RE.findall(atof) == []


async def test_tool_outcomes_and_parentage_survive_export(otlp_receiver):
    await run_scenarios("redacted")
    tools = tool_spans(otlp_receiver)
    statuses = sorted(s.get("status", {}).get("code", "STATUS_CODE_UNSET") for s in tools)
    assert statuses.count(STATUS_ERROR) == 1, statuses
    assert len(tools) == 2

    by_id = {s["spanId"]: s for s in otlp_receiver.spans}
    for span in tools:
        assert int(span["endTimeUnixNano"]) > int(span["startTimeUnixNano"])
        chain, cur = [], span
        while cur is not None:
            chain.append(cur["name"])
            cur = by_id.get(cur.get("parentSpanId"))
        assert chain[-1] == "customer-lookup-request", chain


async def test_export_is_authenticated_and_routed(otlp_receiver):
    await run_scenarios("redacted")
    headers = otlp_receiver.requests[0]["headers"]
    assert headers["authorization"].startswith("Basic ")
    assert headers["x-mlflow-experiment-id"] == "42"


async def test_baseline_control_leaks_ssn(otlp_receiver):
    """Without the pii_redaction component, the same run leaks the SSN, so the checks above mean something."""
    await run_scenarios("baseline")
    found = set(SSN_RE.findall(otlp_receiver.dump()))
    assert {SUCCESS_SSN, TIMEOUT_SSN} <= found


@pytest.mark.parametrize("mode", ["redacted", "baseline"])
def test_policy_files_render(mode, otlp_receiver):
    from customer_lookup_agent.relay_runtime import render_plugins_file

    with open(render_plugins_file(plugins_file(mode))) as f:
        lines = [line for line in f.read().splitlines() if not line.lstrip().startswith("#")]
    assert not any("${" in line for line in lines)
