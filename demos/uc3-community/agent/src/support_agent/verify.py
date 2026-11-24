"""Automated verification of the use case 3 success criteria.

Same agent, three refund policy versions. Reads traces and evaluation runs back
from MLflow, and metrics from Prometheus, and checks:

Policy decisions in MLflow
  * all three policies traced with the same agent; decisions exported under the
    versioned policy name, with the version in every reason; blocked refunds
    never executed; v2's budget and v3's over-strict limit are visible.
Evaluation (proposal: compare correct blocks, false blocks, prohibited actions
allowed, and task completion; latency and resources under equivalent load)
  * every policy run has the four rates and Prometheus latency/resource metrics,
    under the same load; the rollout gate promotes v2 and rejects v3.
Prometheus
  * all policy services scraped; decision counters per policy.
Carried over from UC1
  * no SSN in exported telemetry; authenticated, least-privilege routing.

    python -m support_agent.verify
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from mlflow import MlflowClient

from support_agent.customer_db import ALL_SYNTHETIC_SSNS

SSN_PATTERN = re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b")
POLICY_PREFIX = "refund-policy-"
BUSINESS_LIMIT = float(os.environ.get("REFUND_LIMIT", "500"))


@dataclass
class Report:
    results: list[tuple[str, bool, str]] = field(default_factory=list)

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.results.append((name, passed, detail))
        mark = "\033[32mPASS\033[0m" if passed else "\033[31mFAIL\033[0m"
        print(f"  [{mark}] {name}" + (f"\n         {detail}" if detail else ""))

    @property
    def ok(self) -> bool:
        return all(p for _, p, _ in self.results)


def find_ssns(text: str) -> list[str]:
    hits = [s for s in ALL_SYNTHETIC_SSNS if s in text or s.replace("-", "") in text]
    hits += [m for m in SSN_PATTERN.findall(text) if m not in hits]
    return sorted(set(hits))


def attr(span, key: str):
    value = span.attributes.get(key)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def guardrail_spans(trace):
    return [s for s in trace.data.spans if s.name.startswith(POLICY_PREFIX)]


def agent_version(trace) -> str | None:
    for s in trace.data.spans:
        if s.parent_id is None:
            return attr(s, "demo.agent_version") or (s.attributes.get("metadata") or {}).get(
                "demo.agent_version"
            )
    blob = trace.to_json()
    m = re.search(r'demo\.agent_version\\?"\s*:\s*\\?"(v\d)', blob)
    return m.group(1) if m else None


def policy_of(trace) -> str | None:
    """The policy version that served this trace (from its guardrail spans or attributes)."""
    for s in trace.data.spans:
        if s.name.startswith(POLICY_PREFIX):
            return s.name.removeprefix(POLICY_PREFIX)
    m = re.search(r"refund-policy-(v\d)", trace.to_json())
    return m.group(1) if m else None


def amount_of(reason: str) -> float | None:
    m = re.search(r"refund of \$([\d,]+(?:\.\d+)?)", reason)
    return float(m.group(1).replace(",", "")) if m else None


def check_guardrails(report: Report, traces) -> None:
    by_policy: dict[str, list] = defaultdict(list)
    for t in traces:
        by_policy[policy_of(t) or "?"].append(t)
    versions = {agent_version(t) for t in traces}
    report.check(
        "All three policy versions are traced, with the same (fixed) agent",
        {"v1", "v2", "v3"} <= by_policy.keys() and versions <= {"v1", None},
        ", ".join(f"{p}: {len(ts)}" for p, ts in sorted(by_policy.items()))
        + f"; agent versions: {sorted(map(str, versions))}",
    )

    decisions = [(t, g) for t in traces for g in guardrail_spans(t)]
    names = sorted({g.name for _, g in decisions})
    rejected = [(t, g) for t, g in decisions if attr(g, "nemo_relay.end.data.rejected") is True]
    report.check(
        "Each decision is exported under its versioned policy name",
        {"refund-policy-v1", "refund-policy-v2", "refund-policy-v3"} <= set(names),
        f"{len(decisions)} decision(s), {len(rejected)} rejected; policies: {names}",
    )
    stamped = [
        g
        for _, g in rejected
        if str(attr(g, "nemo_relay.end.data.rejection_reason") or "").startswith(g.name)
    ]
    report.check(
        "Every rejection carries the policy version in its reason",
        bool(rejected) and len(stamped) == len(rejected),
        f"{len(stamped)}/{len(rejected)}",
    )

    leaks = []
    for t, g in rejected:
        siblings = [s for s in t.data.spans if s.parent_id == g.parent_id and s.span_type == "TOOL"]
        executed = [s for s in siblings if s.name == "issue_refund"]
        allowed_here = [
            x
            for x in guardrail_spans(t)
            if x.parent_id == g.parent_id and attr(x, "nemo_relay.end.data.allowed") is True
        ]
        if len(executed) > len(allowed_here):
            leaks.append(t.info.trace_id)
    report.check(
        "Blocked refunds did not execute (no executed tool span for a rejected call)",
        not leaks,
        f"{len(rejected)} rejection(s) checked" + (f"; violations in {leaks}" if leaks else ""),
    )

    budget = [
        g
        for _, g in rejected
        if g.name == "refund-policy-v2"
        and "per-request budget" in str(attr(g, "nemo_relay.end.data.rejection_reason"))
    ]
    report.check(
        "MLflow shows v2's per-request budget at work (a rejection v1 would not make)",
        bool(budget),
        str(attr(budget[0], "nemo_relay.end.data.rejection_reason"))[:160]
        if budget
        else "no budget rejection traced (run `make scenarios`)",
    )
    strict = [
        (g, a)
        for _, g in rejected
        if g.name == "refund-policy-v3"
        and (a := amount_of(str(attr(g, "nemo_relay.end.data.rejection_reason")))) is not None
        and a <= BUSINESS_LIMIT
    ]
    report.check(
        "MLflow shows v3 blocking a refund the business rule allows (a false block)",
        bool(strict),
        f"refund-policy-v3 rejected ${strict[0][1]:,.2f} (rule allows up to ${BUSINESS_LIMIT:,.0f})"
        if strict
        else "none traced",
    )


def check_evaluation(report: Report, client: MlflowClient, experiment_name: str) -> None:
    experiment = client.get_experiment_by_name(experiment_name)
    runs = {}
    if experiment is not None:
        for run in client.search_runs([experiment.experiment_id], order_by=["attributes.start_time DESC"]):
            runs.setdefault(run.data.params.get("policy_version"), run)
    if not {"v1", "v2", "v3"} <= runs.keys():
        report.check("Evaluation runs exist for all three policies", False, "run `make eval`")
        return
    m = {v: runs[v].data.metrics for v in ("v1", "v2", "v3")}
    rate_keys = ["correct_block_rate", "prohibited_allowed_rate", "false_block_rate", "task_completion_rate"]
    report.check(
        "Evaluation: each policy run has correct blocks, false blocks, prohibited allowed, task completion",
        all(k in m[v] for v in m for k in rate_keys),
        " | ".join(
            f"{v}: CB {m[v].get('correct_block_rate', 0):.0%} "
            f"PA {m[v].get('prohibited_allowed_rate', 0):.0%} "
            f"FB {m[v].get('false_block_rate', 0):.0%} TC {m[v].get('task_completion_rate', 0):.0%}"
            for v in m
        ),
    )
    res_keys = ["latency_p95_s", "cpu_seconds", "rss_max_mb"]
    report.check(
        "Evaluation: each policy run has latency and resource metrics from Prometheus",
        all(k in m[v] for v in m for k in res_keys),
        " | ".join(
            f"{v}: p95 {m[v].get('latency_p95_s', float('nan')):.1f}s "
            f"cpu {m[v].get('cpu_seconds', float('nan')):.1f}s "
            f"rss {m[v].get('rss_max_mb', float('nan')):.0f}MB"
            for v in m
        ),
    )
    counts = [m[v].get("labeled_requests", 0) for v in m]
    report.check(
        "Evaluation: equivalent load (same labeled requests per policy)",
        max(counts) - min(counts) <= 2 and min(counts) > 0,
        f"labeled requests: {dict(zip(m, counts, strict=True))}",
    )
    tags = {v: runs[v].data.tags.get("rollout_decision") for v in ("v2", "v3")}
    report.check(
        "Rollout gate: v2 (per-request budget) is PROMOTED",
        tags["v2"] == "PROMOTE",
        f"v2: {tags['v2']} ({runs['v2'].data.tags.get('rollout_reasons', '')}); "
        f"prohibited allowed v1 {m['v1'].get('prohibited_allowed_rate', 0):.0%} "
        f"-> v2 {m['v2'].get('prohibited_allowed_rate', 0):.0%}",
    )
    report.check(
        "Rollout gate: v3 (over-strict) is REJECTED for false blocks",
        tags["v3"] == "REJECT" and m["v3"].get("false_block_rate", 0) > m["v1"].get("false_block_rate", 0),
        f"v3: {tags['v3']} ({runs['v3'].data.tags.get('rollout_reasons', '')})",
    )


def check_prometheus(report: Report, prom_url: str) -> None:
    def q(query: str):
        try:
            return httpx.get(f"{prom_url}/api/v1/query", params={"query": query}, timeout=10).json()["data"][
                "result"
            ]
        except Exception as exc:  # noqa: BLE001
            print(f"  (Prometheus query failed: {exc})")
            return []

    up = {r["metric"].get("job"): r["value"][1] for r in q("up")}
    want = {f"agent-policy-{v}" for v in ("v1", "v2", "v3")}
    report.check(
        "Prometheus scrapes all three policy services",
        all(up.get(j) == "1" for j in want),
        str(dict(sorted(up.items()))),
    )
    decisions = q("sum by (policy, decision) (uc3_guardrail_decisions_total)")
    seen = sorted(
        f"{r['metric']['policy']}/{r['metric']['decision']}={float(r['value'][1]):.0f}" for r in decisions
    )
    report.check(
        "Prometheus has guardrail decision counters per policy",
        {r["metric"]["policy"] for r in decisions} >= {"v1", "v2", "v3"},
        ", ".join(seen) or "none",
    )


def check_routing(report: Report, tracking_uri: str, experiment_id: str) -> None:
    url = tracking_uri.rstrip("/") + "/v1/traces"
    headers = {"content-type": "application/x-protobuf", "x-mlflow-experiment-id": experiment_id}
    r = httpx.post(url, headers=headers, content=b"", timeout=10)
    report.check(
        "OTLP export without credentials is rejected",
        r.status_code in (401, 403),
        f"POST /v1/traces without auth -> HTTP {r.status_code}",
    )
    user, password = os.environ.get("AGENT_MLFLOW_USERNAME"), os.environ.get("AGENT_MLFLOW_PASSWORD")
    if user and password:
        r = httpx.post(
            url,
            headers={**headers, "x-mlflow-experiment-id": "0"},
            content=b"",
            auth=(user, password),
            timeout=10,
        )
        report.check(
            "The agent's service account cannot write to an experiment it was not granted",
            r.status_code == 403,
            f"POST /v1/traces to experiment 0 as {user!r} -> HTTP {r.status_code}",
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tracking-uri", default=os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
    parser.add_argument("--experiment", default=os.environ.get("TRACE_EXPERIMENT", "uc3-policy-validation"))
    parser.add_argument(
        "--eval-experiment", default=os.environ.get("EVAL_EXPERIMENT", "uc3-policy-validation-eval")
    )
    parser.add_argument(
        "--prometheus-url", default=os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
    )
    parser.add_argument("--telemetry-dir", default=os.environ.get("RELAY_TELEMETRY_DIR", "/app/telemetry"))
    args = parser.parse_args()

    client = MlflowClient(tracking_uri=args.tracking_uri)
    report = Report()
    experiment = client.get_experiment_by_name(args.experiment)
    traces = client.search_traces(locations=[experiment.experiment_id], max_results=500) if experiment else []

    print(f"\nPolicy decisions in MLflow: {args.experiment}")
    report.check("The trace experiment has traces", bool(traces), f"{len(traces)} trace(s)")
    if traces:
        check_guardrails(report, traces)

    print(f"\nEvaluation: {args.eval_experiment}")
    check_evaluation(report, client, args.eval_experiment)

    print(f"\nPrometheus: {args.prometheus_url}")
    check_prometheus(report, args.prometheus_url)

    print("\nCarried over from UC1")
    if traces:
        blobs = [t.to_json() for t in traces]
        leaks = sorted({s for b in blobs for s in find_ssns(b)})
        report.check(
            "No SSN appears in exported traces",
            not leaks,
            f"leaks: {leaks}" if leaks else f"scanned {sum(map(len, blobs))} bytes",
        )
    for f in sorted(Path(args.telemetry_dir).glob("atof-*.jsonl")):
        hits = find_ssns(f.read_text())
        report.check(f"No SSN in Relay's local event file {f.name}", not hits, str(hits or "clean"))
    if experiment:
        check_routing(report, args.tracking_uri, experiment.experiment_id)

    passed = sum(p for _, p, _ in report.results)
    print(f"\n{passed}/{len(report.results)} checks passed.")
    sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
