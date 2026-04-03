# File Templates Reference

This document contains the exact YAML templates for each file in a deployed app. Variables in `<angle-brackets>` should be substituted. Optional sections are marked with comments.

## Table of Contents
1. [ks.yaml](#ksyaml)
2. [app/ocirepository.yaml](#ocirepositoryaml)
3. [app/kustomization.yaml](#kustomizationyaml)
4. [app/helmrelease.yaml](#helmreleaseyaml)
5. [app/externalsecret.yaml](#externalsecretyaml)
6. [app/pvc.yaml](#pvcyaml)

---

## ks.yaml

### Minimal (no persistence, no secrets)

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/kustomize.toolkit.fluxcd.io/kustomization_v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app <appname>
  namespace: <namespace>
spec:
  targetNamespace: <namespace>
  path: ./kubernetes/apps/<namespace>/<appname>/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-cluster
    namespace: flux-system
  wait: false
  interval: 30m
  retryInterval: 1m
  timeout: 5m
  postBuild:
    substitute:
      APP: *app
```

### With VolSync persistence

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/kustomize.toolkit.fluxcd.io/kustomization_v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app <appname>
  namespace: <namespace>
spec:
  targetNamespace: <namespace>
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  dependsOn:
    - name: rook-ceph-cluster
      namespace: flux-system
  path: ./kubernetes/apps/<namespace>/<appname>/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-cluster
    namespace: flux-system
  wait: false
  interval: 30m
  retryInterval: 1m
  timeout: 5m
  postBuild:
    substitute:
      APP: *app
      VOLSYNC_CAPACITY: <capacity>
  components:
    - ../../../../components/volsync
```

### With VolSync + ExternalSecrets

Add to `dependsOn`:
```yaml
  dependsOn:
    - name: rook-ceph-cluster
      namespace: flux-system
    - name: external-secrets-stores
      namespace: kube-system
```

### With VolSync + ExternalSecrets + Postgres

Add to `dependsOn`:
```yaml
  dependsOn:
    - name: cloudnative-pg-cluster
      namespace: flux-system
    - name: external-secrets-stores
      namespace: kube-system
```

---

## ocirepository.yaml

Always the same structure, only the metadata name changes:

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/source.toolkit.fluxcd.io/ocirepository_v1.json
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: <appname>
spec:
  interval: 15m
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    tag: 4.6.2
  url: oci://ghcr.io/bjw-s-labs/helm/app-template
```

---

## kustomization.yaml

### Minimal (no secrets, no extra PVCs)

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
  - ./ocirepository.yaml
```

### With ExternalSecret

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./externalsecret.yaml
  - ./helmrelease.yaml
  - ./ocirepository.yaml
```

### With ExternalSecret + extra PVC

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./externalsecret.yaml
  - ./pvc.yaml
  - ./helmrelease.yaml
  - ./ocirepository.yaml
```

### With configMapGenerator (for config files in resources/)

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
  - ./ocirepository.yaml
configMapGenerator:
  - name: <appname>-configmap
    files:
      - <filename>=./resources/<filename>
generatorOptions:
  disableNameSuffixHash: true
  annotations:
    kustomize.toolkit.fluxcd.io/substitute: disabled
```

---

## helmrelease.yaml

### Standard app (with persistence, secrets, internal route)

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: <appname>
spec:
  chartRef:
    kind: OCIRepository
    name: <appname>
  interval: 1h
  values:
    controllers:
      <appname>:
        annotations:
          reloader.stakater.com/auto: "true"

        containers:
          app:
            image:
              repository: <image-repo>
              tag: <image-tag>@sha256:<digest>
            env:
              TZ: Pacific/Auckland
              <PORT_ENV_VAR>: &port <port-number>
            probes:
              liveness:
                enabled: true
              readiness:
                enabled: true
              startup:
                enabled: true
                spec:
                  failureThreshold: 30
                  periodSeconds: 5
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities: { drop: ["ALL"] }
            resources:
              requests:
                cpu: <cpu-request>
              limits:
                memory: <memory-limit>

    defaultPodOptions:
      securityContext:
        runAsNonRoot: true
        runAsUser: <uid>
        runAsGroup: <gid>
        fsGroup: <gid>
        fsGroupChangePolicy: OnRootMismatch
        seccompProfile: { type: RuntimeDefault }

    service:
      app:
        controller: <appname>
        ports:
          http:
            port: *port

    route:
      app:
        parentRefs:
          - name: envoy-internal
            namespace: networking
            sectionName: https
        hostnames:
          - "{{ .Release.Name }}.mcgrath.nz"
        rules:
          - backendRefs:
              - identifier: app
                port: http

    persistence:
      config:
        existingClaim: "{{ .Release.Name }}"
        globalMounts:
          - path: <mount-path>
      tmp:
        type: emptyDir
```

### With custom command/args

Add to the container spec:
```yaml
            command:
              - <command>
            args:
              - <arg1>
              - <arg2>
```

### With secrets (envFrom pattern)

Add to the container spec:
```yaml
            envFrom:
              - secretRef:
                  name: <appname>-secret
```

### With Postgres init container (shared envFrom anchor)

```yaml
    controllers:
      <appname>:
        annotations:
          reloader.stakater.com/auto: "true"
        initContainers:
          init-db:
            image:
              repository: ghcr.io/home-operations/postgres-init
              tag: 18
            envFrom: &envFrom
              - secretRef:
                  name: <appname>-secret
        containers:
          app:
            # ... image, env, etc ...
            envFrom: *envFrom
```

### With custom health probe

```yaml
            probes:
              liveness: &probes
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: <health-path>
                    port: *port
                  initialDelaySeconds: 0
                  periodSeconds: 10
                  timeoutSeconds: 1
                  failureThreshold: 3
              readiness: *probes
```

### With NFS media mount

Add to persistence:
```yaml
      media:
        type: nfs
        server: 172.20.0.1
        path: /volume1/Media
        globalMounts:
          - path: /media
```

### Stateless app (no persistence claim, maybe replicas)

Omit the `config` persistence entry. Optionally add replicas and topology spread:
```yaml
    controllers:
      <appname>:
        replicas: 2
        strategy: RollingUpdate
        # ...
        pod:
          topologySpreadConstraints:
            - maxSkew: 1
              topologyKey: kubernetes.io/hostname
              whenUnsatisfiable: DoNotSchedule
              labelSelector:
                matchLabels:
                  app.kubernetes.io/name: <appname>
```

---

## externalsecret.yaml

### Standard (single 1Password item)

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/external-secrets.io/externalsecret_v1.json
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <appname>
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-connect
  target:
    name: <appname>-secret
    template:
      engineVersion: v2
      data:
        <ENV_VAR_NAME>: "{{ .<1PASSWORD_FIELD_NAME> }}"
  dataFrom:
    - extract:
        key: <1password-item-name>
```

### With Postgres (multiple 1Password items)

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/external-secrets.io/externalsecret_v1.json
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <appname>
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-connect
  target:
    name: <appname>-secret
    template:
      engineVersion: v2
      data:
        # App-specific secrets
        <APP_SECRET_VAR>: "{{ .<1PASSWORD_FIELD> }}"

        # Postgres connection
        <APP_DB_HOST_VAR>: &dbHost postgres17-rw.database.svc.cluster.local
        <APP_DB_PORT_VAR>: "5432"
        <APP_DB_USER_VAR>: &dbUser "{{ .<POSTGRES_USER_FIELD> }}"
        <APP_DB_PASS_VAR>: &dbPass "{{ .<POSTGRES_PASS_FIELD> }}"
        <APP_DB_NAME_VAR>: &dbName <database-name>

        # Init container vars (standard names)
        INIT_POSTGRES_DBNAME: *dbName
        INIT_POSTGRES_HOST: *dbHost
        INIT_POSTGRES_USER: *dbUser
        INIT_POSTGRES_PASS: *dbPass
        INIT_POSTGRES_SUPER_PASS: "{{ .POSTGRES_SUPER_PASS }}"
  dataFrom:
    - extract:
        key: <1password-item-name>
    - extract:
        key: cloudnative-pg
```

---

## pvc.yaml

For additional PVCs (cache volumes, data that doesn't need backup):

```yaml
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: <appname>-<purpose>
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: <size>
  storageClassName: ceph-block
```

---

## Namespace Registration

After creating all app files, add the app's `ks.yaml` to the namespace kustomization at `kubernetes/apps/<namespace>/kustomization.yaml`:

```yaml
resources:
  # ... existing apps ...
  - ./<appname>/ks.yaml    # Add in alphabetical order
```
