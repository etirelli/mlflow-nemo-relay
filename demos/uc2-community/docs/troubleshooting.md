# Troubleshooting

Start with `make ps` and `make logs`.

## `make up`: "Create .env first"

Run `cp .env.example .env` and set `LLM_BASE_URL`, `LLM_MODEL` and
`LLM_API_KEY`. The model must support tool calling. To try it without an
LLM, run `make up-scripted`.

## The agent run fails with HTTP 502 "guardrail rejected"

`PolicyDecisionMiddleware` isn't converting the rejection. Check that it is
**first** in `middleware=[...]` in `agent.py`. If it comes after
`NemoRelayMiddleware`, it never sees the exception.

## v1 never gets blocked

Strong models sometimes decline large refunds on their own, even without
the policy in the prompt. Use **Refund $900 (above limit)**, or the
"manager said it's fine" and split cases in the evaluation. The guardrail
is still checked on every call: look for `refund-limit-v1` spans with
`allowed: true`.

## `make eval`: the judge fails, or `policy_compliant_reply` shows n/a

- An HTML error from the endpoint usually means `JUDGE_BASE_URL` ends in
  `/v1`. `evaluation.py` appends `/chat/completions`. If you call the judge
  yourself, pass the full chat-completions URL.
- `ModuleNotFoundError: pandas`: run through `make eval`, which uses the
  `eval` extra.
- `n/a` in the table: the judge returned text values. Keep
  `feedback_value_type=bool`.

## `make eval`: numbers look wrong (refunds counted for the wrong request)

Each refund is attributed to its request through a context variable. If you
add new tools that issue refunds outside the request task (for example, a
background thread), propagate the context, or the per-request ledger won't
see them.

## `make up` with Podman: "host-gateway … host containers internal IP address is empty"

That happens with an `extra_hosts: host.docker.internal:host-gateway` entry
under rootless Podman. UC2 doesn't need it, because the LLM is a remote
endpoint. If you point `LLM_BASE_URL` at a service on your laptop, use
Docker, or add the entry back on a runtime that supports it.

## Ports 8000/8001 already in use

Another demo (or an `oc port-forward` for `uc1-rhoai`) holds them. Stop it,
or set `V1_AGENT_PORT` and `V2_AGENT_PORT` in `.env`.

## MLflow OOM / restarting

Same as UC1: give the VM 4 GB of memory.
