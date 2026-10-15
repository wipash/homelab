# Homelab Cluster

## Cluster Overview

2-node Talos Linux Kubernetes cluster. Both nodes are control-plane: hp1 (10.0.16.133) and hp2 (10.0.16.135) on the 10.0.16.0/24 network. Cluster API VIP is 10.0.16.132. etcd has two members, so rebooting either node takes the Kubernetes API down until it returns; that is accepted for this homelab.

- **OS:** Talos Linux
- **CNI:** Cilium (replaces kube-proxy entirely)
- **GitOps:** Flux v2 with SOPS age encryption

## Repository Structure

```
talos/                    # Talos base template, node overlays, and image schematic
  nodes/                  # Per-node Talos machine configuration overlays
kubernetes/
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

- **Primary:** iSCSI LUNs on a Synology DS1621+ NAS at 10.0.16.16 (`synology-iscsi` StorageClass, default), provisioned by synology-csi. Every app volume lives on this one NAS, so NAS slowness shows up cluster-wide as iSCSI timeouts and ext4 volumes remounted read-only.
- **VolSync helpers:** `synology-iscsi-ephemeral` for mover clones, `synology-nfs-cache` (NFS) for restic caches.
- **Local:** OpenEBS hostpath (`openebs-hostpath`).
- **Media:** NFS from the same NAS (`/volume1/Media`).
- **Snapshots:** `synology-iscsi` VolumeSnapshotClass.
- **Backups:** VolSync with restic, hourly to MinIO on the NAS (`<app>`) and nightly to Cloudflare R2 (`<app>-r2`).

### VolSync schedules

Every VolSync run snapshots and clones a LUN on the NAS, so runs that start together pile load onto it. Each app sets both schedules explicitly in its `ks.yaml` `postBuild.substitute`, on a slot no other app uses:

- `VOLSYNC_LOCAL_SCHEDULE`: hourly, e.g. `"<minute> * * * *"`. Pick a minute absent from `grep -rh VOLSYNC_LOCAL_SCHEDULE kubernetes/apps`.
- `VOLSYNC_REMOTE_SCHEDULE`: nightly R2, on the next 5-minute slot after the latest one in use (the run currently spans 00:02-03:37 UTC, 13:02-16:37 NZ time). This window stays clear of the NAS's own Hyper Backup jobs at 23:50 and 01:20 NZ time.

Both `kubernetes/components/volsync` and the older `kubernetes/templates/volsync` read these variables.

### NAS access and recovery

SSH: `ssh wipash@10.0.16.16 -p 22222`, password in `.env` as `NASPW`. `sudo -n` works without a password.

- **Read-only volumes** (pods report "Read-only file system" after iSCSI write timeouts): scale the workload to 0, confirm the volume is unmounted on the node, then scale back up. A rollout restart can land on the same node and reuse the read-only mount.
- **`Volume[...] is not found` on mount:** the DSM ScsiTarget package is stopped, often marked `start_failed` after a hard power cycle while the kernel target still serves LUNs. Run `sudo /usr/syno/bin/synopkg start ScsiTarget` on the NAS.
- **iSCSI login rejected after a pod moves nodes:** each target allows one session, and a volume unstaged while the DSM API was down leaves the old node logged in. Log it out from that node's CSI pod: `kubectl -n synology-csi exec <synology-csi-node pod> -c csi-plugin -- chroot /host /usr/local/sbin/iscsiadm -m node -T <iqn> --logout`.

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

The Prometheus container has neither curl nor wget. Port-forward for repeated queries, or use a temporary curl pod for one-offs:

```sh
kubectl -n monitoring port-forward svc/prometheus-operated 19090:9090 &
curl -sG 'http://localhost:19090/api/v1/query' --data-urlencode 'query=up'

kubectl -n monitoring run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl -s 'http://prometheus-operated.monitoring.svc.cluster.local:9090/api/v1/query?query=up'
```

Synology NAS metrics come from the SNMP exporter (job `synology`): `storageIOLA` (disk load %), `iSCSILUNDiskLatencyAvg`, `raidStatus`, `diskStatus`.

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

The Prometheus `ALERTS` metric records alert state over time but only carries labels (alertname, severity, instance, etc.). It does not include annotations (summary, description). For full alert details, query Alertmanager's API or check Pushover notification history.

### Grafana

Grafana has Prometheus, Loki, and Alertmanager configured as datasources. The Explore view (requires Editor/Admin login; anonymous users are Viewers) supports querying all three. Log exploration is under Explore with the Loki datasource.

## Local Validation (no cluster access needed)

Use [flate](https://github.com/home-operations/flate) (same tool as CI) to render and validate all Flux manifests offline. It fetches charts over HTTPS but never touches the cluster. Run it via mise:

```sh
# Validate every Kustomization, HelmRelease, and Flux source renders cleanly
mise x github:home-operations/flate@0.4.10 -- flate test all -p ./kubernetes/flux --no-progress

# Render HelmReleases to YAML (optionally -n <namespace>)
mise x github:home-operations/flate@0.4.10 -- flate build hr -p ./kubernetes/flux --no-progress

# Diff rendered manifests against a git rev. This is the definitive check for what a change
# actually does to cluster resources (catches misplaced values that still render OK)
mise x github:home-operations/flate@0.4.10 -- flate diff hr --base <rev> -p ./kubernetes/flux --no-progress
```

`flate test` also warns about values not consumed by the chart. Note it only checks that manifests render. A structurally-valid-but-misplaced value (e.g. a block inserted mid-`env:` map) still renders, so use `flate diff` against a known-good rev to verify semantic correctness.

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
