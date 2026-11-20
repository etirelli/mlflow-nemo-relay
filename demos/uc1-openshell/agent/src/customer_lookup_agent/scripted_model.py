"""Deterministic chat model for offline rehearsals and automated tests.

It behaves like a tool-calling LLM: it finds an SSN in the user's message,
requests one ``lookup_customer`` call, and then summarizes the tool result.
If the user asks to sync the customer with the partner CRM, it follows a
successful lookup with a ``notify_partner_crm`` call, which the OpenShell
sandbox policy blocks.
Use it with ``LLM_PROVIDER=scripted`` when no LLM endpoint is available.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

SSN_RE = re.compile(r"\b\d{3}-?\d{2}-?\d{4}\b")
CRM_RE = re.compile(r"\b(partner|crm)\b", re.IGNORECASE)


def _tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:12]}"}],
    )


def _is_error(tool_message: ToolMessage, content: str) -> bool:
    return getattr(tool_message, "status", None) == "error" or content.startswith(
        ("Error", "TimeoutError", "NotFound", "EgressBlocked", "PartnerCRMError")
    )


def _tool_name(tool_message: ToolMessage, messages: list[BaseMessage]) -> str | None:
    """Name of the tool that produced ``tool_message``.

    ``ToolMessage.name`` is not always populated (Relay's managed tool path can
    drop it), so fall back to the matching tool call of an earlier AIMessage.
    """
    if tool_message.name:
        return tool_message.name
    for message in reversed(messages):
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("id") == tool_message.tool_call_id:
                return call.get("name")
    return None


class ScriptedCustomerLookupModel(BaseChatModel):
    """Plays the LLM role in the demo without network access."""

    model_name: str = "scripted-customer-lookup"

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedCustomerLookupModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last = messages[-1]
        human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        wants_crm = bool(human and CRM_RE.search(str(human.content)))

        if isinstance(last, ToolMessage):
            content = str(last.content)
            tool = _tool_name(last, messages)
            if tool == "lookup_customer" and wants_crm and not _is_error(last, content):
                record = json.loads(content)
                message = _tool_call(
                    "notify_partner_crm",
                    {"customer_id": record.get("customer_id"), "ssn": record.get("ssn")},
                )
            else:
                message = AIMessage(content=self._summarize(last, tool))
        elif isinstance(last, HumanMessage) and (match := SSN_RE.search(str(last.content))):
            message = _tool_call("lookup_customer", {"ssn": match.group(0)})
        else:
            message = AIMessage(
                content="I can look up a customer account if you share their SSN (format NNN-NN-NNNN)."
            )
        return ChatResult(generations=[ChatGeneration(message=message)])

    @staticmethod
    def _summarize(tool_message: ToolMessage, tool: str | None = None) -> str:
        content = str(tool_message.content)
        if (tool or tool_message.name) == "notify_partner_crm":
            if _is_error(tool_message, content):
                return (
                    "I found the customer, but I could not sync the record to the partner CRM: "
                    f"{content} Ask the platform team whether this destination should be approved."
                )
            return f"The record was synced to the partner CRM: {content}"
        if _is_error(tool_message, content):
            return (
                "Sorry, I couldn't complete the lookup because the customer records "
                f"service reported a problem: {content}"
            )
        try:
            record = json.loads(content)
        except json.JSONDecodeError:
            return f"Lookup result: {content}"
        return (
            f"Found {record.get('name')} ({record.get('customer_id')}), SSN {record.get('ssn')}: "
            f"{record.get('plan')} plan, account {record.get('status')}, "
            f"{record.get('open_tickets')} open ticket(s)."
        )
