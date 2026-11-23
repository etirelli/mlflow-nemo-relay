"""Deterministic chat model for offline tests and rehearsals.

It imitates the two agent revisions:

* v1 follows the user literally: it calls ``issue_refund`` for any amount.
* v2 knows the limit: above it, it calls ``request_supervisor_approval``.

Both look the customer up first when the request contains an SSN, and both
handle a plain lookup like the UC1 agent.
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
CUST_RE = re.compile(r"\bCUST-\d{4}\b")
AMOUNT_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")


def _call(name: str, args: dict) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:12]}"}]
    )


def _tool_name(msg: ToolMessage, messages: list[BaseMessage]) -> str | None:
    if msg.name:
        return msg.name
    for m in reversed(messages):
        for c in getattr(m, "tool_calls", None) or []:
            if c.get("id") == msg.tool_call_id:
                return c.get("name")
    return None


class ScriptedSupportModel(BaseChatModel):
    """Plays the LLM role without network access."""

    model_name: str = "scripted-support-agent"
    version: str = "v1"
    refund_limit: float = 500.0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedSupportModel:
        return self

    def _refund_step(self, customer_id: str, amount: float) -> AIMessage:
        args = {"customer_id": customer_id, "amount": amount, "reason": "customer request"}
        if self.version == "v2" and amount > self.refund_limit:
            return _call("request_supervisor_approval", args)
        return _call("issue_refund", args)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        text = str(human.content) if human else ""
        amount_m = AMOUNT_RE.search(text)
        amount = float(amount_m.group(1).replace(",", "")) if amount_m else None
        last = messages[-1]

        if isinstance(last, HumanMessage):
            if (ssn := SSN_RE.search(text)) and (amount is None or not CUST_RE.search(text)):
                msg = _call("lookup_customer", {"ssn": ssn.group(0)})
            elif amount is not None and (cust := CUST_RE.search(text)):
                msg = self._refund_step(cust.group(0), amount)
            else:
                msg = AIMessage(content="I can look up customers by SSN and help with refunds.")
        elif isinstance(last, ToolMessage):
            name = _tool_name(last, messages)
            content = str(last.content)
            ok = getattr(last, "status", "") != "error" and content.lstrip().startswith("{")
            if name == "lookup_customer" and amount is not None and ok:
                msg = self._refund_step(json.loads(content)["customer_id"], amount)
            else:
                msg = AIMessage(content=self._summarize(name, last, content))
        else:
            msg = AIMessage(content="How can I help?")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @staticmethod
    def _summarize(name: str | None, msg: ToolMessage, content: str) -> str:
        if content.startswith("BLOCKED_BY_POLICY"):
            return f"I couldn't issue that refund: {content}"
        if getattr(msg, "status", None) == "error" or not content.lstrip().startswith("{"):
            return f"Sorry, the request failed: {content}"
        data = json.loads(content) if content.startswith("{") else {}
        if name == "issue_refund":
            return (
                f"Refund {data.get('refund_id')} of ${data.get('amount')} "
                f"issued to {data.get('customer_id')}."
            )
        if name == "request_supervisor_approval":
            return (
                f"That amount needs supervisor approval, so I escalated it (ticket {data.get('ticket')}). "
                f"{data.get('next_step')}"
            )
        return (
            f"Found {data.get('name')} ({data.get('customer_id')}), SSN {data.get('ssn')}: "
            f"{data.get('plan')} plan, account {data.get('status')}."
        )
