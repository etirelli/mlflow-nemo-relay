# Demo script: 6 minutes

**Audience:** platform and ML engineers, security-minded architects.
**Message:** *Relay keeps sensitive data out of the evidence. OpenShell keeps
the agent from sending it anywhere it shouldn't. MLflow shows engineers what
happened, without the sensitive data.*

## Before you present (T-15 min)

```bash
cd demos/uc1-openshell
openshell status                 # gateway is up
make clean && make up            # or: make up-scripted (no LLM, fully deterministic)
make demo                        # warms everything up; expect "18/18 checks passed"
```

Open four tabs or windows:
1. http://localhost:8000: the chat UI. The header shows `sandbox: uc1-agent-redacted`.
2. http://localhost:5000: MLflow, logged in as `admin`, experiment **uc1-openshell-redacted** → *Traces*.
3. MLflow, experiment **uc1-openshell-baseline** → *Traces*.
4. A terminal in `demos/uc1-openshell`, with `openshell/policy.yaml` open in an editor next to it.

Tip: `make term` (the OpenShell TUI) in a second terminal shows denials live,
and it looks great on screen.

---

## 1. The problem (30 s)

> "This support agent looks customers up by Social Security number. Two
> things can go wrong. First, the SSN ends up in traces that many people can
> read. Second, a tool, a bad integration, or a prompt injection sends
> customer data somewhere it should never go. Today we handle both, and we
> still give engineers full visibility."

## 2. The agent runs in a sandbox (45 s)

In the terminal:

```bash
make ps            # two sandboxes, two forwards, MLflow in compose
```

Show `openshell/policy.yaml`:

> "The agent runs in an NVIDIA OpenShell sandbox with networking turned off.
> The only way out is the OpenShell supervisor, and this policy says the
> agent's Python process may call exactly one thing: the LLM's chat
> completions endpoint. Traces leave through OpenShell's agent trace relay,
> so not even MLflow is reachable. Everything else is denied."

## 3. Run a lookup (60 s)

In the chat UI, with **Redacted** selected:

- Click **Successful lookup**. You get a green `lookup_customer: success` chip.
- Click **Lookup that times out**. You get a red `error` chip and a plain
  explanation.

> "The chat shows the real SSN. The engineer is entitled to it, and the tool
> got it. Nothing about execution changed."

## 4. Block an exfiltration attempt (60 s)

Click **Sync to partner CRM (blocked by sandbox)**. The prompt names the tool
explicitly, because `qwen2.5:0.5b` skips the second tool call when asked
casually.

- The agent looks the customer up (green), then calls `notify_partner_crm`.
  It gets an amber chip, **blocked by OpenShell policy**, and the agent says
  it could not sync the record.

In the terminal:

```bash
make deny-log
#  NET:REFUSE [MED] DENIED partner-crm.example.com [reason:policy_dns_ineligible]
#  NET:OPEN [MED] DENIED /usr/local/bin/python3.12(0) -> partner-crm.example.com:443 [reason:transparent_tcp_policy_denied]
make probe
#  BLOCKED: https://pypi.org/simple/ -> ConnectError: [Errno 13] Permission denied
#  BLOCKED: https://partner-crm.example.com/v1/customers/notify -> ConnectError: [Errno 13] Permission denied
```

> "The tool really tried. The agent wasn't trained to refuse; the boundary
> refused. OpenShell blocked the connection before a byte left the sandbox,
> and logged who tried, from which binary, to where."

## 5. Inspect in MLflow (90 s)

Click **view trace in MLflow** on the CRM reply, or open tab 2.

- **Trace list:** previews read `… SSN [REDACTED-SSN] …`.
- **CRM trace:** `customer-lookup-request → customer_lookup_agent → tools →
  notify_partner_crm`, status **ERROR**. The output says `EgressBlocked: could
  not connect to partner-crm.example.com (ConnectError: All connection attempts
  failed). The record for SSN [REDACTED-SSN] was not sent.`
- **Root span attributes:** `demo.sandbox = uc1-agent-redacted`.
- **Timeout trace:** `lookup_customer`, status **ERROR**, about 2,000 ms, and
  still understandable.

> "Engineers see that the agent attempted a prohibited action, what the
> policy decided, and where in the run it happened. The SSN never reached
> MLflow, not even in the error message of the blocked call. That's the
> evidence you need to fix the agent, which is exactly use case 2."

## 6. Before / after (30 s)

Switch the UI toggle to **Baseline (no redaction)**, run **Successful
lookup**, and open its trace in tab 3.

> "Same image, same sandbox policy. OpenShell allows MLflow, so without
> Relay's redaction the SSN shows up about 90 times in one trace. Sandboxing
> controls *where* data goes. Relay controls *what* is in the telemetry. You
> need both."

## 7. Proof and close (45 s)

```bash
make verify
```

Walk the green checks: both outcomes, parentage, timing, an understandable
failure, no SSN in MLflow or in the ATOF file pulled out of the sandbox, the
baseline control leaks, 401/403 auth, the trace came from the sandbox, the
blocked CRM call is an ERROR span with the reason, the sandbox log has the
denial, and the egress probe was blocked.

> "Relay sanitizes telemetry before export. OpenShell confines the agent to
> the destinations you approve. MLflow lets engineers investigate tool
> outcomes, including denials, without exposing sensitive inputs."

---

## Optional: live policy change (60 s)

Show L7 enforcement on an *allowed* host. The sandbox may call Ollama's chat
API, but not its model-management API:

```bash
openshell sandbox exec -n uc1-agent-redacted -- python -c \
  "import httpx; print(httpx.post('http://host.openshell.internal:11434/api/pull', json={'model':'x'}).text)"
# {"error":"policy_denied","policy":"local_llm","rule":"POST /api/pull","detail":"POST /api/pull not permitted by policy",...}
```

Show that network policy hot-reloads without restarting the agent:

```bash
openshell policy update uc1-agent-redacted --rule-name partner_crm \
  --binary /usr/local/bin/python3.12 \
  --add-endpoint partner-crm.example.com:443:read-write:rest:enforce --wait
make probe         # the partner CRM line changes from BLOCKED to an upstream error (the host doesn't exist)
openshell policy update uc1-agent-redacted --remove-rule partner_crm --wait
```

> "Policy is data. It's versioned (`openshell policy list`), reviewable, and
> applied live. In use case 3 we compare policy versions in MLflow before
> rolling one out."

## Recording a video

- Use `make up-scripted` for deterministic output and no LLM latency.
- Set the browser zoom to 125% and hide the bookmarks bar.
- Open the MLflow tabs and log in before you start recording.
- Keep `make term` in a side window for the denial moment.
