"""Egress probe: run INSIDE the sandbox to show that the internet and MLflow are unreachable.

    openshell sandbox exec -n uc1-agent-redacted -- python -m customer_lookup_agent.egress_probe

Prints one line, ``BLOCKED: ...`` or ``ALLOWED: ...``, for each URL. It uses the
same interpreter as the agent, so it is subject to the same policy rules.
"""

from __future__ import annotations

import sys

import httpx

DEFAULT_URLS = [
    "https://pypi.org/simple/",
    "https://partner-crm.example.com/v1/customers/notify",
    "http://host.openshell.internal:5000/v1/traces",
]


def probe(url: str) -> str:
    try:
        response = httpx.get(url, timeout=5)
    except httpx.ProxyError as exc:
        return f"BLOCKED: {url} -> proxy refused ({exc})"
    except httpx.TransportError as exc:
        return f"BLOCKED: {url} -> {type(exc).__name__}: {exc}"
    if response.status_code == 403 and "policy_denied" in response.text:
        return f"BLOCKED: {url} -> {response.text[:200]}"
    return f"ALLOWED: {url} -> HTTP {response.status_code}"


def main() -> None:
    results = [probe(url) for url in (sys.argv[1:] or DEFAULT_URLS)]
    print("\n".join(results))
    sys.exit(0 if all(r.startswith("BLOCKED") for r in results) else 1)


if __name__ == "__main__":
    main()
