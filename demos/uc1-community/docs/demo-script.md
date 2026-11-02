# Demo script: 5 minutes

**Audience:** platform and ML engineers, security-minded architects.
**Message:** *Relay protects telemetry before it leaves the agent. MLflow gives
engineers the evidence they need, without the sensitive data.*

## Before you present (T-10 min)

```bash
cd demos/uc1-community
make clean && make up          # or: make up-scripted (no LLM, fully deterministic)
make demo                      # warms everything up; expect "12/12 checks passed"
```

Open three browser tabs:
1. http://localhost:8000: the chat UI
2. http://localhost:5000: MLflow (log in as `admin`). Open experiment **uc1-customer-lookup-redacted** → *Traces*.
3. MLflow, experiment **uc1-customer-lookup-baseline** → *Traces*

Tip: with a real LLM, use `qwen2.5:7b` or larger. Tiny models (0.5b) call the
tool correctly but write weak explanations of the timeout. For a fully
predictable live demo, use `make up-scripted`.

---

## 1. The problem (30 s)

> "This support agent looks customers up by Social Security number. The tool
> genuinely needs the SSN. But every agent framework emits traces, and those
> traces end up in observability backends that many people can read. How do
> you debug tool calls without copying SSNs into your trace store?"

## 2. Run a lookup (60 s)

In the chat UI, with **Redacted** selected:

- Click **Successful lookup**. The agent calls `lookup_customer` and replies
  with Ada Synthetic's account. Point at the green `lookup_customer: success` chip.
- Click **Lookup that times out**. That customer is on a "legacy shard" that
  never answers within 2 s. You get a red `error` chip, and the agent explains
  the failure.

> "Notice the chat shows the real SSN. The engineer is entitled to it, and the
> tool received it. Nothing about the actual execution changed."

## 3. Inspect in MLflow (90 s)

Click **view trace in MLflow** on the timeout reply, or open tab 2.

- **Trace list:** the request preview reads `Check the account for SSN [REDACTED-SSN]`.
- **Open the trace:** walk the tree: `customer-lookup-request → customer_lookup_agent → tools → lookup_customer`.
- **The tool span:** status **ERROR**, duration about 2,000 ms, inputs
  `{"ssn": "[REDACTED-SSN]"}`. The output still says *what* failed: "TimeoutError:
  customer records service did not respond within 2.0s while looking up SSN
  [REDACTED-SSN]…"
- Open the successful trace: the tool span is **OK**, about 200 ms, and the
  echoed `ssn` field in the result is redacted too.

> "Engineers get status, duration, position in the run, and an understandable
> error. The identifier never reached MLflow, including where the tool
> *echoed* it back in its result and error message."

## 4. Before / after (45 s)

Switch the chat UI toggle to **Baseline (no redaction)**, run **Successful
lookup**, and open its trace (tab 3).

> "Same agent, same image. The only difference is the Relay policy file.
> Without the `pii_redaction` component, the SSN shows up in inputs, outputs,
> LLM messages, and tool attributes: about 90 copies in a single trace."

Optionally, show [`relay/plugins.redacted.toml`](../relay/plugins.redacted.toml):
two short profiles, one for the `ssn` field and one regex for echoed text.

## 5. Proof and close (45 s)

In a terminal:

```bash
make verify
```

Walk the green checks: both outcomes visible, parentage and timing preserved,
failure understandable, **no SSN in MLflow or in Relay's local event file**,
the baseline control leaks, an unauthenticated export gets 401, and the
service account is blocked from other experiments (403).

> "Relay sanitizes telemetry before export. MLflow lets engineers investigate
> tool outcomes without exposing sensitive inputs. Next, we extend the same
> integration to execution controls: Relay *blocking* actions, and MLflow
> evaluating the agent's behavior (use case 2)."

---

## Recording a 5-minute video

- Run `make up-scripted` for deterministic output and no LLM latency.
- Set the browser zoom to 125% and hide the bookmarks bar.
- Pre-open the MLflow tabs and log in before you start recording.
