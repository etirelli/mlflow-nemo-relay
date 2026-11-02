"""Synthetic customer records service.

Every record here is synthetic. The SSNs use area numbers in the 900 range with
group numbers below 50. The SSA never issues that range, and the IRS does not use
it for ITINs, so these values cannot belong to a real person.

The service simulates a slow downstream system so the demo can show a
controlled failure (a tool timeout) alongside a successful lookup.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CustomerRecord:
    customer_id: str
    name: str
    ssn: str
    plan: str
    status: str
    open_tickets: int
    # Simulated backend latency for this record, in seconds.
    latency_seconds: float = 0.2

    def public_view(self) -> dict:
        data = asdict(self)
        data.pop("latency_seconds")
        return data


CUSTOMERS: dict[str, CustomerRecord] = {
    r.ssn: r
    for r in [
        CustomerRecord("CUST-1001", "Ada Synthetic", "900-12-0001", "Premium", "active", 0),
        CustomerRecord("CUST-1002", "Grace Example", "900-12-0002", "Standard", "active", 2),
        CustomerRecord("CUST-1003", "Alan Placeholder", "900-12-0003", "Basic", "suspended", 1),
        # This record lives on a "legacy shard" that never answers in time,
        # which produces the controlled timeout failure in the demo.
        CustomerRecord(
            "CUST-1004", "Linus Testcase", "900-34-0004", "Premium", "active", 0, latency_seconds=30
        ),
    ]
}

# SSNs used by the demo scenarios and the verification script.
SUCCESS_SSN = "900-12-0001"
TIMEOUT_SSN = "900-34-0004"
ALL_SYNTHETIC_SSNS = sorted(CUSTOMERS)


class CustomerNotFoundError(LookupError):
    pass


async def fetch_customer(ssn: str) -> CustomerRecord:
    """Query the simulated customer records backend."""
    record = CUSTOMERS.get(ssn.strip())
    await asyncio.sleep(record.latency_seconds if record else 0.1)
    if record is None:
        raise CustomerNotFoundError(f"No customer record matches SSN {ssn}")
    return record
