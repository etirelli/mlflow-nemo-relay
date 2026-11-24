# Enabling OpenShift AI Observability (one-time, cluster admin)

UC3 takes latency and resource context from **OpenShift AI Observability**, the
monitoring stack that OpenShift AI deploys when `DSCInitialization.spec.monitoring`
configures metrics (and traces). These are the exact steps validated on
2026-11-24 on ROSA, OCP 4.22.22, RHOAI 3.6.0-ea.2, 2 × m5.2xlarge.

> The RHOAI monitoring stack is **Technology Preview** in 3.x.

## Prerequisites

- cert-manager. It's already required for RHOAI 3.6 (the `odh-observability`
  webhook certificate).
- The `Monitoring` CR exists and `MonitoringDependenciesReady` turns True
  once the operators below are installed.

## 1. Operators (OperatorHub, `redhat-operators`, channel `stable`)

| Operator | Package | Namespace | Validated version | Needed for |
|---|---|---|---|---|
| Cluster Observability Operator | `cluster-observability-operator` | `openshift-cluster-observability-operator` | 1.5.5 | metrics (MonitoringStack, ThanosQuerier, Perses) |
| Red Hat build of OpenTelemetry | `opentelemetry-product` | `openshift-opentelemetry-operator` | 0.158.0 | metrics and traces (collector, target allocator, Instrumentation) |
| Tempo Operator | `tempo-product` | `openshift-tempo-operator` | 0.22.0 | traces (TempoMonolithic) |

Each operator gets its own namespace, an AllNamespaces OperatorGroup and a Subscription:

```yaml
apiVersion: v1
kind: Namespace
metadata: {name: openshift-cluster-observability-operator}
---
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata: {name: cluster-observability-operator, namespace: openshift-cluster-observability-operator}
spec: {}
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata: {name: cluster-observability-operator, namespace: openshift-cluster-observability-operator}
spec: {channel: stable, name: cluster-observability-operator, source: redhat-operators,
       sourceNamespace: openshift-marketplace, installPlanApproval: Automatic}
```

Repeat the same three objects for `opentelemetry-product` and `tempo-product`
in their own namespaces.

## 2. Configure monitoring in the DSCI

```bash
oc patch dscinitialization default-dsci --type=merge --patch-file=- <<'EOF'
spec:
  monitoring:
    managementState: Managed
    namespace: redhat-ods-monitoring      # immutable once set
    collectorReplicas: 1
    metrics:
      replicas: 1
      storage: {size: 5Gi, retention: 1d}
    traces:
      sampleRatio: "1.0"
      storage: {backend: pv, size: 5Gi, retention: 24h}   # a Go duration: 24h, not 1d
EOF
```

Notes:
- `metrics` is applied only if it has `storage` or `exporters`.
- `collectorReplicas` needs metrics storage or traces.
- Run `oc patch ... --dry-run=server` first to validate.

After about a minute, the `Monitoring` CR (`oc get monitoring default-monitoring -o yaml`)
reports `MonitoringStackAvailable`, `ThanosQuerierAvailable`,
`OpenTelemetryCollectorAvailable`, `TempoAvailable`, `InstrumentationAvailable`
and `PersesAvailable` as True. `Degraded` clears once the pods are ready.
`redhat-ods-monitoring` then runs 11 pods: Prometheus, Alertmanager ×2,
Thanos querier, the collector and its target allocator, Tempo, Perses,
korrel8r and two proxies. It also has three PVCs on the default storage class
(5Gi, 5Gi, 1Gi).

## 3. Turn on the dashboard page

```bash
oc patch odhdashboardconfig odh-dashboard-config -n redhat-ods-applications --type=merge \
  -p '{"spec":{"dashboardConfig":{"observabilityDashboard":true}}}'
```

This turns on **Observe & monitor → Dashboard** in the OpenShift AI dashboard. Perses was
already available, so no COO `UIPlugin` was needed.

## 4. Security: restrict the unauthenticated Thanos querier route

> ⚠️ In RHOAI 3.6.0-ea.2, the route `data-science-thanos-querier-route` in
> `redhat-ods-monitoring` uses edge TLS straight to the Thanos querier, with
> **no authentication**. Anyone on the internet can query every metric in the
> RHOAI monitoring stack.
>
> Verified on 2026-11-24: an unauthenticated `GET /api/v1/query` returned data.
> The namespace-scoped route `data-science-prometheus-route` next to it
> correctly returns 401 without a token.

The demo doesn't need that route. Until there's a product fix, restrict it to
your egress IP. This is reversible, and in our test the operator didn't
revert it:

```bash
oc annotate route data-science-thanos-querier-route -n redhat-ods-monitoring \
  haproxy.router.openshift.io/ip_whitelist="<your egress IP>" --overwrite
```

## How UC3 uses the stack

| Need | Source | How |
|---|---|---|
| The agents' latency, guardrail cost and decisions | RHOAI monitoring stack | A `ServiceMonitor` labelled `monitoring.opendatahub.io/scrape: "true"` in the demo namespace. The collector's target allocator selects these in **all** namespaces, scrapes `/metrics`, and forwards the series to the stack's Prometheus. |
| Querying them, namespace-scoped | `data-science-prometheus-route` (kube-rbac-proxy + prom-label-proxy) | `GET /api/v1/query?namespace=<ns>` with a bearer token. It's authorized by `get pods.metrics.k8s.io` in that namespace (Role `uc3-metrics-reader`). |
| Container CPU and memory per policy Deployment | Cluster Prometheus (`thanos-querier.openshift-monitoring.svc:9092`, tenancy port) | The same source the RHOAI Perses "Cluster Prometheus" datasource uses. It's authorized by `get pods` in the namespace. The RHOAI collector has no kubelet/cAdvisor receiver of its own. |

Things that differ from the 3.4 docs, found in the 3.6 source and on the cluster:
- the collector's OTLP ports (4317/4318) accept traffic only from
  `redhat-ods-monitoring` (a NetworkPolicy), so user workloads can't push
  OTLP to it;
- the pod-label scrape path (`monitoring.opendatahub.io/scrape=true` on the
  pod) hard-codes port 8080. The ServiceMonitor path doesn't.

## Rollback

```bash
oc patch dscinitialization default-dsci --type=json \
  -p '[{"op":"remove","path":"/spec/monitoring/metrics"},{"op":"remove","path":"/spec/monitoring/traces"},{"op":"remove","path":"/spec/monitoring/collectorReplicas"}]'
oc patch odhdashboardconfig odh-dashboard-config -n redhat-ods-applications --type=merge \
  -p '{"spec":{"dashboardConfig":{"observabilityDashboard":false}}}'
# then delete the three Subscriptions, their CSVs and namespaces
```
