"""Per-request record of the money movements the payments service confirmed.

The system of record is the payments service's ledger (``payments/app.py``),
which runs outside the sandbox. This module only remembers, per chat request,
which movements the service confirmed (HTTP 201), so the agent API can return
them with the reply. ``make verify`` cross-checks them with the real ledger.

Requests are handled concurrently (for example during evaluation), so
movements are attributed by request id (a context variable), not by position.
The request id also travels to the service as ``x-request-id``.
"""

from __future__ import annotations

import contextvars
import threading
import uuid

current_request: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_request", default=None)

_CONFIRMED: list[dict] = []
_LOCK = threading.Lock()


def start_request() -> str:
    """Tag movements confirmed from now on (in this context) with a new request id."""
    request_id = uuid.uuid4().hex
    current_request.set(request_id)
    return request_id


def record(entry: dict) -> None:
    """Remember a ledger entry the payments service returned for this request."""
    with _LOCK:
        _CONFIRMED.append({**entry, "request_id": entry.get("request_id") or current_request.get()})


def executed_by(request_id: str) -> list[dict]:
    with _LOCK:
        return [dict(e) for e in _CONFIRMED if e.get("request_id") == request_id]
