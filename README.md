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

## Headscale tailnet

`kubernetes/apps/networking/tailscale-router` runs a standalone Tailscale subnet/exit router against **https://hs.mcgrath.nz**. Headscale 0.29.3 does not provide the OAuth API needed by the native Kubernetes operator, so the previous operator and Connector have been removed.

- **Router:** `ts-pod-cidrs.tailnet.hs.mcgrath.nz` (`100.64.0.2`), tagged `tag:homelab-router`.
- **Advertised subnets:** `10.0.16.0/24`, `10.0.10.0/24`, `10.244.0.0/16`, `172.16.10.0/24`; also advertises IPv4/IPv6 exit-node routes. Headscale auto-approves these through policy in the separate `jumper` repository.
- **Kubernetes API:** use the existing authenticated kubeconfig endpoint `https://10.0.16.132:6443` over the subnet route. The old operator-specific API proxy is gone.
- **Enrollment:** 1Password vault `Kubernetes`, item `headscale-router`, concealed field `auth_key`. External Secrets produces `networking/tailscale-router-auth`; no enrollment key is stored in Git.
- **Identity:** `networking/tailscale-router-state` holds Tailscale state across pod replacements. Keep it when restarting or updating the app. The service account can only get/update/patch this named Secret.
- **Talos:** automatic firewall selection uses nftables; legacy iptables is unavailable. Forwarding is enabled inside the pod network namespace, without host networking.

Linux clients need `tailscale set --accept-routes=true`. To use the home connection as an exit node, select `ts-pod-cidrs` in the client or run `tailscale set --exit-node=ts-pod-cidrs`; clear it with `tailscale set --exit-node=`.

The reusable tagged enrollment key expires **2026-12-19 05:27:55 UTC**. Its expiry does not disconnect the already-enrolled router: `TS_AUTH_ONCE=true` reuses the persisted identity. Before fresh enrollment or recovery without that state, create a replacement with `headscale preauthkeys create --tags tag:homelab-router --reusable --expiration 2160h` on Jumper and update `auth_key`, `headscale_key_id`, and `expires_at` in the vault item. Refresh `tailscale-router-auth` through External Secrets before starting a new identity. Do not paste keys into Git or command-line arguments.

Operational checks:

```sh
flux reconcile kustomization tailscale-router --with-source
kubectl -n networking get helmrelease tailscale-router
kubectl -n networking exec deployment/tailscale-router -- tailscale status
```

Verified on 2026-09-20 from an independent Azure tailnet client: Kubernetes API TLS validation and expected unauthenticated HTTP 401, pod metrics HTTP 200, internal load-balancer HTTP 301, ICMP to `10.0.10.1`, and IPv4 exit traffic through home IP `101.98.238.192`. Router identity survived pod replacement and Flux reapplication. Temporary verification resources were removed.

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
