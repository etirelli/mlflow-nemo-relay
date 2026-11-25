"""Egress probe: run INSIDE the sandbox to show what the policy refuses.

    openshell sandbox exec -n uc2-agent-v1 -- python -m support_agent.egress_probe

Each target is ``METHOD URL``. Prints one line per target, ``BLOCKED: ...`` or
``ALLOWED: ...``. It uses the same interpreter as the agent, so the same policy
rules apply. Nothing is sent that could move money: the credit request has an
invalid body (amount 0), so even if it got through, the service would reject it
with HTTP 400 and the probe would report ALLOWED. MLflow is probed too: the
agent's traces leave through the OpenShell agent trace relay, so the agent
itself has no route to MLflow.
"""

from __future__ import annotations

import os
import sys

import httpx

PAYMENTS = os.environ.get("PAYMENTS_URL", "http://host.openshell.internal:8090").rstrip("/")
MLFLOW = os.environ.get("MLFLOW_PROBE_URL", "http://host.openshell.internal:5000").rstrip("/")
DEFAULT_TARGETS = [
    "GET https://pypi.org/simple/",
    f"POST {PAYMENTS}/v1/credits",
    f"GET {PAYMENTS}/v1/ledger",
    f"POST {MLFLOW}/v1/traces",
]


def probe(target: str) -> str:
    method, url = target.split(" ", 1)
    try:
        response = httpx.request(method, url, json={"customer_id": "PROBE", "amount": 0}, timeout=5)
    except httpx.ProxyError as exc:
        return f"BLOCKED: {target} -> proxy refused ({exc})"
    except httpx.TransportError as exc:
        return f"BLOCKED: {target} -> {type(exc).__name__}: {exc}"
    if response.status_code == 403 and "policy_denied" in response.text:
        return f"BLOCKED: {target} -> {response.text[:200]}"
    return f"ALLOWED: {target} -> HTTP {response.status_code}"


def main() -> None:
    results = [probe(t) for t in (sys.argv[1:] or DEFAULT_TARGETS)]
    print("\n".join(results))
    sys.exit(0 if all(r.startswith("BLOCKED") for r in results) else 1)


if __name__ == "__main__":
    main()
