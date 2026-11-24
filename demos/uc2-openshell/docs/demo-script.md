# Demo script: 7 minutes

**Audience:** ML engineers, platform and security owners.
**Message:** *Two independent controls, one record. NeMo Relay decides which
tool calls an agent may make. OpenShell decides which network requests the
agent's process may make. MLflow shows both decisions, distinctly, in the same
trace, and proves on the same cases that a better agent hits neither.*

## Before you present (T-15 min)

```bash
cd demos/uc2-openshell
make up && make demo      # expect "UC2 (OpenShell) success criteria: MET" and all checks passing
```

Open:
1. http://localhost:8000: the chat UI, toggle on **v1**.
2. MLflow (`admin`) → **uc2-openshell-refund-agent** → Traces.
3. MLflow → **uc2-openshell-refund-agent-eval** → Evaluation runs.
4. A terminal in `demos/uc2-openshell` for `make deny-log` and `make ledger`.

## 1. The setup (45 s)

> "Same support agent as before, same $500 refund policy in NeMo Relay. What's
> new: both agent versions run inside NVIDIA OpenShell sandboxes. The sandbox
> policy lets the agent call exactly one payments API, `POST /v1/refunds`, plus
> MLflow and the LLM. Nothing else: no internet, no ledger, no credits API.
> And the LLM key isn't even in the sandbox. OpenShell injects it on the way out."

Show `openshell/policy.yaml`, the `payments_refunds` rule.

## 2. Layer 1: Relay blocks the refund (45 s)

With **v1**, click **Refund $900 (above limit)**:
`issue_refund: blocked by Relay policy`, "money moved: none".

> "Relay's policy saw `issue_refund` with amount 900 and stopped it before the
> tool ran. Nothing left the process."

## 3. Layer 2: OpenShell denies the workaround (75 s)

Still on **v1**, click **$900, else as a credit**:

- `issue_refund: blocked by Relay policy`
- `apply_account_credit: denied by OpenShell sandbox`

> "v1 is helpful to a fault. When the refund was blocked, it reached for a
> credit tool a developer added: same money, different API. Relay's refund
> policy doesn't know that tool, so it allowed the call. But the sandbox only
> lets this process post to `/v1/refunds`, so the credit request never reached
> the payments service."

```bash
make deny-log    # DENIED POST http://host.openshell.internal:8090/v1/credits [policy:payments_refunds engine:l7]
make ledger      # only the allowed refunds; no credit, nothing above $500
```

## 4. Both decisions in one MLflow trace (75 s)

Open that request's trace:

- `tools` → **`refund-limit-v1`** `GUARDRAIL`, target `issue_refund`,
  `rejected: true`, with the reason. There's **no** `issue_refund` tool span.
- Next `tools` → **`refund-limit-v1`** `GUARDRAIL`, target
  `apply_account_credit`, `allowed: true`, then the **`apply_account_credit`**
  `TOOL` span with status **ERROR**: `EgressBlocked: OpenShell sandbox policy
  denied POST …/v1/credits (error=policy_denied; policy=payments_refunds;
  rule=POST /v1/credits …)`.
- For contrast, **Lookup that times out**: a `TOOL` span with status `ERROR`
  and a `TimeoutError`, with no guardrail involved.

> "Three different shapes: a policy block, a sandbox denial, and an ordinary
> failure. An engineer can tell them apart at a glance and filter for each.
> The sandbox denial names the policy and the rule, because the payments host
> sits behind an L7 rule."

## 5. Improve the agent, not the controls (45 s)

> "The trace tells the engineer two things: v1 doesn't know the limit, and it
> uses a tool that can never succeed to get around it. v2 fixes both: the
> prompt explains the limit, there's an escalation tool, and the credit tool
> is gone. Relay's policy and the sandbox policy are untouched."

Toggle **v2**, click **$900, else as a credit**:
`request_supervisor_approval: success`, with an escalation ticket. No block and
no denial.

## 6. Prove it on the same cases (90 s)

MLflow → **uc2-openshell-refund-agent-eval** → compare **agent-v1** with
**agent-v2**:

- 12 cases, including two "credit instead" workarounds.
- `no_prohibited_attempt` counts Relay blocks **and** sandbox denials;
  `no_sandbox_denial` isolates the second layer.
- `blocked_never_executed` is 100% for both: the payments ledger shows no
  refund above $500 and no credit.
- Open a row and show the LLM judge's rationale.

## 7. Close (30 s)

```bash
make verify
```

> "Relay controls what the agent may *do*, OpenShell controls where its process
> may *reach*, and MLflow is the single place where both decisions become
> evidence for improving the agent. Same story on OpenShift AI next."

## Notes

- `make up-scripted` gives a deterministic rehearsal (v1 always tries the credit).
- LLM responses vary. GLM 5.3 v1 doesn't always try the credit; the
  quick-action wording makes it likely, not certain.
