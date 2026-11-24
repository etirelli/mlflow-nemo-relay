# Troubleshooting

Start with `make status`, `make logs`, and `oc get monitoring default-monitoring -o yaml`.

## `make check`: "OpenShift AI Observability (metrics) is not enabled"

The `data-science-prometheus-route` doesn't exist. Do the one-time setup in
[observability-setup.md](observability-setup.md): three operators, then the
DSCI monitoring patch.

## The evaluation logs no latency (`latency_p95_s` missing)

- Is the agent scraped? Run `make verify` and look at check 13, or query the
  stack directly:
  `oc get --raw "/api/v1/namespaces/redhat-ods-monitoring/services/data-science-collector-targetallocator:80/proxy/scrape_configs"`
  must list `serviceMonitor/<ns>/uc3-agents/0`.
- The `ServiceMonitor` must carry `monitoring.opendatahub.io/scrape: "true"`.
- **403 from the proxy:** the evaluator needs the grant in `redhat-ods-monitoring`
  (`make monitoring-access`). Check it with
  `oc auth can-i get pods.metrics.k8s.io -n redhat-ods-monitoring --as=system:serviceaccount:<ns>:uc3-evaluator`.
- **200 but empty:** you queried `?namespace=<project>`. RHOAI 3.6 relabels
  workload series to `namespace=redhat-ods-monitoring` (OBS-2 in the repo's product gaps report).
- The first samples arrive after two 30-second scrape hops. Very short runs
  can end before them.

## `make monitoring-access` says "created", but the grant doesn't work

Check the namespace: `oc get role uc3-rhoai-metrics-reader -n redhat-ods-monitoring`.
If you rendered the manifest with `oc process`, the objects went to your
current project instead, because `oc process` drops `metadata.namespace`. Use
`make monitoring-access` (plain YAML via `sed`).

## Collector logs `Failed to scrape … dial tcp …:8000`

This is normal during a rollout (old pod IPs). It's persistent only if a
NetworkPolicy in your project blocks ingress from `redhat-ods-monitoring`.
Allow port 8000 from that namespace.

## Target allocator logs `secrets is forbidden`

That's OBS-5 in the repo's product gaps report. It's harmless for ServiceMonitors without
TLS or auth secrets.

## `make port-forward`: ports in use

Ports 8000–8002 are shared with `uc3-community` and other demos. Stop them
(`make down` there), or set `POLICY_V*_LOCAL_PORT` in `config.env`.

## The Thanos querier route stopped answering

That's expected if you restricted it to your IP (observability-setup step 4)
and your egress IP changed, for example on another network or VPN. The demo
doesn't use that route.

## The gate says NOT MET

See [`uc3-community/docs/troubleshooting.md`](../../uc3-community/docs/troubleshooting.md):
LLM variance, the latency budget, missing cases.
