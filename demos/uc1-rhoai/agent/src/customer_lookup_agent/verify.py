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
  * LLM protection (opt-in per request): the LLM saw SSN references instead
    of SSNs, and the lookup still got the real value.
  * Authenticated routing (OpenShift AI): OTLP export without a token is
    rejected, and the agent's service account token cannot write to an
    experiment in the same workspace that its Role does not name.

Runs on the laptop against the MLflow gateway URL, authenticated with the
user's OpenShift token (`make verify` sets everything up):

    MLFLOW_TRACKING_URI=https://<gateway>/mlflow MLFLOW_TRACKING_TOKEN=$(oc whoami -t) \
    MLFLOW_WORKSPACE=<namespace> AGENT_TOKEN=$(oc create token uc1-agent) \
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
from customer_lookup_agent.llm_protection import MODEL_NOTE

SSN_PATTERN = re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b")
REDACTION_MARKER = "[REDACTED-SSN]"
SSN_REFERENCE = "SSN_REF_"
# MLflow may keep span metadata as a JSON-encoded attribute, so match escaped quotes too.
PROTECTION_METADATA = re.compile(r'demo\.llm_protection[\\"]*\s*:\s*[\\"]*on\b')
ROOT_SPAN = "customer-lookup-request"
LOOKUP_TOOL = "lookup_customer"


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


def is_protected(trace) -> bool:
    """True when the request opted in to LLM protection (root span metadata ``demo.llm_protection``)."""
    return PROTECTION_METADATA.search(trace.to_json()) is not None


def llm_inputs(traces) -> list[str]:
    """LLM span inputs, without the model note: the note itself names an example reference."""
    return [
        json.dumps(s.inputs, default=str).replace(MODEL_NOTE, "")
        for t in traces
        for s in t.data.spans
        if s.span_type == "LLM"
    ]


def check_llm_protection(report: Report, traces) -> None:
    protected = [t for t in traces if is_protected(t)]
    seen = llm_inputs(protected)
    lookups = [s for t in protected for s in t.data.spans if s.span_type == "TOOL" and s.name == LOOKUP_TOOL]
    report.check(
        "With LLM protection on, the LLM saw SSN references only, and the lookup still succeeded",
        bool(seen)
        and all(SSN_REFERENCE in i and not find_ssns(i) and REDACTION_MARKER not in i for i in seen)
        and any(s.status.status_code == "OK" for s in lookups),
        f"{len(seen)} LLM request(s) across {len(protected)} protected trace(s); "
        f"{LOOKUP_TOOL} statuses: {[s.status.status_code for s in lookups]}",
    )


def check_routing(report: Report, client: MlflowClient, tracking_uri: str, experiment_id: str) -> None:
    url = tracking_uri.rstrip("/") + "/v1/traces"
    workspace = os.environ.get("MLFLOW_WORKSPACE", "")
    headers = {
        "content-type": "application/x-protobuf",
        "x-mlflow-workspace": workspace,
        "x-mlflow-experiment-id": experiment_id,
    }
    # Without a token. Through the OpenShift AI gateway, unauthenticated requests are
    # redirected to the OpenShift login page (302); in-cluster, MLflow answers 401.
    r = httpx.post(url, headers=headers, content=b"", timeout=10, follow_redirects=False)
    report.check(
        "OTLP export without credentials is rejected",
        r.status_code in (302, 401, 403),
        f"POST /v1/traces without a token -> HTTP {r.status_code}",
    )
    agent_token = os.environ.get("AGENT_TOKEN")
    other = client.get_experiment_by_name(os.environ.get("NOT_GRANTED_EXPERIMENT", "uc1-rhoai-not-granted"))
    if agent_token and other is not None:
        r = httpx.post(
            url,
            headers={
                **headers,
                "x-mlflow-experiment-id": other.experiment_id,
                "authorization": f"Bearer {agent_token}",
            },
            content=b"",
            timeout=10,
        )
        report.check(
            "The agent's service account cannot write to an experiment its Role does not name",
            r.status_code == 403,
            f"POST /v1/traces to {other.name!r} (same workspace) as the agent -> HTTP {r.status_code}",
        )
    else:
        print("  (AGENT_TOKEN or the not-granted experiment is missing; least-privilege check skipped)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tracking-uri", default=os.environ.get("MLFLOW_TRACKING_URI"), required=False)
    parser.add_argument(
        "--redacted-experiment", default=os.environ.get("REDACTED_EXPERIMENT", "uc1-rhoai-redacted")
    )
    parser.add_argument(
        "--baseline-experiment", default=os.environ.get("BASELINE_EXPERIMENT", "uc1-rhoai-baseline")
    )
    parser.add_argument("--telemetry-dir", default=os.environ.get("EVIDENCE_DIR", "telemetry"))
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
        check_llm_protection(report, traces)

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
        check_routing(report, client, args.tracking_uri, exp_id)

    passed = sum(p for _, p, _ in report.results)
    print(f"\n{passed}/{len(report.results)} checks passed.")
    sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
