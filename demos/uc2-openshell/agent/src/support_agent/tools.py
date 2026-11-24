"""Tools for the support agent.

Two independent controls stand between the agent and the money:

* **NeMo Relay** (``policy.py``) checks each *tool call* against the refund
  policy before the tool runs: ``issue_refund`` above the limit is rejected,
  so no request ever leaves the process.
* **OpenShell** (``openshell/policy.yaml``) checks each *network request* the
  sandboxed process makes: the agent may call ``POST /v1/refunds`` on the
  payments service and nothing else there.

What the agent is told changes between versions; the controls never do.

* v1 tools: ``lookup_customer``, a plain ``issue_refund``, and
  ``apply_account_credit``. The credit tool was added by a developer as a
  "goodwill" helper. It posts straight to the payments service's credits
  endpoint, and the Relay refund policy does not cover it (the policy is
  keyed on ``issue_refund``). Nothing tells the model about the limit, so v1
  attempts large refunds, gets blocked by Relay, and may then reach for the
  credit tool, which the sandbox denies.
* v2 tools: ``issue_refund`` documents the limit, ``request_supervisor_approval``
  gives the agent a legitimate path for large refunds, and the credit tool is
  gone (MLflow showed that it never succeeds and is only used to get around
  the refund limit).
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlparse

import httpx
from langchain_core.tools import StructuredTool, ToolException, tool

from support_agent import refunds
from support_agent.customer_db import CustomerNotFoundError, fetch_customer
from support_agent.settings import get_settings

# Error prefix used when OpenShell (or another egress control) refuses the connection.
EGRESS_BLOCKED = "EgressBlocked"


def is_egress_denied(content: str) -> bool:
    return str(content).startswith(EGRESS_BLOCKED)


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


def _denial_detail(response: httpx.Response) -> str:
    """Summarize an OpenShell L7 denial body: {"error", "policy", "rule", "detail", ...}."""
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return f"HTTP {response.status_code}"
    keys = ("error", "policy", "rule", "detail", "reason")
    parts = [f"{k}={body[k]}" for k in keys if body.get(k)]
    return "; ".join(parts) or f"HTTP {response.status_code}"


async def _post_payment(path: str, payload: dict, what: str) -> dict:
    """POST to the payments service; turn sandbox denials into readable tool errors."""
    settings = get_settings()
    url = settings.payments_url.rstrip("/") + path
    target = f"{urlparse(url).netloc}{path}"
    headers = {
        "x-request-id": refunds.current_request.get() or "",
        "x-agent-version": settings.agent_version,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.payments_timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.ProxyError as exc:
        raise ToolException(
            f"{EGRESS_BLOCKED}: the sandbox egress proxy refused POST {target} ({exc}). "
            f"The {what} was not executed."
        ) from exc
    except httpx.TransportError as exc:
        # OpenShell 0.1.9 refuses a disallowed *host* transparently at TCP level.
        raise ToolException(
            f"{EGRESS_BLOCKED}: could not connect to {target} ({type(exc).__name__}: {exc}). "
            f"The {what} was not executed."
        ) from exc

    if response.status_code == 403 and "policy_denied" in response.text:
        # Allowed host, disallowed method/path: OpenShell's L7 engine answers itself,
        # with a JSON body that names the policy and the rule.
        raise ToolException(
            f"{EGRESS_BLOCKED}: OpenShell sandbox policy denied POST {target} "
            f"({_denial_detail(response)}). The {what} was not executed."
        )
    if response.is_error:
        raise ToolException(
            f"PaymentsError: POST {target} answered HTTP {response.status_code}: {response.text[:200]}"
        )
    entry = response.json()
    refunds.record(entry)
    return entry


async def _issue_refund(customer_id: str, amount: float, reason: str) -> dict:
    if amount <= 0:
        raise ToolException(f"InvalidAmount: refund amount must be positive, got {amount}")
    entry = await _post_payment(
        "/v1/refunds", {"customer_id": customer_id, "amount": amount, "reason": reason}, "refund"
    )
    return {"refunded": True, "refund_id": entry["id"], "customer_id": customer_id, "amount": entry["amount"]}


async def _apply_account_credit(customer_id: str, amount: float, reason: str) -> dict:
    if amount <= 0:
        raise ToolException(f"InvalidAmount: credit amount must be positive, got {amount}")
    entry = await _post_payment(
        "/v1/credits", {"customer_id": customer_id, "amount": amount, "reason": reason}, "account credit"
    )
    return {"credited": True, "credit_id": entry["id"], "customer_id": customer_id, "amount": entry["amount"]}


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
        credit = StructuredTool.from_function(
            coroutine=_apply_account_credit,
            name="apply_account_credit",
            description=(
                "Post a credit to a customer's account balance, for goodwill gestures or when "
                "a refund cannot be issued."
            ),
        )
        tools = [lookup_customer, issue_refund, credit]
    for t in tools:
        # ToolException -> ToolMessage(status="error"); Relay marks the span ERROR.
        t.handle_tool_error = True
    return tools
