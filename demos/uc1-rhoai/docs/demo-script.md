# Demo script: 5 minutes (OpenShift AI)

**Audience:** platform engineers, ML engineers, security architects evaluating OpenShift AI.
**Message:** *Relay keeps sensitive inputs out of agent telemetry. MLflow in
OpenShift AI gives engineers the evidence, isolated per project, and
authenticated with the platform's own identities.*

## Before you present (T-15 min)

```bash
cd demos/uc1-rhoai
make check            # cluster, Secret, MLflow OK
make up               # if not deployed yet
make port-forward
make demo             # warm-up; expect "13/13 checks passed"
```

Open:
1. http://localhost:8000: the chat UI.
2. The OpenShift AI dashboard → **Applications → MLflow**, workspace **uc1-rhoai**, experiment **uc1-rhoai-redacted** → *Traces*.
3. The same for **uc1-rhoai-baseline**.
4. A terminal with `openshift/template.yaml` open at the `Role`.

## 1. The problem (30 s)

> "A support agent on OpenShift AI looks customers up by SSN. The tool needs
> it. But agent traces flow into a shared trace store. How do engineers debug
> tool calls without copying SSNs into MLflow, and without handing the agent
> broad credentials?"

## 2. Run a lookup (60 s)

In the chat UI, with **Redacted** selected:
- **Successful lookup:** a green `lookup_customer: success` chip.
- **Lookup that times out:** a red chip. The model explains the timeout and suggests a next step.

> "The chat shows the real SSN, because the engineer is entitled to it. The
> model is the one configured for this cluster; nothing about the model is
> baked into the demo."

## 3. Inspect in MLflow, in OpenShift AI (90 s)

Click **view trace in MLflow** on the timeout reply. It opens the right workspace.

- **Workspace `uc1-rhoai`:** one MLflow workspace per OpenShift project.
- **Trace tree:** `customer-lookup-request → customer_lookup_agent → tools → lookup_customer`.
- **The tool span:** **ERROR**, about 2,000 ms, with inputs `{"ssn": "[REDACTED-SSN]"}`, and the error is still readable.

> "Status, duration, position in the run and the cause, with no SSN. That
> includes the place where the tool echoed the SSN in its error."

## 4. Before / after (45 s)

Toggle **Baseline**, run **Successful lookup**, and open the baseline trace.

> "Same image, same model. The only difference is the Relay policy. Without
> it, the SSN appears about 90 times in one trace."

## 5. Platform-native security (45 s)

Show the `Role` in `openshift/template.yaml`:

```yaml
resources: ["experiments"]
verbs: ["get", "update"]
resourceNames: ["uc1-rhoai-redacted", "uc1-rhoai-baseline"]
```

> "The agent authenticates with its OpenShift service account token. There's
> no password, and the token rotates. MLflow authorizes every write with
> Kubernetes RBAC: this agent can write traces to *these two experiments*, and
> nothing else, not even another experiment in the same project."

## 6. Proof and close (30 s)

```bash
make verify
```

> "Twelve checks: both outcomes, timing, parentage, readable failures, no SSN
> in MLflow, the baseline control, and authentication. A missing token is
> rejected, and the agent is blocked from an experiment it wasn't granted.
> Relay sanitizes before export; MLflow in OpenShift AI keeps the evidence,
> per project, under platform RBAC. Next: Relay *blocking* actions, with
> MLflow evaluating agent versions (use case 2)."

## Recording tips

- For a fully deterministic recording, set `LLM_PROVIDER=scripted` in
  `config.env`, then run `make deploy rollout port-forward`.
- Log in to the OpenShift AI dashboard and open the MLflow tabs before you
  start.
