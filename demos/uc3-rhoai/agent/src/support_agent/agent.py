"""LangGraph support agent, in two revisions, instrumented with NeMo Relay.

v1 is the agent as first shipped: helpful, and unaware of the refund limit.
v2 is the revision an engineer makes after reviewing the guardrail decisions
in MLflow: the system prompt and tool definitions explain the limit and give
the agent an escalation path. The Relay policy is identical for both.
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from nemo_relay.integrations.langgraph import NemoRelayMiddleware, configure_graph

from support_agent.policy import PolicyDecisionMiddleware
from support_agent.settings import Settings
from support_agent.tools import build_tools

SYSTEM_PROMPTS = {
    "v1": """You are a customer support assistant for a retail bank.
You can look up customers by Social Security number (format NNN-NN-NNNN) and
issue refunds to their accounts. When a customer asks for a refund, look the
customer up if needed, then issue the refund they asked for and confirm it.
If a tool reports an error, explain it plainly. Never invent customer data.""",
    "v2": """You are a customer support assistant for a retail bank.
You can look up customers by Social Security number (format NNN-NN-NNNN),
issue refunds, and request supervisor approval.

Refund policy (enforced by the platform; you cannot override it):
- You may issue refunds of up to ${limit:,.0f} per request with issue_refund.
- For any amount above ${limit:,.0f}, do NOT call issue_refund and do NOT split
  it into smaller refunds. Call request_supervisor_approval instead, and tell
  the customer their request was escalated and what happens next.
- A refund of exactly ${limit:,.0f} is allowed.

Look the customer up first when you only have their SSN. If a tool reports an
error, explain it plainly. Never claim a refund was issued unless issue_refund
succeeded. Never invent customer data.""",
}


def system_prompt(settings: Settings) -> str:
    template = SYSTEM_PROMPTS.get(settings.agent_version, SYSTEM_PROMPTS["v1"])
    return template.replace("${limit:,.0f}", f"${settings.refund_limit:,.0f}")


def build_model(settings: Settings) -> BaseChatModel:
    if settings.llm_provider == "scripted":
        from support_agent.scripted_model import ScriptedSupportModel

        return ScriptedSupportModel(version=settings.agent_version, refund_limit=settings.refund_limit)

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0,
        timeout=120,
    )


def build_agent(settings: Settings):
    """Build the agent graph.

    Middleware order matters (first = outermost):
    1. ``PolicyDecisionMiddleware`` turns a Relay guardrail rejection into a
       ``BLOCKED_BY_POLICY`` tool result.
    2. ``NemoRelayMiddleware`` routes LLM and tool calls through Relay's managed
       pipeline, where the guardrail runs and every decision is recorded.
    """
    agent = create_agent(
        model=build_model(settings),
        tools=build_tools(settings.agent_version),
        system_prompt=system_prompt(settings),
        middleware=[PolicyDecisionMiddleware(), NemoRelayMiddleware()],
        name=f"support_agent_{settings.agent_version}",
    )
    return configure_graph(agent)
