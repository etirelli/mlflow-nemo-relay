"""Tools for the support agent.

The *policy* (refunds above the limit are blocked) lives in Relay and never
changes between agent versions. What changes is what the agent is told:

* v1 tools: ``lookup_customer`` and a plain ``issue_refund``. Nothing tells the
  model about the limit, so it attempts large refunds and gets blocked.
* v2 tools: ``issue_refund`` documents the limit, and a new
  ``request_supervisor_approval`` tool gives the agent a legitimate path for
  large refunds.
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import StructuredTool, ToolException, tool

from support_agent import refunds
from support_agent.customer_db import CustomerNotFoundError, fetch_customer
from support_agent.settings import get_settings


@tool
async def lookup_customer(ssn: str) -> dict:
    """Look up a customer account by Social Security number (format NNN-NN-NNNN).

    Returns the customer's id, name, plan, account status, and open ticket count.
    """
    timeout = get_settings().tool_timeout_seconds
    try:
        record = await asyncio.wait_for(fetch_customer(ssn), timeout=timeout)
    except TimeoutError as exc:
        raise ToolException(
            f"TimeoutError: customer records service did not respond within {timeout:.1f}s "
            f"while looking up SSN {ssn}. The record may be on the legacy shard; retry later."
        ) from exc
    except CustomerNotFoundError as exc:
        raise ToolException(f"NotFound: {exc}") from exc
    return {"found": True, **record.public_view()}


async def _issue_refund(customer_id: str, amount: float, reason: str) -> dict:
    if amount <= 0:
        raise ToolException(f"InvalidAmount: refund amount must be positive, got {amount}")
    refund = refunds.issue(customer_id, amount, reason)
    return {
        "refunded": True,
        "refund_id": refund.refund_id,
        "customer_id": customer_id,
        "amount": refund.amount,
    }


async def _request_supervisor_approval(customer_id: str, amount: float, reason: str) -> dict:
    return {
        "escalated": True,
        "ticket": f"SUP-{abs(hash((customer_id, amount, reason))) % 100000:05d}",
        "customer_id": customer_id,
        "amount": round(amount, 2),
        "next_step": "A supervisor will review the refund within one business day.",
    }


def build_tools(version: str) -> list:
    limit = get_settings().refund_limit
    if version == "v2":
        issue_refund = StructuredTool.from_function(
            coroutine=_issue_refund,
            name="issue_refund",
            description=(
                f"Issue a refund to a customer account. Support agents may only refund up to "
                f"${limit:,.0f} per request. For larger amounts do NOT call this tool and do not "
                "split the amount into several refunds: use request_supervisor_approval instead."
            ),
        )
        approval = StructuredTool.from_function(
            coroutine=_request_supervisor_approval,
            name="request_supervisor_approval",
            description=(
                f"Ask a supervisor to approve a refund above ${limit:,.0f}. "
                "Returns an escalation ticket. Use it instead of issue_refund for large refunds."
            ),
        )
        tools = [lookup_customer, issue_refund, approval]
    else:
        issue_refund = StructuredTool.from_function(
            coroutine=_issue_refund,
            name="issue_refund",
            description="Issue a refund to a customer account.",
        )
        tools = [lookup_customer, issue_refund]
    for t in tools:
        # ToolException -> ToolMessage(status="error"); Relay marks the span ERROR.
        t.handle_tool_error = True
    return tools
