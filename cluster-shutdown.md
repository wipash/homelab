# Cluster Shutdown

Graceful shutdown procedure for the 3-node Talos + Rook-Ceph cluster.

## 1. Flag Ceph to pause rebalancing

Prevents Ceph from thrashing when OSDs drop out. Run from the rook-ceph toolbox:

```sh
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- sh -c '
  for f in noout nobackfill norecover norebalance nodown pause; do
    ceph osd set $f
  done
  ceph status
'
```

Flag meanings:

| Flag | Effect |
|------|--------|
| `noout` | Don't mark down OSDs as out (prevents remapping) |
| `nobackfill` | Pause backfill operations |
| `norecover` | Pause recovery operations |
| `norebalance` | Pause rebalancing |
| `nodown` | Don't mark OSDs down |
| `pause` | Pause all client I/O |

Expect `HEALTH_WARN` — that's the flags, not a real problem.

## 2. (Optional) Suspend Flux

Only needed if you want the cluster to come back in exactly the same state without Flux racing to reconcile during boot:

```sh
flux -n flux-system suspend kustomization --all
```

## 3. Shut down the nodes

All three in parallel — Talos handles kubelet drain internally:

```sh
talosctl -n 10.0.16.133,10.0.16.135,10.0.16.136 shutdown
```

Or one at a time via the justfile (`talos/mod.just:47`):

```sh
just talos shutdown-node hp1
just talos shutdown-node hp2
just talos shutdown-node hp3
```

## 4. Power up

Boot all three nodes (ideally together). Wait for the API server VIP (10.0.16.132) to respond and all nodes to become `Ready`:

```sh
kubectl get nodes -w
```

## 5. Unset Ceph flags

Once Rook is healthy and OSDs are back up:

```sh
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- sh -c '
  for f in pause nodown norebalance norecover nobackfill noout; do
    ceph osd unset $f
  done
  ceph status
'
```

Wait for `HEALTH_OK`.

## 6. Resume Flux (if suspended)

```sh
flux -n flux-system resume kustomization --all
```
