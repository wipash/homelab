# App-Template Migration Instructions: 3.x → 4.5.0 with OCIRepository

This document provides a template for migrating HelmReleases from app-template 3.x (using HelmRepository) to 4.5.0 (using OCIRepository).

## Reference Conventions

Based on the k8s-at-home community patterns from `/home/sean/oned/kubernetes/apps/default/`.

---

## Files to Create/Modify

For each app migration, you will need to:

1. **Create** `ocirepository.yaml`
2. **Modify** `helmrelease.yaml`
3. **Update** `kustomization.yaml` to include the new ocirepository.yaml

---

## 1. OCIRepository Template

Create `ocirepository.yaml` in the app directory:

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/source.toolkit.fluxcd.io/ocirepository_v1.json
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: <app-name>
spec:
  interval: 15m
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    tag: 4.5.0
  url: oci://ghcr.io/bjw-s-labs/helm/app-template
```

**Important:** The `metadata.name` MUST match the name referenced in the HelmRelease's `chartRef.name`.

---

## 2. HelmRelease Modifications

### Remove the old chart spec section

**REMOVE this entire block:**
```yaml
spec:
  interval: 30m
  chart:
    spec:
      chart: app-template
      version: 3.7.3
      sourceRef:
        kind: HelmRepository
        name: bjw-s
        namespace: flux-system
```

### Remove install/upgrade/rollback sections (now handled by Flux defaults)

The following sections are now applied automatically via the patch in `kubernetes/main/flux/apps.yaml`:

**REMOVE these sections if present:**
```yaml
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      strategy: rollback
      retries: 3
```

The Flux defaults now handle:
- `install.crds: CreateReplace`
- `install.strategy.name: RetryOnFailure`
- `rollback.cleanupOnFail: true`
- `rollback.recreate: true`
- `upgrade.cleanupOnFail: true`
- `upgrade.crds: CreateReplace`
- `upgrade.strategy.name: RemediateOnFailure`
- `upgrade.remediation.remediateLastFailure: true`
- `upgrade.remediation.retries: 2`

Also remove any variations like `install.createNamespace`, `uninstall.keepHistory`, `maxHistory`, etc.

### Replace with chartRef

**ADD this instead:**
```yaml
spec:
  chartRef:
    kind: OCIRepository
    name: <app-name>
  interval: 1h
```

### Service Definition Change

**REMOVE** the explicit `controller:` field from services. In 4.x, the controller is auto-detected.

**Before (3.x):**
```yaml
service:
  app:
    controller: radarr
    ports:
      http:
        port: *port
```

**After (4.x):**
```yaml
service:
  app:
    ports:
      http:
        port: *port
```

### Move Pod Security Context to defaultPodOptions

Some HelmReleases have pod-level security context under `controllers.<name>.pod.securityContext`. This should be moved to `defaultPodOptions.securityContext`.

**Before (wrong location):**
```yaml
controllers:
  prowlarr:
    pod:
      securityContext:
        runAsUser: 1000
        runAsGroup: 1000
        runAsNonRoot: true
        fsGroup: 1000
        fsGroupChangePolicy: OnRootMismatch
    containers:
      app:
        # ...
```

**After (correct location):**
```yaml
controllers:
  prowlarr:
    containers:
      app:
        # ...
defaultPodOptions:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    fsGroupChangePolicy: OnRootMismatch
```

**Note:** The `controllers.<name>.pod` section can still be used for controller-specific settings like `restartPolicy: Never` (for CronJobs), `hostNetwork`, `hostPID`, `nodeSelector`, `tolerations`, `affinity`, and `topologySpreadConstraints`. Only move `securityContext` to `defaultPodOptions`.

### Add Container Security Context (if missing)

Each container should have a security context for best practices:

```yaml
containers:
  app:
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities: {drop: ["ALL"]}
```

### Standardize Ingress Naming

Use `app` as the ingress identifier instead of `main` for consistency:

**Before:**
```yaml
ingress:
  main:
    className: internal
    # ...
```

**After:**
```yaml
ingress:
  app:
    className: internal
    # ...
```

### Use Templated Names

Use Helm templating `{{ .Release.Name }}` for names that match the release name. This is preferred over YAML anchors (`*app`) for these values as it's more portable.

**Before (either of these):**
```yaml
metadata:
  name: &app radarr
# ...
persistence:
  config:
    existingClaim: *app  # YAML anchor
    # or
    existingClaim: radarr  # hardcoded
```

**After:**
```yaml
metadata:
  name: radarr  # no anchor needed for this purpose
# ...
persistence:
  config:
    existingClaim: "{{ .Release.Name }}"
```

Same for secrets and ingress hostnames:
```yaml
envFrom:
  - secretRef:
      name: "{{ .Release.Name }}-secret"
