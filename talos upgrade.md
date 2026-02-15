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
