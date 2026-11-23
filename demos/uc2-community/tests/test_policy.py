"""UC2 behavior, checked offline: guardrail decisions, enforcement, and the v1 -> v2 change.

The real agent graph runs with the scripted model, the real Relay policy file
and the real refund guardrail. An in-process OTLP receiver stands in for MLflow.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import nemo_relay
import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from conftest import plugins_file
from support_agent import refunds
from support_agent.agent import build_agent
from support_agent.policy import BLOCKED_PREFIX, RefundPolicy
from support_agent.relay_runtime import relay_activation
from support_agent.settings import get_settings

SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


async def run(version: str, message: str):
    settings = replace(get_settings(), relay_plugins_file=plugins_file(), agent_version=version)
    policy = RefundPolicy("v1", 500)
    request_id = refunds.start_request()
    async with relay_activation(settings):
        policy.register()
        try:
            agent = build_agent(settings)
            with nemo_relay.scope.scope(
                "support-request",
                nemo_relay.ScopeType.Agent,
                input={"message": message},
                metadata={"demo.agent_version": version, "demo.policy": policy.name},
            ):
                out = await agent.ainvoke({"messages": [HumanMessage(message)]})
        finally:
            nemo_relay.guardrails.deregister_tool_conditional_execution(policy.name)
    tools = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    return out["messages"][-1].content, tools, refunds.executed_by(request_id)


def attrs(span: dict) -> dict:
    return {a["key"]: next(iter(a["value"].values()), None) for a in span.get("attributes", [])}


def spans_of_kind(capture, kind: str) -> list[dict]:
    return [s for s in capture.spans if attrs(s).get("openinference.span.kind") == kind]


async def test_v1_large_refund_is_blocked_before_execution(otlp_receiver):
    reply, tools, executed = await run("v1", "Please refund $900 to CUST-1001 for a late delivery.")

    # The agent attempted the prohibited action, Relay blocked it, nothing executed.
    assert [t.name for t in tools] == ["issue_refund"]
    assert tools[0].status == "error" and tools[0].content.startswith(BLOCKED_PREFIX)
    assert executed == []
    assert "couldn't issue" in reply

    # The decision is exported: GUARDRAIL span, rejected, reason with the policy version.
    guardrails = spans_of_kind(otlp_receiver, "GUARDRAIL")
    assert len(guardrails) == 1
    g = attrs(guardrails[0])
    assert guardrails[0]["name"] == "refund-limit-v1"
    assert g["nemo_relay.end.data.rejected"] is True and g["nemo_relay.end.data.allowed"] is False
    assert "exceeds the $500.00 limit" in g["nemo_relay.end.data.rejection_reason"]
    assert g["nemo_relay.start.data.target_name"] == "issue_refund"
    # The blocked tool never started: no TOOL span at all for this request.
    assert spans_of_kind(otlp_receiver, "TOOL") == []


async def test_allowed_refund_executes_and_the_guardrail_allows_it(otlp_receiver):
    _, tools, executed = await run("v1", "Please refund $120 to CUST-1001 for a late delivery.")
    assert tools[0].status == "success"
    assert len(executed) == 1 and executed[0]["amount"] == 120.0
    g = attrs(spans_of_kind(otlp_receiver, "GUARDRAIL")[0])
    assert g["nemo_relay.end.data.allowed"] is True
    assert [s["name"] for s in spans_of_kind(otlp_receiver, "TOOL")] == ["issue_refund"]


async def test_v2_escalates_instead_of_attempting(otlp_receiver):
    reply, tools, executed = await run("v2", "Please refund $900 to CUST-1001 for a late delivery.")
    assert [t.name for t in tools] == ["request_supervisor_approval"]
    assert not any(t.content.startswith(BLOCKED_PREFIX) for t in tools)
    assert executed == []
    assert "escalated" in reply
    # Same policy, still enforced; it simply had nothing to block.
    rejected = [
        s for s in spans_of_kind(otlp_receiver, "GUARDRAIL") if attrs(s).get("nemo_relay.end.data.rejected")
    ]
    assert rejected == []


async def test_policy_rejection_is_distinguishable_from_tool_failure(otlp_receiver):
    # A lookup timeout is a tool failure: TOOL span with status ERROR, no guardrail rejection.
    _, tools, _ = await run("v1", "Please refund $100 to the customer with SSN 900-34-0004.")
    assert tools[0].name == "lookup_customer" and tools[0].status == "error"
    assert not tools[0].content.startswith(BLOCKED_PREFIX)
    tool_spans = spans_of_kind(otlp_receiver, "TOOL")
    assert tool_spans[0].get("status", {}).get("code") == "STATUS_CODE_ERROR"


async def test_ssn_stays_redacted_with_the_guardrail_in_place(otlp_receiver):
    await run("v1", "Please refund $900 to the customer with SSN 900-12-0001.")
    exported = otlp_receiver.dump()
    assert SSN_RE.findall(exported) == []
    assert "[REDACTED-SSN]" in exported


@pytest.mark.parametrize("amount,blocked", [(500, False), (500.01, True), ("abc", True)])
def test_policy_boundaries(amount, blocked):
    reason = RefundPolicy("v1", 500)("issue_refund", {"amount": amount})
    assert (reason is not None) == blocked
    assert RefundPolicy("v1", 500)("lookup_customer", {"ssn": "900-12-0001"}) is None


def test_policy_file_renders(otlp_receiver):
    from support_agent.relay_runtime import render_plugins_file

    rendered = Path(render_plugins_file(plugins_file())).read_text()
    lines = [x for x in rendered.splitlines() if not x.lstrip().startswith("#")]
    assert not any("${" in line for line in lines)
    assert json.dumps("refund-limit-v1")[1:-1] in rendered


async def test_refunds_are_attributed_per_request_under_concurrency(otlp_receiver):
    """Concurrent requests must not see each other's refunds (evaluation runs in parallel)."""
    import asyncio

    settings = replace(get_settings(), relay_plugins_file=plugins_file(), agent_version="v1")
    policy = RefundPolicy("v1", 500)

    async def one(agent, amount: int) -> list[dict]:
        request_id = refunds.start_request()  # same as the chat handler, per request task
        await agent.ainvoke({"messages": [HumanMessage(f"Please refund ${amount} to CUST-1001.")]})
        return refunds.executed_by(request_id)

    async with relay_activation(settings):
        policy.register()
        try:
            agent = build_agent(settings)
            results = await asyncio.gather(*[asyncio.create_task(one(agent, a)) for a in (110, 220, 330)])
        finally:
            nemo_relay.guardrails.deregister_tool_conditional_execution(policy.name)
    assert [[r["amount"] for r in res] for res in results] == [[110.0], [220.0], [330.0]]
