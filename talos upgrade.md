talosctl upgrade --nodes 10.0.16.136 --preserve=true --image factory.talos.dev/installer/4b3cd373a192c8469e859b7a0cfbed3ecc3577c4a2d346a37b0aeff9cd17cdb0:v1.9.5 --stage


talosctl upgrade --nodes 10.0.16.133 --preserve=true --image factory.talos.dev/installer/97bf8e92fc6bba0f03928b859c08295d7615737b29db06a97be51dc63004e403:v1.8.4

talosctl upgrade --nodes 10.0.16.136 --preserve=true --image factory.talos.dev/installer/97bf8e92fc6bba0f03928b859c08295d7615737b29db06a97be51dc63004e403:v1.8.4




talosctl upgrade --nodes 10.0.16.133 --preserve=true --image factory.talos.dev/installer/97bf8e92fc6bba0f03928b859c08295d7615737b29db06a97be51dc63004e403:v1.7.7

talosctl upgrade --nodes 10.0.16.136 --preserve=true --image factory.talos.dev/installer/97bf8e92fc6bba0f03928b859c08295d7615737b29db06a97be51dc63004e403:v1.7.7 --stage



## 20260215

First to v1.8.4
0d43c63bee47be4dab9fb128289e59639434fb071f58cccb20fb895419a00748


talosctl patch mc --nodes 10.0.16.133 -p '[
    {"op": "add", "path": "/machine/kubelet/image", "value": "ghcr.io/siderolabs/kubelet:v1.31.6"},
    {"op": "replace", "path": "/cluster/apiServer/image", "value": "registry.k8s.io/kube-apiserver:v1.31.6"},
    {"op": "replace", "path": "/cluster/scheduler/image", "value": "registry.k8s.io/kube-scheduler:v1.31.6"},
    {"op": "replace", "path": "/cluster/controllerManager/image", "value": "registry.k8s.io/kube-controller-manager:v1.31.6"}
    ]'
talosctl upgrade --nodes 10.0.16.133 --preserve=true --image factory.talos.dev/installer/0d43c63bee47be4dab9fb128289e59639434fb071f58cccb20fb895419a00748:v1.8.4



talosctl patch mc --nodes 10.0.16.136 -p '[
    {"op": "add", "path": "/machine/kubelet/image", "value": "ghcr.io/siderolabs/kubelet:v1.31.6"},
    {"op": "replace", "path": "/cluster/apiServer/image", "value": "registry.k8s.io/kube-apiserver:v1.31.6"},
    {"op": "replace", "path": "/cluster/scheduler/image", "value": "registry.k8s.io/kube-scheduler:v1.31.6"},
    {"op": "replace", "path": "/cluster/controllerManager/image", "value": "registry.k8s.io/kube-controller-manager:v1.31.6"}
    ]'
talosctl upgrade --nodes 10.0.16.136 --preserve=true --image factory.talos.dev/installer/0d43c63bee47be4dab9fb128289e59639434fb071f58cccb20fb895419a00748:v1.8.4


### 1.9.6
5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c
customization:
    systemExtensions:
        officialExtensions:
            - siderolabs/i915
            - siderolabs/intel-ucode
            - siderolabs/mdadm
            - siderolabs/util-linux-tools

talosctl upgrade --nodes 10.0.16.133 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.9.6 --reboot-mode powercycle

talosctl upgrade --nodes 10.0.16.135 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.9.6 --reboot-mode powercycle

talosctl upgrade --nodes 10.0.16.136 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.9.6 --reboot-mode powercycle


talosctl upgrade-k8s --nodes 10.0.16.133 --to 1.32.12 --dry-run


### 1.10.9

talosctl upgrade --nodes 10.0.16.133 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.10.9 --reboot-mode powercycle

talosctl upgrade --nodes 10.0.16.135 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.10.9 --reboot-mode powercycle

talosctl upgrade --nodes 10.0.16.136 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.10.9 --reboot-mode powercycle


### 1.11.6

talosctl upgrade --nodes 10.0.16.133 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.11.6 --reboot-mode powercycle

talosctl upgrade --nodes 10.0.16.135 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.11.6 --reboot-mode powercycle

talosctl upgrade --nodes 10.0.16.136 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.11.6 --reboot-mode powercycle


### 1.12.4

talosctl upgrade --nodes 10.0.16.133 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.12.4 --reboot-mode powercycle

talosctl upgrade --nodes 10.0.16.135 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.12.4 --reboot-mode powercycle

talosctl upgrade --nodes 10.0.16.136 --preserve=true --image factory.talos.dev/installer/5e1f9b996489d8d98a4537001db4771766998326ba72d6af4ff807ef504f9b8c:v1.12.4 --reboot-mode powercycle

## Talos v1.14 multi-document workflow

The shared and per-node templates now emit dedicated configuration documents.
Sign in to 1Password before using the Just recipes:

```sh
just talos validate-config hp1
just talos validate-config hp2
just talos validate-config hp3
just talos upgrade-node hp1
# Check node readiness, etcd, Ceph, Cilium, DNS and storage before the next node.
just talos upgrade-node hp2
just talos upgrade-node hp3
just talos upgrade-k8s 1.37.0
just talos apply-node hp1 --mode=no-reboot --dry-run
just talos apply-node hp1
# Verify recovery before repeating the config cutover for hp2 and hp3.
```

Upgrade the OS under the existing configuration first; apply the dedicated
documents only after all nodes run v1.14. The Kubernetes v1.37 target exceeds
Cilium v1.20's tested compatibility matrix (through v1.36); this is an accepted
homelab trade-off, not an upstream compatibility guarantee.

`render-config` combines base, node and watchdog documents. It decodes only the
five dedicated Kubernetes CA/service-account PEM fields after vault injection;
existing vault fields and cluster identity remain unchanged. Rendered output
contains secrets: do not commit it or print config diffs into public logs.

The full legacy `machine.kubelet` block remains because `extraMounts` has no
dedicated replacement and Talos rejects coexistence with `KubeletConfig`.
`/var/openebs/local` remains a shared writable bind mount. No `UserVolumeConfig`
or storage migration is involved, and workload isolation remains disabled.

Link aliases select the original NIC MACs without renaming physical interfaces.
Static `LinkConfig` documents disable default DHCP. A route containing only
`gateway: 10.0.16.1` preserves the IPv4 default route; v1.14 rejects an explicit
`destination: 0.0.0.0/0` in this document.

The authentication document allows anonymous requests only to `/livez`, `/readyz`
and `/healthz`, which Talos uses for API server probes. Verify these return 200
without credentials while `/api` returns 401; disabling anonymous authentication
entirely causes the unauthenticated probes to fail and restart the API server.

An etcd upgrade also advances its storage/protocol version. After the v1.14
rollout advances etcd to 3.7, do not assume that reinstalling the previous Talos
image is a safe rollback. Keep the pre-upgrade etcd snapshot and machine configs
protected, and use an explicitly supported recovery procedure.
