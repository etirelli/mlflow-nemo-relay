"""LangGraph customer lookup agent instrumented with NeMo Relay."""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from nemo_relay.integrations.langgraph import NemoRelayMiddleware, configure_graph

from customer_lookup_agent.settings import Settings
from customer_lookup_agent.tools import TOOLS

SYSTEM_PROMPT = """You are a customer support assistant for a retail bank.
When the user provides a Social Security number, call the lookup_customer tool
with it exactly as written (format NNN-NN-NNNN). Summarize the account for the
support engineer in one or two sentences. If the tool reports an error, explain
the failure plainly and suggest a next step. Never invent customer data."""


def build_model(settings: Settings) -> BaseChatModel:
    if settings.llm_provider == "scripted":
        from customer_lookup_agent.scripted_model import ScriptedCustomerLookupModel

        return ScriptedCustomerLookupModel()

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

    ``NemoRelayMiddleware`` routes every LLM and tool call through Relay's
    managed execution pipeline. That pipeline produces the LLM and tool spans,
    and it is where the pii_redaction policy sanitizes telemetry.
    ``configure_graph`` adds the callback handler that records graph and node
    scopes, so tool spans keep their place in the agent run.
    """
    agent = create_agent(
        model=build_model(settings),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[NemoRelayMiddleware()],
        name="customer_lookup_agent",
    )
    return configure_graph(agent)
