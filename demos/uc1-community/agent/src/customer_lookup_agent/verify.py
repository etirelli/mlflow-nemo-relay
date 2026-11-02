"""Automated verification of the use case 1 success criteria.

Reads traces back from MLflow (as an admin) and checks:

  * Both lookup outcomes are visible: a TOOL span with status OK and one with ERROR.
  * Each tool span keeps its place in the agent run (parent chain up to the
    request root span) and has a non-zero duration.
  * The failure remains understandable: the error output still says what failed.
  * No synthetic SSN appears anywhere in the exported traces of the redacted
    experiment, or in the redacted ATOF file, and redaction markers are present.
  * Control: the baseline experiment DOES contain the SSNs, which proves the
    check above is meaningful.
  * Authenticated routing: OTLP export without credentials is rejected, and the
    agent's service account cannot write to an experiment it was not granted.

    python -m customer_lookup_agent.verify
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from mlflow import MlflowClient

from customer_lookup_agent.customer_db import ALL_SYNTHETIC_SSNS

SSN_PATTERN = re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b")
REDACTION_MARKER = "[REDACTED-SSN]"
ROOT_SPAN = "customer-lookup-request"


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
    """Known synthetic SSNs (dashed or bare digits) plus any other NNN-NN-NNNN value."""
    hits = [s for s in ALL_SYNTHETIC_SSNS if s in text or s.replace("-", "") in text]
    hits += [m for m in SSN_PATTERN.findall(text) if m not in hits]
    return sorted(set(hits))


def load_traces(client: MlflowClient, experiment_name: str):
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        return None, []
    traces = client.search_traces(locations=[experiment.experiment_id], max_results=500)
    return experiment.experiment_id, traces


def check_trace_structure(report: Report, traces) -> None:
    tool_spans = []
    for trace in traces:
        by_id = {s.span_id: s for s in trace.data.spans}
        for span in trace.data.spans:
            if span.span_type == "TOOL":
                tool_spans.append((trace, span, by_id))

    ok_spans = [t for t in tool_spans if t[1].status.status_code == "OK"]
    err_spans = [t for t in tool_spans if t[1].status.status_code == "ERROR"]
    report.check(
        "MLflow shows a successful tool call (TOOL span, status OK)",
        bool(ok_spans),
        f"{len(ok_spans)} OK tool span(s) across {len(traces)} trace(s)",
    )
    report.check(
        "MLflow shows a failed tool call (TOOL span, status ERROR)",
        bool(err_spans),
        f"{len(err_spans)} ERROR tool span(s)",
    )

    def chain_to_root(span, by_id) -> list[str]:
        names, current = [], span
        while current is not None:
            names.append(current.name)
            current = by_id.get(current.parent_id) if current.parent_id else None
        return names

    chains = [chain_to_root(span, by_id) for _, span, by_id in tool_spans]
    parented = [c for c in chains if c[-1] == ROOT_SPAN and len(c) > 2]
    report.check(
        "Tool spans keep their place in the agent run (parent chain to the request root)",
        bool(tool_spans) and len(parented) == len(tool_spans),
        " <- ".join(chains[0]) if chains else "no tool spans",
    )
    durations = [(s.end_time_ns - s.start_time_ns) / 1e6 for _, s, _ in tool_spans]
    report.check(
        "Tool spans carry useful timing",
        bool(durations) and all(d > 0 for d in durations),
        ", ".join(f"{d:.0f} ms" for d in durations[:6]),
    )
    if err_spans:
        output = json.dumps(err_spans[0][1].outputs, default=str)
        report.check(
            "The failure stays understandable after redaction",
            "TimeoutError" in output and "did not respond" in output,
            output[:200],
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
            headers={**headers, "x-mlflow-experiment-id": "0"},  # the Default experiment, not granted
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
    parser.add_argument(
        "--redacted-experiment", default=os.environ.get("REDACTED_EXPERIMENT", "uc1-customer-lookup-redacted")
    )
    parser.add_argument(
        "--baseline-experiment", default=os.environ.get("BASELINE_EXPERIMENT", "uc1-customer-lookup-baseline")
    )
    parser.add_argument("--telemetry-dir", default=os.environ.get("RELAY_TELEMETRY_DIR", "/app/telemetry"))
    args = parser.parse_args()

    client = MlflowClient(tracking_uri=args.tracking_uri)
    report = Report()

    print(f"\nRedacted experiment: {args.redacted_experiment}")
    exp_id, traces = load_traces(client, args.redacted_experiment)
    report.check("Redacted experiment has traces", bool(traces), f"{len(traces)} trace(s)")
    if traces:
        check_trace_structure(report, traces)
        blobs = {t.info.trace_id: t.to_json() for t in traces}
        leaks = {tid: find_ssns(b) for tid, b in blobs.items() if find_ssns(b)}
        report.check(
            "No SSN appears in exported MLflow traces (spans, attributes, inputs/outputs, previews)",
            not leaks,
            f"leaks: {leaks}" if leaks else f"scanned {sum(map(len, blobs.values()))} bytes",
        )
        markers = sum(b.count(REDACTION_MARKER) for b in blobs.values())
        report.check(
            "Redaction markers are present (sanitizer ran, data was not just missing)",
            markers > 0,
            f"{markers} occurrence(s) of {REDACTION_MARKER}",
        )

    atof = Path(args.telemetry_dir) / "atof-redacted.jsonl"
    if atof.exists():
        hits = find_ssns(atof.read_text())
        report.check(
            "No SSN appears in the redacted Relay ATOF event file", not hits, f"{atof}: {hits or 'clean'}"
        )

    print(f"\nBaseline experiment (control, no redaction): {args.baseline_experiment}")
    _, base_traces = load_traces(client, args.baseline_experiment)
    if base_traces:
        hits = sum(len(SSN_PATTERN.findall(t.to_json())) for t in base_traces)
        report.check(
            "Control: without Relay redaction, the SSN DOES leak into MLflow",
            hits > 0,
            f"{hits} SSN occurrence(s) across {len(base_traces)} baseline trace(s)",
        )
    else:
        print("  (no baseline traces; skipped)")

    if exp_id:
        print("\nAuthenticated routing")
        check_routing(report, args.tracking_uri, exp_id)

    passed = sum(p for _, p, _ in report.results)
    print(f"\n{passed}/{len(report.results)} checks passed.")
    sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
