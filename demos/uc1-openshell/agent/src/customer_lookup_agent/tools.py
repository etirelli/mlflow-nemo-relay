"""Tools used by the customer lookup agent.

``lookup_customer`` needs the full SSN to do its job, so the SSN is a tool
argument. NeMo Relay never changes what the tool receives. Its pii_redaction
plugin sanitizes only the telemetry copies of the arguments, results, and errors.

``notify_partner_crm`` sends a customer record to an external partner system.
It stands in for any tool that moves data out of the agent: an integration
that a developer added, or one that a prompt injection talks the agent into
using. The OpenShell sandbox policy does not allow that destination, so the
connection is refused at the sandbox boundary, *before* any data leaves.
The tool turns the refusal into a readable error, so MLflow shows a failed
tool call with the reason.

Both tools deliberately echo the SSN in their errors. Many real services do
this, and it lets the demo validate the product gap "echoed inputs in results
and error details".
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlparse

import httpx
from langchain_core.tools import ToolException, tool

from customer_lookup_agent.customer_db import CustomerNotFoundError, fetch_customer
from customer_lookup_agent.settings import get_settings

# Error prefix used when OpenShell (or another egress control) refuses the connection.
EGRESS_BLOCKED = "EgressBlocked"


@tool
async def lookup_customer(ssn: str) -> dict:
    """Look up a customer account by Social Security number (format NNN-NN-NNNN).

    Returns the customer's id, name, plan, account status, and open ticket count.
    """
    timeout = get_settings().tool_timeout_seconds
    try:
        record = await asyncio.wait_for(fetch_customer(ssn), timeout=timeout)
    except TimeoutError as exc:
        # Controlled failure: the records backend did not answer in time.
        raise ToolException(
            f"TimeoutError: customer records service did not respond within {timeout:.1f}s "
            f"while looking up SSN {ssn}. The record may be on the legacy shard; retry later."
        ) from exc
    except CustomerNotFoundError as exc:
        raise ToolException(f"NotFound: {exc}") from exc
    return {"found": True, **record.public_view()}


def _denial_detail(response: httpx.Response) -> str:
    """Summarize an OpenShell proxy error body: {"error", "detail", "reason"}."""
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return f"HTTP {response.status_code}"
    parts = [str(body.get(k)) for k in ("error", "detail", "reason") if body.get(k)]
    return "; ".join(parts) or f"HTTP {response.status_code}"


@tool
async def notify_partner_crm(customer_id: str, ssn: str) -> dict:
    """Send a customer's record to the external partner CRM.

    Use only when the user explicitly asks to sync or share a customer with the
    partner CRM. Pass the customer_id and ssn returned by lookup_customer.
    """
    settings = get_settings()
    url = settings.partner_crm_url
    target = urlparse(url).netloc or url
    payload = {"customer_id": customer_id, "ssn": ssn, "source": "uc1-customer-lookup-agent"}
    try:
        # trust_env=True (the default) uses the sandbox's egress proxy settings.
        async with httpx.AsyncClient(timeout=settings.partner_crm_timeout_seconds) as client:
            response = await client.post(url, json=payload)
    except httpx.ProxyError as exc:
        # An explicit egress proxy refused CONNECT (403). Not how OpenShell 0.1.9 behaves
        # on Podman, which intercepts transparently (next branch), but kept for proxies.
        raise ToolException(
            f"{EGRESS_BLOCKED}: the sandbox egress proxy refused the connection to {target} "
            f"({exc}). OpenShell policy does not allow this destination. "
            f"The record for SSN {ssn} was not sent."
        ) from exc
    except httpx.TransportError as exc:
        # OpenShell 0.1.9 (observed on Podman): the supervisor intercepts the connection
        # transparently and refuses it, so the client sees a ConnectError / EACCES. The
        # sandbox log records `DENIED ... [reason:transparent_tcp_policy_denied]`.
        raise ToolException(
            f"{EGRESS_BLOCKED}: could not connect to {target} ({type(exc).__name__}: {exc}). "
            f"The record for SSN {ssn} was not sent."
        ) from exc

    if response.status_code == 403 and "policy_denied" in response.text:
        # Plain HTTP through the supervisor: the denial comes back as a JSON body.
        raise ToolException(
            f"{EGRESS_BLOCKED}: OpenShell policy denied the request to {target} "
            f"({_denial_detail(response)}). The record for SSN {ssn} was not sent."
        )
    if response.is_error:
        raise ToolException(
            f"PartnerCRMError: {target} answered HTTP {response.status_code} for the record with SSN {ssn}."
        )
    return {"synced": True, "customer_id": customer_id, "partner_status": response.status_code}


# Return ToolException messages to the model as ToolMessage(status="error").
# Relay marks the tool span status ERROR, and the agent can explain the failure.
lookup_customer.handle_tool_error = True
notify_partner_crm.handle_tool_error = True

TOOLS = [lookup_customer, notify_partner_crm]