# ...
ingress:
  app:
    hosts:
      - host: "{{ .Release.Name }}.mcgrath.nz"
```

**Note:** YAML anchors are still useful for local reuse within the file (e.g., `&port 80` referenced by probes and service). Only replace anchors used for the app name pattern.

**Keep explicit names for:**
- Claims like `radarr-cache` or `plex-cache`
- Secrets with different naming patterns
- Hostnames like `sab.mcgrath.nz` (for sabnzbd) or `zigbee.mcgrath.nz` (for zigbee2mqtt)

### Standardize Reloader Annotations

Apps that use secrets or configmaps should use the generic auto-reload annotation. Remove specific reload annotations.

**Before:**
```yaml
controllers:
  audiobookshelf:
    annotations:
      secret.reloader.stakater.com/reload: &secret audiobookshelf-secret
```

**After:**
```yaml
controllers:
  audiobookshelf:
    annotations:
      reloader.stakater.com/auto: "true"
```

Remove any of these specific annotations:
- `secret.reloader.stakater.com/reload`
- `configmap.reloader.stakater.com/reload`

Replace with `reloader.stakater.com/auto: "true"` if the app uses secrets or configmaps.

### Standardize Timezone

All apps should have a TZ environment variable set to `Pacific/Auckland`. Add it if not present:

```yaml
env:
  TZ: Pacific/Auckland
```

### Remove Unnecessary Fields

In app-template 4.x, several fields are no longer needed:

**Remove `enabled: true`** from these sections (they're enabled by being defined):
- `persistence`
- `ingress`
- `serviceMonitor`
- `service`
- `route`

**Remove `serviceName`** from `serviceMonitor` (auto-detected):

**Before:**
```yaml
serviceMonitor:
  app:
    enabled: true
    serviceName: radarr
    endpoints:
      - port: http
```

**After:**
```yaml
serviceMonitor:
  app:
    endpoints:
      - port: http
```

### Keep Everything Else

The following sections remain compatible and should be preserved as-is:
- `controllers` section (including initContainers, containers, type, replicas, strategy, annotations)
- `defaultPodOptions` section
- `ingress` section
- `persistence` section
- `serviceMonitor` section
- `configMaps` section
- `dependsOn` section

---

## 3. Update kustomization.yaml

Add the ocirepository.yaml to the resources list:

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

---

## Complete Example: Standard Web App

### Before Migration (3.x)

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: radarr
spec:
  interval: 30m
  chart:
    spec:
      chart: app-template
      version: 3.7.3
      sourceRef:
        kind: HelmRepository
        name: bjw-s
        namespace: flux-system
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      strategy: rollback
      retries: 3
  dependsOn:
    - name: rook-ceph-cluster
      namespace: rook-ceph
  values:
    controllers:
      radarr:
        annotations:
          reloader.stakater.com/auto: "true"
        initContainers:
          init-db:
            image:
              repository: ghcr.io/home-operations/postgres-init
              tag: 18
            envFrom: &envFrom
              - secretRef:
                  name: radarr-secret
        containers:
          app:
            image:
              repository: ghcr.io/home-operations/radarr
              tag: 6.1.0.10293
            env:
              RADARR__SERVER__PORT: &port 80
              TZ: Pacific/Auckland
            envFrom: *envFrom
            probes:
              liveness: &probes
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /ping
                    port: *port
              readiness: *probes
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities: { drop: ["ALL"] }
    defaultPodOptions:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        fsGroupChangePolicy: OnRootMismatch
    service:
      app:
        controller: radarr
        ports:
          http:
            port: *port
    ingress:
      app:
        className: internal
        hosts:
          - host: "{{ .Release.Name }}.mcgrath.nz"
            paths:
              - path: /
                service:
                  identifier: app
                  port: http
    persistence:
      config:
        existingClaim: radarr
      tmp:
        type: emptyDir
```

### After Migration (4.5.0)

**helmrelease.yaml:**
```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: radarr
spec:
  chartRef:
    kind: OCIRepository
    name: radarr
  interval: 1h
  dependsOn:
    - name: rook-ceph-cluster
      namespace: rook-ceph
  values:
    controllers:
      radarr:
        annotations:
          reloader.stakater.com/auto: "true"
        initContainers:
          init-db:
            image:
              repository: ghcr.io/home-operations/postgres-init
              tag: 18
            envFrom: &envFrom
              - secretRef:
                  name: radarr-secret
        containers:
          app:
            image:
              repository: ghcr.io/home-operations/radarr
              tag: 6.1.0.10293
            env:
              RADARR__SERVER__PORT: &port 80
              TZ: Pacific/Auckland
            envFrom: *envFrom
            probes:
              liveness: &probes
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /ping
                    port: *port
              readiness: *probes
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities: { drop: ["ALL"] }
    defaultPodOptions:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        fsGroupChangePolicy: OnRootMismatch
    service:
      app:
        ports:
          http:
            port: *port
    ingress:
      app:
        className: internal
        hosts:
          - host: "{{ .Release.Name }}.mcgrath.nz"
            paths:
              - path: /
                service:
                  identifier: app
                  port: http
    persistence:
      config:
        existingClaim: radarr
      tmp:
        type: emptyDir
```

