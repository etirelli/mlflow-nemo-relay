"""Deterministic chat model for offline rehearsals and automated tests.

It behaves like a tool-calling LLM: it finds an SSN in the user's message,
requests one ``lookup_customer`` call, and then summarizes the tool result.
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
        if isinstance(last, ToolMessage):
            message = AIMessage(content=self._summarize(last))
        elif isinstance(last, HumanMessage) and (match := SSN_RE.search(str(last.content))):
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "lookup_customer",
                        "args": {"ssn": match.group(0)},
                        "id": f"call_{uuid.uuid4().hex[:12]}",
                    }
                ],
            )
        else:
            message = AIMessage(
                content="I can look up a customer account if you share their SSN (format NNN-NN-NNNN)."
            )
        return ChatResult(generations=[ChatGeneration(message=message)])

    @staticmethod
    def _summarize(tool_message: ToolMessage) -> str:
        content = str(tool_message.content)
        if getattr(tool_message, "status", None) == "error" or content.startswith(
            ("Error", "TimeoutError", "NotFound")
        ):
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
