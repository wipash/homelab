# Homelab Cluster

## Cluster Overview

3-node Talos Linux Kubernetes cluster. All nodes are control-plane (hp1, hp2, hp3) on the 10.0.16.0/24 network with a secondary 172.20.0.0/24 network for Ceph traffic. Cluster API VIP is 10.0.16.132.

- **OS:** Talos Linux
- **CNI:** Cilium (replaces kube-proxy entirely)
- **GitOps:** Flux v2 with SOPS age encryption

## Repository Structure

```
kubernetes/
  bootstrap/talos/     # Talos machine config (talconfig.yaml)
  flux/
    config/            # Flux system bootstrap
    repositories/helm/ # HelmRepository sources (~40 repos)
    apps.yaml          # Top-level apps Kustomization
  apps/                # All workloads, organized by namespace
    <namespace>/
      <app>/
        app/
          helmrelease.yaml
          kustomization.yaml
        ks.yaml          # Flux Kustomization pointing to app/
  components/          # Shared components (alerts, secrets, volsync)
  templates/           # Reusable templates (volsync backup configs)
```

Each app follows the pattern: Flux Kustomization (`ks.yaml`) -> `app/kustomization.yaml` -> HelmRelease + supporting resources.

## Networking

- **Gateway API** via Envoy Gateway (not Ingress). Routes are HTTPRoute resources.
- **Two gateways:** `envoy-external` (172.16.10.1) and `envoy-internal` (172.16.10.3)
- **DNS:** external-dns syncs to both Cloudflare (public) and Pi-hole at 10.0.16.4 (internal)
- **Tunnel:** Cloudflared for external access
- **Domain:** mcgrath.nz
- **Load balancing:** Cilium BGP with dedicated IPs per service (172.16.10.0/24 range)

## Storage

- **Primary:** Rook-Ceph (`ceph-block` StorageClass, default). 3-way replication across nodes using NVMe drives.
- **Local:** OpenEBS hostpath (`openebs-hostpath`) for ephemeral workloads.
- **Backups:** Volsync with Restic snapshots to S3-compatible storage.
- **Snapshots:** `csi-ceph-blockpool` VolumeSnapshotClass.

## Secrets

- **External Secrets Operator** pulling from 1Password Connect (`onepassword-connect.kube-system.svc.cluster.local`)
- **SOPS** with age encryption for secrets committed to git (`.sops.yaml` in repo root)
- **Cluster variables** substituted by Flux from ConfigMap `cluster-settings` and Secret `cluster-secrets`

## Monitoring & Diagnostics

### Stack

| Tool | Purpose | Internal Address |
|------|---------|-----------------|
| Prometheus | Metrics & alerting rules | `prometheus-operated.monitoring.svc.cluster.local:9090` |
| Alertmanager | Alert routing (Pushover for critical) | `alertmanager-operated.monitoring.svc.cluster.local:9093` |
| Grafana | Dashboards & log exploration | `grafana.monitoring.svc.cluster.local:80` |
| Loki | Log aggregation (7-day retention) | `loki-headless.monitoring.svc.cluster.local:3100` |
| Promtail | Log collection (DaemonSet) | pushes to Loki |

External URLs: `grafana.mcgrath.nz`, `prometheus.mcgrath.nz`, `alertmanager.mcgrath.nz`

Additional exporters: node-exporter, kube-state-metrics, blackbox-exporter, SNMP exporter (UPS), smartctl exporter (disks), speedtest exporter. Gatus health dashboard at `status.mcgrath.nz`.

### Querying Prometheus

Prometheus pods don't have curl/wget. Use the exec approach through the Prometheus container which has a built-in HTTP client:

```sh
# Query via exec into the prometheus container
kubectl -n monitoring exec prometheus-kube-prometheus-stack-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=up'

# Or spin up a temporary curl pod for any internal service
kubectl -n monitoring run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl -s 'http://prometheus-operated.monitoring.svc.cluster.local:9090/api/v1/query?query=up'
```

### Querying Loki

Loki containers are minimal (no curl/wget). Use a debug pod:

```sh
# Check Loki health
kubectl -n monitoring run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl -s 'http://loki-headless.monitoring.svc.cluster.local:3100/ready'

# Query logs via LogQL
kubectl -n monitoring run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl -s 'http://loki-headless.monitoring.svc.cluster.local:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={namespace="monitoring"}' \
  --data-urlencode 'limit=50'
```

### Alertmanager

```sh
# List currently firing alerts
kubectl -n monitoring run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl -s 'http://alertmanager-operated.monitoring.svc.cluster.local:9093/api/v2/alerts?active=true'
```

### Notes on the ALERTS Metric

The Prometheus `ALERTS` metric records alert state over time but only carries labels (alertname, severity, instance, etc.) — it does NOT include annotations (summary, description). For full alert details, query Alertmanager's API or check Pushover notification history.

### Grafana

Grafana has Prometheus, Loki, and Alertmanager configured as datasources. The Explore view (requires Editor/Admin login — anonymous users are Viewers) supports querying all three. Log exploration is under Explore with the Loki datasource.

## Flux Operations

```sh
# Force reconciliation of an app
flux reconcile kustomization <app-name> --with-source

# Check Flux status
flux get kustomizations
flux get helmreleases -A

# Suspend/resume an app (useful during debugging)
flux suspend helmrelease <name> -n <namespace>
flux resume helmrelease <name> -n <namespace>
```
