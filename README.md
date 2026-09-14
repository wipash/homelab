# Homelab Kubernetes cluster

My homelab runs Kubernetes on [Talos Linux](https://www.talos.dev/). [Flux](https://fluxcd.io/) keeps the cluster in sync with this repository.

## Core components

| Component | Purpose |
| --- | --- |
| [Cilium](https://cilium.io/) | Pod networking and load balancing |
| [Envoy Gateway](https://gateway.envoyproxy.io/) | HTTP routing through the Kubernetes Gateway API |
| [Cloudflared](https://github.com/cloudflare/cloudflared) | Cloudflare Tunnel for external access |
| [external-dns](https://github.com/kubernetes-sigs/external-dns) | Automatic DNS records |
| [cert-manager](https://cert-manager.io/) | TLS certificates |
| [External Secrets](https://external-secrets.io/) | Kubernetes secrets from 1Password Connect |
| [SOPS](https://github.com/getsops/sops) | Encryption for secrets stored in Git |
| [Spegel](https://spegel.dev/) | Container image sharing between nodes |
| [Prometheus](https://prometheus.io/), [Grafana](https://grafana.com/) and [Loki](https://grafana.com/oss/loki/) | Metrics, dashboards and logs |
| [Actions Runner Controller](https://github.com/actions/actions-runner-controller) | Self-hosted GitHub Actions runners |

## Storage

Most other k8s homelab clusters use node-local storage like Rook/Ceph for persistent volumes. I have recently torn that out to save cluster resources, and now use iSCSI via 10GBe network on a Synology NAS.

## GitOps

Flux applies the configuration under `kubernetes/apps`, grouped by namespace. Each app's `ks.yaml` points to its manifests, usually a HelmRelease and supporting resources. Dependencies control deployment order.

[Renovate](https://github.com/renovatebot/renovate) opens pull requests for dependency updates. Flux applies merged changes to the cluster.

## Repository layout

```text
talos/                   # Node configuration and OS image templates
bootstrap/               # Cluster bootstrap configuration
kubernetes/
  apps/                  # Applications
  flux/                  # Flux configuration, sources and cluster variables
  components/            # Shared Kustomize components
.taskfiles/              # Operational tasks
```

## Acknowledgements

Inspired by the [Home Operations](https://discord.gg/home-operations) community and [flux-cluster-template](https://github.com/onedr0p/flux-cluster-template). [KubeSearch](https://kubesearch.dev/) has examples from other homelabs.
