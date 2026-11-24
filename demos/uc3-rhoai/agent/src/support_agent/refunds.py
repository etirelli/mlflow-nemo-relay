"""Simulated refunds service with an auditable ledger.

Every refund that actually executes is appended to the ledger. The ledger is
how the demo proves that a refund blocked by the guardrail never ran: the
agent API returns the refunds executed during each request, and the
verification compares them with the guardrail decisions in MLflow.
"""

from __future__ import annotations

import contextvars
import threading
import time
import uuid
from dataclasses import asdict, dataclass

# The chat request that is currently running. Requests are handled concurrently
# (e.g. during evaluation), so refunds are attributed by request, not by position.
current_request: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_request", default=None)


@dataclass(frozen=True)
class Refund:
    refund_id: str
    customer_id: str
    amount: float
    reason: str
    executed_at: float
    request_id: str | None = None


_LEDGER: list[Refund] = []
_LOCK = threading.Lock()


def issue(customer_id: str, amount: float, reason: str) -> Refund:
    refund = Refund(
        f"RF-{uuid.uuid4().hex[:8].upper()}",
        customer_id,
        round(amount, 2),
        reason,
        time.time(),
        current_request.get(),
    )
    with _LOCK:
        _LEDGER.append(refund)
    return refund


def start_request() -> str:
    """Tag refunds executed from now on (in this context) with a new request id."""
    request_id = uuid.uuid4().hex
    current_request.set(request_id)
    return request_id


def executed_by(request_id: str) -> list[dict]:
    with _LOCK:
        return [asdict(r) for r in _LEDGER if r.request_id == request_id]


def total_executed() -> int:
    with _LOCK:
        return len(_LEDGER)
