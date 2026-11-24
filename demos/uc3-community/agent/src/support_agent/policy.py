"""Refund policy versions enforced by NeMo Relay, and how their decisions reach the agent.

UC3 keeps the agent fixed and changes the *policy*. Three versions of the same
refund policy can be deployed (``POLICY_VERSION``):

=====  ===========================  =====================================================
v1     ``refund-policy-v1``         $500 per refund call. The UC2 baseline in production.
v2     ``refund-policy-v2``         $500 per customer request, all refunds combined.
                                    Closes the "split it into two $450 refunds" gap.
v3     ``refund-policy-v3``         $300 per refund call. An over-strict candidate: it
                                    blocks legitimate refunds between $300 and $500.
=====  ===========================  =====================================================

The business rule that all three try to implement, and that the evaluation
labels follow, is: *a support agent may refund up to $500 per customer
request; anything more needs a supervisor.*

Each version is a Relay *tool conditional-execution guardrail*. Relay runs it
before the tool callback: if it returns a reason, the tool never executes.
The decision is recorded as a ``guardrail`` scope (``allowed``, ``rejected``,
``rejection_reason``) named after the policy version, and exported to MLflow.

Relay signals a rejection by raising ``RuntimeError("guardrail rejected: ...")``.
``PolicyDecisionMiddleware`` turns it into a tool result with a
``BLOCKED_BY_POLICY`` prefix, so the agent can explain the outcome (see UC2).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import nemo_relay
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from support_agent import metrics, refunds

log = logging.getLogger(__name__)

BLOCKED_PREFIX = "BLOCKED_BY_POLICY"
_RELAY_REJECTION = "guardrail rejected: "
# The business rule the policy versions implement (and the evaluation labels follow).
BUSINESS_LIMIT = 500.0


@dataclass(frozen=True)
class PolicySpec:
    version: str
    scope: str  # "call" (each issue_refund on its own) or "request" (all refunds in one request)
    limit: float
    summary: str


POLICIES: dict[str, PolicySpec] = {
    "v1": PolicySpec("v1", "call", 500.0, "up to $500 per refund call"),
    "v2": PolicySpec("v2", "request", 500.0, "up to $500 per customer request, all refunds combined"),
    "v3": PolicySpec("v3", "call", 300.0, "up to $300 per refund call"),
}


class RefundPolicy:
    """One version of the refund policy, registered as a Relay guardrail."""

    def __init__(self, version: str = "v1") -> None:
        if version not in POLICIES:
            raise ValueError(f"unknown policy version {version!r}; choose one of {sorted(POLICIES)}")
        self.spec = POLICIES[version]
        self.version = version
        self.limit = self.spec.limit
        # Per-request budget (v2): amounts already allowed, reserved atomically at decision
        # time. The model can issue several refund calls in parallel, so check-and-reserve
        # must be one step.
        self._reserved: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return f"refund-policy-{self.version}"

    def _decide(self, tool_name: str, args: Any) -> str | None:
        if tool_name != "issue_refund":
            return None
        try:
            amount = float((args or {}).get("amount", 0))
        except (TypeError, ValueError):
            return f"{self.name}: refund amount is missing or not a number"
        if self.spec.scope == "call":
            if amount > self.limit:
                return (
                    f"{self.name}: refund of ${amount:,.2f} exceeds the ${self.limit:,.2f} per-refund limit "
                    "for support agents; supervisor approval is required"
                )
            return None
        request_id = refunds.current_request.get() or "no-request"
        with self._lock:
            spent = self._reserved.get(request_id, 0.0)
            if spent + amount > self.limit + 1e-9:
                return (
                    f"{self.name}: refund of ${amount:,.2f} would bring this request's refunds to "
                    f"${spent + amount:,.2f}, above the ${self.limit:,.2f} per-request budget; "
                    "supervisor approval is required"
                )
            self._reserved[request_id] = spent + amount
        return None

    def __call__(self, tool_name: str, args: Any) -> str | None:
        started = time.perf_counter()
        reason = self._decide(tool_name, args)
        if tool_name == "issue_refund":
            metrics.record_decision(reason is None, time.perf_counter() - started)
        return reason

    def release(self, request_id: str) -> None:
        """Forget a finished request's budget."""
        with self._lock:
            self._reserved.pop(request_id, None)

    def register(self) -> None:
        nemo_relay.guardrails.register_tool_conditional_execution(self.name, 10, self)
        log.info("Registered Relay guardrail %s (%s)", self.name, self.spec.summary)


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
