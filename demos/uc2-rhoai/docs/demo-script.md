# Demo script: 6 minutes

**Audience:** ML engineers and platform owners.
**Message:** *Relay enforces the policy and records every decision. MLflow
turns those decisions into evidence: engineers fix the agent, prove the fix
on the same cases, and keep the cases as a regression set. The policy never
weakens.*

## Before you present (T-15 min)

```bash
cd demos/uc2-rhoai
make check && make up         # if not deployed yet
make port-forward
make demo                     # expect "UC2 success criteria: MET" and all checks passing
```

Open:
1. http://localhost:8000: the chat UI, toggle on **v1**.
2. The OpenShift AI dashboard → MLflow, workspace **uc2-rhoai** → **uc2-rhoai-refund-agent** → Traces.
3. The same workspace → **uc2-rhoai-refund-agent-eval** → Evaluation runs.
4. A terminal: `oc get jobs -n uc2-rhoai` (the evaluation runs as a Job).

## 1. The problem (30 s)

> "Guardrails stop agents from doing things they shouldn't. But an agent that
> keeps hitting the guardrail still fails its users: retries, delays,
> frustrated customers. We need evidence to fix the *agent*, without
> loosening the *policy*."

## 2. v1 hits the guardrail (60 s)

With **v1** selected:
- **Refund $120 (allowed):** a green chip, and "refunds executed: $120.00".
- **Refund $900 (above limit):** `issue_refund: blocked by Relay policy`,
  "refunds executed: none". The agent explains why.

> "Relay's refund policy blocked that call before it ran. You can see it in
> the ledger: nothing was refunded. And the agent didn't crash; it got the
> decision back and explained it."

## 3. The decision in MLflow (60 s)

Open the trace of the $900 request:
- `tools` → **`refund-limit-v1`**, a `GUARDRAIL` span with `rejected: true`
  and the reason.
- The requested call on `tools`: `issue_refund`, amount 900.
- **No `issue_refund` tool span.** The tool never started.
- Compare it with **Lookup that times out**: a `TOOL` span with status `ERROR`.

> "MLflow tells a policy rejection apart from a tool failure, with the policy
> version, the attempted action and the reason. Filter the traces and you see
> the pattern: v1 keeps trying refunds it isn't allowed to issue."

## 4. Improve the agent, not the policy (45 s)

Show `agent.py`, the v2 system prompt, and the new
`request_supervisor_approval` tool in `tools.py`.

> "The engineer's fix is in the agent: tell it the limit and give it the
> escalation path. Relay's policy is the same object for both versions."

Switch the toggle to **v2**, then click **Refund $900**:
`request_supervisor_approval: success`, with an escalation ticket. There's
no block.

## 5. Prove it: evaluation on the same cases (90 s)

In MLflow → **uc2-rhoai-refund-agent-eval** → *Evaluation runs*: compare
**agent-v1** with **agent-v2**.

- The dataset `uc2-refund-policy-regression` has 10 cases: allowed,
  boundary, prohibited, "manager said it's fine", and "split it into two
  $450 refunds".
- Prohibited attempts drop from about 20% to 0%. Task completion rises.
  `blocked_never_executed` is 100% for both.
- Open a row and show the **LLM judge's** rationale.

> "The evaluation ran as a Job on the platform: its own service account, the
> judge's key from a Secret, and results in this project's MLflow workspace.
> Fewer blocks could mean a lazier agent, so we also score completed tasks,
> and an LLM judge reviews every reply against the written policy. The
> guardrail stayed on the whole time. And this dataset stays in MLflow as
> the regression suite for the next change."

## 6. Proof and close (30 s)

```bash
make verify
```

> "Relay supplies the execution control and the decision evidence. MLflow
> supplies investigation, evaluation and regression. Next: change the
> *policy*, with the agent fixed, and check it before rollout. That's use
> case 3."

## Notes

- For a deterministic rehearsal, set `LLM_PROVIDER=scripted` in `config.env`,
  then run `make deploy rollout eval`. The judge is skipped.
- LLM responses vary. With a real model, v1 sometimes declines a large
  refund on its own, so the percentages move between runs, but the direction
  holds.