**ocirepository.yaml:**
```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/source.toolkit.fluxcd.io/ocirepository_v1.json
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: radarr
spec:
  interval: 15m
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    tag: 4.5.0
  url: oci://ghcr.io/bjw-s-labs/helm/app-template
```

---

## CronJob Example

For CronJob-type controllers, the pattern is the same. Example:

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: recyclarr
spec:
  chartRef:
    kind: OCIRepository
    name: recyclarr
  interval: 1h
  values:
    controllers:
      recyclarr:
        type: cronjob
        cronjob:
          schedule: "@daily"
          backoffLimit: 0
          concurrencyPolicy: Forbid
          successfulJobsHistory: 1
          failedJobsHistory: 1
          ttlSecondsAfterFinished: 86400
        containers:
          app:
            image:
              repository: ghcr.io/recyclarr/recyclarr
              tag: 7.5.2
            args:
              - sync
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities: { drop: ["ALL"] }
        pod:
          restartPolicy: Never
    defaultPodOptions:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        fsGroupChangePolicy: OnRootMismatch
    persistence:
      config:
        existingClaim: recyclarr
      config-file:
        type: configMap
        name: recyclarr-configmap
        globalMounts:
          - path: /config/recyclarr.yml
            subPath: recyclarr.yml
      tmp:
        type: emptyDir
```

---

## Migration Checklist

For each app:

### Required Changes
- [ ] Create `ocirepository.yaml` with correct app name
- [ ] Remove `chart.spec` section from helmrelease.yaml
- [ ] Add `chartRef` section pointing to OCIRepository
- [ ] Change `interval` from `30m` to `1h`
- [ ] Remove `install` section (now handled by Flux defaults)
- [ ] Remove `upgrade` section (now handled by Flux defaults)
- [ ] Remove `maxHistory`, `uninstall` sections if present
- [ ] Remove `controller: <name>` from service definitions
- [ ] Update `kustomization.yaml` to include ocirepository.yaml

### Cleanup/Standardization
- [ ] Move `controllers.<name>.pod.securityContext` to `defaultPodOptions.securityContext`
- [ ] Add container-level `securityContext` if missing (allowPrivilegeEscalation, readOnlyRootFilesystem, capabilities)
- [ ] Rename `ingress.main` to `ingress.app` for consistency
- [ ] Add `tmp: type: emptyDir` persistence if container has `readOnlyRootFilesystem: true` and lacks a writable /tmp
- [ ] Replace YAML anchors (`*app`) with `"{{ .Release.Name }}"` for existingClaim, secretRef, ingress hosts
- [ ] Remove unused `&app` anchors from metadata.name (keep if used elsewhere in file)
- [ ] Use `reloader.stakater.com/auto: "true"` annotation for apps with secrets/configmaps
- [ ] Remove specific reloader annotations (`secret.reloader.stakater.com/reload`, etc.)
- [ ] Add `TZ: Pacific/Auckland` env var to all containers
- [ ] Remove `enabled: true` from persistence, ingress, serviceMonitor, service, route
- [ ] Remove `serviceName` from serviceMonitor

### Verification
- [ ] Verify `defaultPodOptions.securityContext` exists (if original had `pod.securityContext`)
- [ ] Verify the app name in metadata.name matches across all files
- [ ] Verify controller name matches the app name

---

## Breaking Changes to Be Aware Of

1. **Label Change**: `app.kubernetes.io/component` is renamed to `app.kubernetes.io/controller`. This causes Deployments/StatefulSets to be **recreated** (not updated in place).

2. **Service Account Tokens**: Now use short-lived tokens by default. To keep static tokens, set `staticToken: true` on the service account.

3. **Resource Naming**: The naming scheme changed. Resources may get new names, potentially removing old ones. Ensure PVCs use `existingClaim` to prevent data loss.

---

## What NOT to Change

- Keep your existing `controllers` structure (initContainers, containers, etc.)
- Keep your existing `defaultPodOptions` section
- Keep your existing `ingress` configuration (we use ingress, not route)
- Keep your existing `persistence` configuration
- Keep your existing `serviceMonitor` configuration
- Keep your existing `dependsOn` dependencies
- Keep your existing user/group IDs (1000 is the standard)
- Keep your existing security contexts
