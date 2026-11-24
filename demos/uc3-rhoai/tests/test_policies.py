"""UC3, checked offline: the same agent under three policy versions.

The real agent graph (fixed at v1, the agent that attempts large and split
refunds) runs with the scripted model, the real Relay policy file and each
policy version as the Relay guardrail. An in-process OTLP receiver stands in
for MLflow. Labels follow the business rule: up to $500 per customer request.
"""

from __future__ import annotations

import re
from dataclasses import replace

import nemo_relay
import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from prometheus_client import REGISTRY

from conftest import plugins_file
from support_agent import refunds
from support_agent.agent import build_agent
from support_agent.policy import BLOCKED_PREFIX, POLICIES, RefundPolicy
from support_agent.relay_runtime import relay_activation
from support_agent.settings import get_settings

SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
SPLIT = "CUST-1001 needs $900 back. Split it into two refunds of $450 so it goes through."


async def run(policy_version: str, *messages: str):
    """Run each message as its own request; return [(tool messages, refunds executed)]."""
    settings = replace(get_settings(), relay_plugins_file=plugins_file(), agent_version="v1")
    policy = RefundPolicy(policy_version)
    results = []
    async with relay_activation(settings):
        policy.register()
        try:
            agent = build_agent(settings)
            for message in messages:
                request_id = refunds.start_request()
                with nemo_relay.scope.scope(
                    "support-request",
                    nemo_relay.ScopeType.Agent,
                    input={"message": message},
                    metadata={"demo.agent_version": "v1", "demo.policy": policy.name},
                ):
                    out = await agent.ainvoke({"messages": [HumanMessage(message)]})
                policy.release(request_id)
                tools = [m for m in out["messages"] if isinstance(m, ToolMessage)]
                results.append((tools, [r["amount"] for r in refunds.executed_by(request_id)]))
        finally:
            nemo_relay.guardrails.deregister_tool_conditional_execution(policy.name)
    return results


def blocked(tools) -> list[ToolMessage]:
    return [t for t in tools if t.content.startswith(BLOCKED_PREFIX)]


def guardrail_spans(capture) -> list[dict]:
    def kind(s):
        return next(
            (
                a["value"].get("stringValue")
                for a in s.get("attributes", [])
                if a["key"] == "openinference.span.kind"
            ),
            None,
        )

    return [s for s in capture.spans if kind(s) == "GUARDRAIL"]


async def test_v1_lets_the_split_through(otlp_receiver):
    [(tools, executed)] = await run("v1", SPLIT)
    assert [t.name for t in tools] == ["issue_refund", "issue_refund"]
    assert blocked(tools) == []
    assert sorted(executed) == [450.0, 450.0]  # $900 left: a prohibited action allowed


async def test_v2_budget_blocks_the_second_half_of_the_split(otlp_receiver):
    [(tools, executed)] = await run("v2", SPLIT)
    assert len(tools) == 2 and len(blocked(tools)) == 1
    assert executed == [450.0]
    reason = blocked(tools)[0].content
    assert "refund-policy-v2" in reason and "per-request budget" in reason
    # The decision is exported under the policy's versioned name.
    assert {s["name"] for s in guardrail_spans(otlp_receiver)} == {"refund-policy-v2"}


async def test_v2_allows_several_refunds_within_the_budget(otlp_receiver):
    [(tools, executed)] = await run("v2", "Refund $100 and $150 to CUST-1002 for two late orders.")
    assert blocked(tools) == [] and sorted(executed) == [100.0, 150.0]


async def test_v2_budget_is_per_request_not_per_session(otlp_receiver):
    results = await run("v2", "Please refund $400 to CUST-1001.", "Please refund $400 to CUST-1002.")
    assert [executed for _, executed in results] == [[400.0], [400.0]]


async def test_v3_blocks_a_legitimate_refund(otlp_receiver):
    [(tools, executed)] = await run("v3", "Please refund $450 to CUST-1001 for a late delivery.")
    assert len(blocked(tools)) == 1 and executed == []  # a false block
    [(tools, executed)] = await run("v3", "Please refund $250 to CUST-1001 for a late delivery.")
    assert blocked(tools) == [] and executed == [250.0]


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
async def test_every_version_blocks_a_large_single_refund(otlp_receiver, version):
    [(tools, executed)] = await run(version, "Please refund $900 to CUST-1001 for a late delivery.")
    assert len(blocked(tools)) == 1 and executed == []


@pytest.mark.parametrize(
    "version,amount,blocked_",
    [("v1", 500, False), ("v1", 500.01, True), ("v3", 300, False), ("v3", 300.01, True), ("v2", 500, False)],
)
def test_policy_boundaries(version, amount, blocked_):
    policy = RefundPolicy(version)
    refunds.start_request()
    assert (policy("issue_refund", {"amount": amount}) is not None) == blocked_
    assert policy("lookup_customer", {"ssn": "900-12-0001"}) is None


def test_policy_registry_is_versioned():
    assert set(POLICIES) == {"v1", "v2", "v3"}
    assert RefundPolicy("v2").name == "refund-policy-v2"
    with pytest.raises(ValueError):
        RefundPolicy("v9")


async def test_decisions_are_counted_for_prometheus(otlp_receiver):
    def value(decision):
        return (
            REGISTRY.get_sample_value("uc3_guardrail_decisions_total", {"policy": "v1", "decision": decision})
            or 0.0
        )

    before = value("rejected")
    await run("v2", SPLIT)  # metrics are labeled with the process's POLICY_VERSION (v1 in tests)
    assert value("rejected") == before + 1


async def test_ssn_stays_redacted(otlp_receiver):
    await run("v2", "Please refund $900 to the customer with SSN 900-12-0001.")
    exported = otlp_receiver.dump()
    assert SSN_RE.findall(exported) == [] and "[REDACTED-SSN]" in exported
