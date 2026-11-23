"""Refund policy enforced by NeMo Relay, and how its decisions reach the agent.

The policy is a Relay *tool conditional-execution guardrail*. Relay runs it
before the tool callback: if it returns a reason, the tool never executes.
Relay records the decision as a ``guardrail`` scope (``allowed``,
``rejected``, ``rejection_reason``), which is exported to MLflow with the
rest of the trace.

The policy stays fixed while the agent changes (v1 -> v2). Its identity and
version are part of every decision: the guardrail is registered as
``refund-limit-<version>`` and the reason starts with the same id.

Relay signals a rejection by raising ``RuntimeError("guardrail rejected: ...")``.
Left alone, that aborts the whole agent run. ``PolicyDecisionMiddleware``
turns it into a tool result with ``status="error"`` and a ``BLOCKED_BY_POLICY``
prefix, so the agent can explain the outcome to the user, and engineers can
tell a policy rejection from a tool failure (a timeout, for example).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import nemo_relay
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

log = logging.getLogger(__name__)

BLOCKED_PREFIX = "BLOCKED_BY_POLICY"
_RELAY_REJECTION = "guardrail rejected: "


class RefundPolicy:
    """Support agents may refund up to ``limit``; anything above needs a supervisor."""

    def __init__(self, version: str = "v1", limit: float = 500.0) -> None:
        self.version = version
        self.limit = float(limit)

    @property
    def name(self) -> str:
        return f"refund-limit-{self.version}"

    def __call__(self, tool_name: str, args: Any) -> str | None:
        if tool_name != "issue_refund":
            return None
        try:
            amount = float((args or {}).get("amount", 0))
        except (TypeError, ValueError):
            return f"{self.name}: refund amount is missing or not a number"
        if amount > self.limit:
            return (
                f"{self.name}: refund of ${amount:,.2f} exceeds the ${self.limit:,.2f} limit "
                "for support agents; supervisor approval is required"
            )
        return None

    def register(self) -> None:
        nemo_relay.guardrails.register_tool_conditional_execution(self.name, 10, self)
        log.info("Registered Relay guardrail %s (limit $%.2f)", self.name, self.limit)


def is_blocked(content: str) -> bool:
    return str(content).startswith(BLOCKED_PREFIX)


class PolicyDecisionMiddleware(AgentMiddleware):
    """Return guardrail rejections to the agent as tool results instead of crashing the run.

    It must be listed *before* ``NemoRelayMiddleware`` (first = outermost), so
    Relay has already recorded the decision when this middleware sees it.
    """

    @staticmethod
    def _blocked(request: Any, exc: Exception) -> ToolMessage:
        reason = str(exc).removeprefix(_RELAY_REJECTION)
        call = request.tool_call
        return ToolMessage(
            content=f"{BLOCKED_PREFIX}: {reason}. The action was not executed.",
            tool_call_id=call["id"],
            name=call["name"],
            status="error",
        )

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        try:
            return handler(request)
        except RuntimeError as exc:
            if str(exc).startswith(_RELAY_REJECTION):
                return self._blocked(request, exc)
            raise

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        try:
            return await handler(request)
        except RuntimeError as exc:
            if str(exc).startswith(_RELAY_REJECTION):
                return self._blocked(request, exc)
            raise
