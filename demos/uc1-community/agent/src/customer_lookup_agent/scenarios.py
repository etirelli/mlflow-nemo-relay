"""Send the use case 1 demo scenarios to one or both agents.

python -m customer_lookup_agent.scenarios                       # both agents
python -m customer_lookup_agent.scenarios --agent http://localhost:8000
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

from customer_lookup_agent.customer_db import SUCCESS_SSN, TIMEOUT_SSN

SCENARIOS = [
    ("successful lookup", f"Please look up the customer with SSN {SUCCESS_SSN}."),
    ("controlled failure (timeout)", f"Can you check the account for SSN {TIMEOUT_SSN}?"),
]


def default_agents() -> list[str]:
    raw = os.environ.get("DEMO_AGENT_URLS", "http://agent-redacted:8000,http://agent-baseline:8000")
    return [u.strip() for u in raw.split(",") if u.strip()]


def run(agent_url: str, client: httpx.Client) -> bool:
    ok = True
    info = client.get(f"{agent_url}/api/info").json()
    print(f"\n=== {agent_url}  (relay_mode={info['relay_mode']}, llm={info['llm_model']})")
    for label, message in SCENARIOS:
        print(f"\n--> {label}\n    user: {message}")
        r = client.post(f"{agent_url}/api/chat", json={"message": message})
        if r.status_code != 200:
            print(f"    !! HTTP {r.status_code}: {r.text}")
            ok = False
            continue
        body = r.json()
        for call in body["tool_calls"]:
            print(f"    tool {call['name']}: status={call['status']}")
        if not body["tool_calls"]:
            print("    !! the model did not call the tool (check the LLM supports tool calling)")
            ok = False
        print(f"    agent: {body['reply']}")
        print(f"    took {body['duration_ms']} ms, trace: {body['mlflow_trace_url']}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--agent", action="append", help="agent base URL (repeatable)")
    args = parser.parse_args()
    with httpx.Client(timeout=180) as client:
        results = [run(url, client) for url in (args.agent or default_agents())]
    print(
        "\nNote: the agent API returns real values (the caller is entitled to them);"
        "\nonly the exported telemetry is sanitized."
    )
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
