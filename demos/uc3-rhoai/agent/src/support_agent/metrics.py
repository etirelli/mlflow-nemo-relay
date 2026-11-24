"""Prometheus metrics: the latency and resource side of a policy comparison.

Exposed on ``GET /metrics`` and scraped by Prometheus (compose service
``prometheus``). Every series carries the policy version as a label, so the
same queries compare policies under the same load:

* ``uc3_chat_request_seconds``        end-to-end agent request latency (histogram)
* ``uc3_guardrail_eval_seconds``      time spent inside the Relay policy callback (histogram)
* ``uc3_guardrail_decisions_total``   decisions by outcome (allowed / rejected)
* ``process_cpu_seconds_total``,
  ``process_resident_memory_bytes``   the agent process's CPU and memory (built-in collector)

The process collector is per container: each policy version runs in its own
service, so its CPU and memory are attributable to that policy.
"""

from __future__ import annotations

import os

from prometheus_client import Counter, Histogram

POLICY = os.environ.get("POLICY_VERSION", "v1")

REQUEST_SECONDS = Histogram(
    "uc3_chat_request_seconds",
    "End-to-end agent request latency",
    ["policy"],
    buckets=(0.25, 0.5, 1, 2, 4, 8, 15, 30, 60, 120),
)
GUARDRAIL_SECONDS = Histogram(
    "uc3_guardrail_eval_seconds",
    "Time spent inside the Relay refund policy callback",
    ["policy"],
    buckets=(1e-6, 5e-6, 1e-5, 5e-5, 1e-4, 5e-4, 1e-3, 5e-3, 1e-2),
)
DECISIONS = Counter(
    "uc3_guardrail_decisions_total",
    "Relay refund policy decisions",
    ["policy", "decision"],
)


def record_decision(allowed: bool, seconds: float) -> None:
    GUARDRAIL_SECONDS.labels(POLICY).observe(seconds)
    DECISIONS.labels(POLICY, "allowed" if allowed else "rejected").inc()


# Create every series at zero on startup. Otherwise a series appears only at its
# first observation, and Prometheus `increase()` misses the increments before it.
REQUEST_SECONDS.labels(POLICY)
GUARDRAIL_SECONDS.labels(POLICY)
for _decision in ("allowed", "rejected"):
    DECISIONS.labels(POLICY, _decision)
