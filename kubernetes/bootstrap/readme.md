# Bootstrap

## Flux

### Install Cilium
```sh
kubectl apply --server-side --enable-helm --kustomize ./kubernetes/bootstrap/cilium
kubectl kustomize --enable-helm ./kubernetes/bootstrap/cilium | kubectl apply -f -
```

### Install kubelet-csr-approver
```sh
kubectl --enable-helm  apply --server-side --kustomize ./kubernetes/bootstrap/kubelet-csr-approver
kubectl kustomize --enable-helm ./kubernetes/bootstrap/kubelet-csr-approver | kubectl apply -f -
```

### Install Flux

```sh
kubectl apply --server-side --kustomize ./kubernetes/bootstrap/flux
```

### Apply Cluster Configuration

_These cannot be applied with `kubectl` in the regular fashion due to be encrypted with sops_

```sh
sops --decrypt kubernetes/bootstrap/flux/age-key.sops.yaml | kubectl apply -f -
sops --decrypt kubernetes/flux/vars/cluster-secrets.sops.yaml | kubectl apply -f -
kubectl apply -f kubernetes/flux/vars/cluster-settings.yaml
```

kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-community/helm-charts/main/charts/kube-prometheus-stack/crds/crd-prometheuses.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-community/helm-charts/main/charts/kube-prometheus-stack/crds/crd-servicemonitors.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-community/helm-charts/main/charts/kube-prometheus-stack/crds/crd-podmonitors.yaml

### Kick off Flux applying this repository

```sh
kubectl apply --server-side --kustomize ./kubernetes/flux/config
```
