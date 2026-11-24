# Product-gap validation and findings (UC2, OpenShell permutation)

Validated on 2026-11-24 with **NeMo Relay 0.11.0**, **MLflow 3.17.2**,
**OpenShell 0.1.9** (Homebrew gateway, Podman driver, Apple M2), LangGraph 1.2
/ LangChain 1.4, and GLM 5.3 (EnMaaS) as both the agent LLM and the judge.

The UC2 gaps and findings from [`uc2-community`](../../uc2-community/docs/product-gaps.md)
carry over unchanged: same agent, same Relay policy, same MLflow. This page
covers what the second enforcement layer adds.

## The agreed design, validated

> *OpenShell blocks the refund service's network path as a second layer next
> to Relay's `refund-limit-v1` guardrail. MLflow must show the two kinds of
> block (Relay `GUARDRAIL` rejection vs OpenShell egress denial) distinctly.*

| Item | Status | Evidence |
|---|---|---|
| Refunds go over HTTP to a payments service outside the sandbox | ✅ live | `payments` compose service; the agent calls `POST /v1/refunds` through the supervisor (`ALLOWED … [policy:payments_refunds engine:l7]`) |
| OpenShell allows only the refunds path on that service | ✅ live | `POST /v1/credits` and `GET /v1/ledger` from inside the sandbox → `403 {"error":"policy_denied","policy":"payments_refunds","rule":…}` |
| Relay block and OpenShell denial are distinct in MLflow | ✅ live | Relay: `GUARDRAIL` `rejected=true`, no `TOOL` span. OpenShell: `GUARDRAIL` `allowed=true` + `TOOL` `ERROR` with `EgressBlocked … policy=payments_refunds; rule=POST /v1/credits`. Tool failure: `TOOL` `ERROR` without `EgressBlocked`. |
| Both layers in one trace | ✅ live | v1 "refund $900, else credit it": Relay rejects `issue_refund`, then OpenShell denies `apply_account_credit` |
| Nothing refused ever executed | ✅ live | The payments ledger (system of record, read from the laptop) has no refund above $500 and no credit |
| The layers are independent | ✅ by design and live | Relay allowed the credit call (its policy is keyed on `issue_refund`); OpenShell had no opinion on the $900 refund (an allowed path) |
| The LLM key stays out of the sandbox | ✅ live | Provider profile with a path rule; the key is injected by the supervisor over TLS; not in `sandbox get` or the evidence |

## Findings

| # | Area | Finding | Impact | Suggestion |
|---|---|---|---|---|
| 1 | **OpenShell** | **A second request on a kept-alive plain-HTTP connection is dropped.** The L7 engine logs it as `ALLOWED … request_sequence:1`, but it never reaches the upstream. Seen with Relay's OTLP exporter to MLflow: MLflow's access log has no entry for the logged request. 6 of 32 traces lost their root spans, and in a follow-up test one trace of three was missing entirely. | **Silent telemetry loss** that looks like a Relay or MLflow bug. The policy log says the request was allowed. | Fix keep-alive handling in the L7 HTTP path (forward every request on the connection, and count `request_sequence`). Workaround in this demo: Relay sends `Connection: close` through `header_env`, which gives one connection per export. After the workaround: 6/6 sequential test traces complete, then 34/34 in the clean end-to-end run. `make verify` now checks completeness. |
| 2 | **OpenShell** | **L7 rules make denials readable.** A disallowed path on a host that has an L7 rule gets `403` with `{"error":"policy_denied","policy","rule","detail","layer":"l7"}`. A host with no rule at all is refused at TCP level (`EACCES`), with no reason (`uc1-openshell`). | Agents and MLflow can classify "blocked by sandbox policy" only for hosts under an L7 rule. | Document this pattern: put every backend the agent talks to under an L7 rule, even a one-path allow. For unknown hosts, the TCP-level refusal still needs a machine-readable signal (`uc1-openshell` finding). |
| 3 | **Relay** | **Per-tool guardrails don't follow the money.** `refund-limit-v1` inspects `issue_refund` only. A second tool that moves money (`apply_account_credit`) passes with `allowed=true`. | A developer adding a tool silently widens what the agent can do. The model *will* use it as a workaround: GLM 5.3 v1 did in the scenarios and in 2 of 12 evaluation cases. | Relay: policy targets by tool category or tag (for example "money movement") and a default-deny mode for tools that no policy has reviewed. The network layer catches this case only because the credit endpoint is a separate path. |
| 4 | **OpenShell + MLflow** | **The denial reaches MLflow only as the tool's error text.** The supervisor's decision (an OCSF event) isn't linked to the agent's span. The demo relies on the tool to parse the 403 body, and on `make evidence` to copy the sandbox log. | Fragile: a tool that swallows the body loses the reason. The sandbox log buffer is short ("log buffer contains only the last N lines"). | Propagate `traceparent` through the proxy and stamp it on the OCSF decision, or export OCSF over OTLP with the agent's trace context, so MLflow can show the decision span inside the trace. |
| 5 | **OpenShell** | **Provider profiles: `rules` and `access` are mutually exclusive** on an endpoint. With `rules`, the provider grants only the listed method and path (here `POST /v1/chat/completions`). | Good least privilege, but undocumented, and the linter error is the only hint. | Document it in the provider profile reference. |
| 6 | **OpenShell** | **Credential injection works with a Python OpenAI client over TLS.** `--credential LLM_API_KEY` stores the key. The sandbox sees a placeholder, and the supervisor substitutes it in `Authorization: Bearer`. | This resolves the `uc1-openshell` open item ("confirm placeholder substitution for the Python OpenAI client"). | — |
| 7 | **OpenShell** | **The MLflow password is still passed with `--env`.** `sandbox create` warns about it. | Same as `uc1-openshell`. MLflow basic auth needs a Basic header that Relay builds in-process, so a provider placeholder can't be substituted inside it. | The OpenShell agent trace relay with per-sandbox headers, or bearer-token auth to MLflow (RHOAI). To try in `uc2-rhoai-openshell`. |
| 8 | **OpenShell** | **Re-registering a provider profile isn't idempotent.** `provider profile lint` fails once the id exists on the gateway ("already exists"), and `provider profile update -f` needs the `resource_version` from an export. | Scripts can't just "apply" a profile file; `make up` failed the second time. | An `apply`-style command (create or update) or a lint mode that ignores the gateway. The demo imports once and offers `make provider-reset`. |
| 9 | **Demo design** | **The back-office API trusts its callers.** The payments service doesn't enforce the limit, on purpose. | Shows why both layers are needed. In production the service should also enforce its own limits (a third layer). | — |

## Upstream report candidates

- OpenShell: finding 1 (L7 keep-alive drop, with the logs from this run),
  finding 4 (decision ↔ trace correlation), findings 5 and 8 (profile docs and idempotency). Also the
  `uc1-openshell` items: no `policy lint`, `sandbox delete` without `--wait`,
  `forward start -d` holding stdout, and transparent denials without a reason.
- Relay: finding 3 (category- or tag-based targets, default deny), plus the
  `uc2-community` findings 1–4.

## Open items

- [ ] `uc2-rhoai-openshell`: OpenShell on ROSA (`opendatahub-io/openshell` installer), MLflow in RHOAI over TLS, and the same two-layer scenario.
- [ ] Re-test finding 1 on a newer OpenShell build, and with Docker instead of Podman.
- [ ] Try exporting OpenShell OCSF events over OTLP to MLflow, next to the agent traces (finding 4).
