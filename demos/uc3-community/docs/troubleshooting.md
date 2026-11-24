# Troubleshooting

Start with `make ps` and `make logs`.

## `make up`: "Create .env first"

Run `cp .env.example .env` and set `LLM_BASE_URL`, `LLM_MODEL` and
`LLM_API_KEY`. To try it without an LLM, run `make up-scripted`, then
`make demo LLM_PROVIDER=scripted`.

## The gate says NOT MET

LLM behavior varies. Look at the rows:
- **v2 rejected for "allows more prohibited actions" or "adds false blocks"**:
  open the failing rows in MLflow. A budget false block usually means the
  model issued the *same* refund twice (a retry), which the budget counts
  twice. That's a real behavior, worth a case of its own.
- **v2 rejected on latency**: LLM latency is noisy. Raise `LOAD_ROUNDS` for
  steadier numbers, or `LATENCY_BUDGET` (default 1.5).
- **v3 promoted**: none of the $300–$500 allowed cases reached the policy,
  for example because the LLM endpoint failed. Check the run's
  `labeled_requests` and the agents' logs.

## Prometheus metrics are missing or zero in the eval runs

- `make ps`: is `prometheus` up? Open http://localhost:9090/targets: all
  three `agent-policy-*` jobs must be UP.
- The eval queries `http://localhost:9090`. Change `PROMETHEUS_PORT` in
  `.env` if 9090 is taken.
- Very short runs (scripted model) can give coarse quantiles, because
  Prometheus scrapes every 5 s.

## `requests` in the run is lower than `labeled_requests`

The run started before Prometheus had a first sample of the series. The
services create their series at zero on startup to prevent this. If you added
a metric, do the same (see `metrics.py`).

## The budget doesn't apply (v2 behaves like v1)

The guardrail reads the request id from a context variable that the chat
handler sets (`refunds.start_request()`). If you call the agent outside
`/api/chat` (for example from a new endpoint), start a request the same way,
or every call shares the `no-request` bucket.

## Ports already in use

Ports 5000, 8000–8002 and 9090 are shared with other demos (and with
`oc port-forward` for the RHOAI demos). Stop them, or change the ports in
`.env`.

## MLflow OOM / restarting

Give the Podman machine 4 GiB. Three agent services, MLflow and Prometheus
fit.
