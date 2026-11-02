"""Customer lookup tool used by the agent.

The tool needs the full SSN to do its job, so the SSN is a tool argument.
NeMo Relay never changes what the tool receives. Its pii_redaction plugin
sanitizes only the telemetry copies of the arguments, results, and errors.

The tool deliberately echoes the SSN in its result and in its error messages.
Many real services do this, and it lets the demo validate the product gap
"echoed inputs in results and error details".
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import ToolException, tool

from customer_lookup_agent.customer_db import CustomerNotFoundError, fetch_customer
from customer_lookup_agent.settings import get_settings


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


# Return ToolException messages to the model as ToolMessage(status="error").
# Relay marks the tool span status ERROR, and the agent can explain the failure.
lookup_customer.handle_tool_error = True

TOOLS = [lookup_customer]
