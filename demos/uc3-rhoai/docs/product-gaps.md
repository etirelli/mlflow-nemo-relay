# Product-gap validation and findings (UC3 on OpenShift AI)

Validated on 2026-11-24 on ROSA, OCP 4.22.22, **RHOAI 3.6.0-ea.2** (MLflow,
monitoring stack = Technology Preview), with Cluster Observability Operator
1.5.5, Red Hat build of OpenTelemetry 0.158.0, Tempo Operator 0.22.0,
**NeMo Relay 0.11.0**, MLflow 3.17.2, and GLM 5.3 as the agent LLM and judge.

The policy comparison, its Relay and MLflow findings, and the rollout gate
are the same as in [`uc3-community`](../../uc3-community/docs/product-gaps.md).
This page covers what OpenShift AI adds: MLflow in OpenShift AI, and **OpenShift
AI Observability** for latency and resources.

| Requirement (proposal) | Status | How |
|---|---|---|
| Same agent, policy changes | ✅ | Three Deployments, one image, `POLICY_VERSION` per Deployment |
| Compare correct blocks, false blocks, prohibited actions allowed, task completion in MLflow | ✅ | MLflow in OpenShift AI, workspace `uc3-rhoai`. The evaluation runs as an in-cluster Job. |
| **OpenShift AI Observability adds latency and resource context under equivalent load** | ✅ with caveats | The RHOAI monitoring stack scrapes the agents (ServiceMonitor). CPU and memory come from the cluster Prometheus, which the RHOAI dashboards also use. See findings 1–3. |

## Findings: OpenShift AI Observability (RHOAI 3.6.0-ea.2)

| # | Severity | Finding | Evidence | Suggestion |
|---|---|---|---|---|
| 1 | **Security** | **The `data-science-thanos-querier-route` is unauthenticated and public.** It uses edge TLS straight to the Thanos querier (port 10902), with no kube-rbac-proxy in front. Anyone on the internet can query every metric in the RHOAI monitoring stack, including all tenants' forwarded workload metrics. | Unauthenticated `GET /api/v1/query?query=count(up)` → 200 with data. The sibling `data-science-prometheus-route` → 401 without a token. | Put kube-rbac-proxy in front (upstream `main` has started adding one), or don't expose a route by default. Workaround: a `haproxy.router.openshift.io/ip_whitelist` annotation, which the operator didn't revert in our test. |
| 2 | **High (multi-tenancy)** | **User-workload series are relabeled to `namespace="redhat-ods-monitoring"`.** The stack's last hop (Prometheus scraping the collector's re-export) doesn't honor labels, so the project's `namespace` becomes `exported_namespace`, and `namespace` is the collector's. The namespace proxy (`prom-label-proxy --label=namespace`) therefore returns **nothing** for `?namespace=<project>`. A project can't query its own workload metrics through the tenant path. | `uc3_*` series carry `namespace=redhat-ods-monitoring`, `exported_namespace=uc3-rhoai`, `k8s_namespace_name=uc3-rhoai`. A tenant query returns `[]` (`make verify` checks this). | `honorLabels: true` on the collector's ServiceMonitor, or a relabel from `k8s_namespace_name` to `namespace`. Until then, the only path is read access in `redhat-ods-monitoring` (`openshift/monitoring-access.yaml`), and that grant lets the holder read **every** tenant's forwarded metrics. |
| 3 | Medium | **No container CPU or memory in the RHOAI stack.** The collector has no kubeletstats or cAdvisor receiver, so resource context comes from the **cluster** Prometheus (`thanos-querier.openshift-monitoring` tenancy port). The RHOAI Perses "Cluster Prometheus" datasource uses it too. | The collector config and RBAC have no `nodes/metrics`. Container series exist only in `openshift-monitoring`. | Document the split ("workload metrics: RHOAI stack; resources: cluster monitoring"), or add a kubeletstats receiver scoped to data science projects. |
| 4 | Medium | **Any pod can push OTLP to the collector, unauthenticated.** The RHOAI NetworkPolicy allows 4317/4318 only from `redhat-ods-monitoring`. But the OpenTelemetry operator's generated policy (`data-science-collector-collector-networkpolicy`) allows those ports from **all** sources, and NetworkPolicies add up. | Both policies, read on the cluster. | Decide on the intended model. If pushing is meant to be allowed, authenticate it (bearer token extension, per-tenant routing). If not, the operator's policy must not open the ports. |
| 5 | Low | **The target allocator logs `secrets is forbidden`** every few seconds. Its service account can't list secrets in `redhat-ods-monitoring`. ServiceMonitor discovery still works. | Target allocator logs. `oc auth can-i list secrets --as=…collector-collector` → no. | Grant read on secrets (it's needed for ServiceMonitor TLS/auth), or turn off that watch. |
| 6 | Info | **The ServiceMonitor path works across namespaces.** The target allocator selects monitors labelled `monitoring.opendatahub.io/scrape: "true"` with an empty namespace selector. The pod-label path hard-codes port 8080 (in the source, not tried here). | `prometheusCR` in the OpenTelemetryCollector spec. Job `serviceMonitor/uc3-rhoai/uc3-agents/0` was served. | Document the ServiceMonitor path as the recommended one for custom workloads. |
| 7 | Info | **Two 30-second scrape hops** (target → collector → Prometheus) delay the series. | The evaluation waits 70 s before querying, and windows are at least 2 minutes. | — |
| 8 | Info | **Technology Preview, and resource limits can't be configured in 3.6** (Prometheus 512Mi, collector 256Mi). The 3.4 docs show `metrics.resources`, but the 3.6 CRD doesn't have it. | CRD `monitorings.services.platform.opendatahub.io`; the `odh-observability` chart defaults. | Expose resources again before GA. |

## Findings: demo engineering

| Finding | Note |
|---|---|
| `oc process` drops `metadata.namespace` | Objects that must live in another namespace (the grant in `redhat-ods-monitoring`) can't go in an OpenShift Template. They landed in the current project instead. `openshift/monitoring-access.yaml` is plain YAML. |
| Setup is several steps | Three operators, a DSCI patch and a dashboard flag: see [observability-setup.md](observability-setup.md). It took about 10 minutes on this cluster. |

## Upstream report candidates

- RHOAI / odh-observability: findings 1 (security), 2 (multi-tenancy), 3, 4,
  5 and 8. They come with the evidence above and the live cluster state.
- NeMo Relay and MLflow: see `uc3-community`.
