---
name: deploy-app
description: |
  Deploy a new application to the homelab Kubernetes cluster using the bjw-s app-template Helm chart with Flux GitOps. Use this skill whenever the user wants to deploy a new service, container, app, or Docker image to the cluster. Also use when they say things like "add X to the cluster", "set up X", "run X in k8s", or mention deploying any container image. This covers the full scaffolding: directory structure, Flux Kustomization, HelmRelease, OCIRepository, ExternalSecrets, PVCs, HTTPRoutes, and registering the app in the namespace kustomization.
---

# Deploy App to Homelab Cluster

You are deploying a new application to Sean's homelab Kubernetes cluster. The cluster runs Flux CD for GitOps, uses the bjw-s app-template Helm chart for all apps, Gateway API with Envoy Gateway for routing, ExternalSecrets with 1Password for secrets, VolSync for backup, and Ceph for storage.

The repo is at `/home/sean/homelab` and all Kubernetes manifests live under `kubernetes/`.

## Interview the User

Before generating any files, gather the following. The user may provide some of this upfront (e.g., "deploy nousresearch/hermes-agent:latest with 2gb ram, 1cpu, 5gb persistence on /opt/data"). Extract what you can and ask about the rest.

### Required
- **Image**: container image repository and tag (e.g., `ghcr.io/org/app:v1.0.0`)
- **App name**: short lowercase name for the app (infer from image name if not given)
- **Port**: the container's listening port
- **Resources**: CPU request and memory limit (e.g., "1 CPU, 2Gi memory")

### Image Digest Pinning

All images in this cluster are pinned to their sha256 digest for immutability. After the user gives you an image + tag, look up the digest by running:

```bash
docker manifest inspect <repository>:<tag> -v 2>/dev/null | jq -r '.[0].Descriptor.digest // .Descriptor.digest' 2>/dev/null || \
  skopeo inspect --raw "docker://<repository>:<tag>" | jq -r '.digest // empty' 2>/dev/null || \
  crane digest "<repository>:<tag>" 2>/dev/null
```

Try each method in order until one succeeds (the user may have docker, skopeo, or crane installed). If none work, ask the user to provide the digest or leave a `# TODO: pin digest` comment.

The resulting tag format in the HelmRelease is: `<tag>@sha256:<hex>` (e.g., `v1.0.0@sha256:abc123...`).

If the user specifies `latest` as the tag, still pin the digest — `latest` is mutable and the digest ensures reproducibility.

### Ask about these
- **Command/args**: custom container command or args? (e.g., `gateway run`)
- **Persistence**: does the app need persistent storage? If yes:
  - How much? (becomes `VOLSYNC_CAPACITY` — default 5Gi)
  - What mount path? (default `/config`)
  - Any additional volumes (cache, data dirs)?
- **NFS media mount**: does it need access to the NAS media library at `172.20.0.1:/volume1/Media`?
- **Secrets**: does the app need secrets from 1Password? If yes:
  - What env vars need to be secret?
  - Does it need a Postgres database? (triggers the init-db pattern)
  - What 1Password item name(s) to pull from?
- **Plain env vars**: any non-secret environment configuration?
- **Route**: does it need an HTTP route?
  - Internal only (`envoy-internal`) or public (`envoy-external`)?
  - Custom hostname or default `<appname>.mcgrath.nz`?
- **Namespace**: which namespace? (default: `default`)
- **UID/GID**: what user should the container run as? (default: `568:568` — Linuxserver.io convention)
- **Probes**: does the app have a health endpoint? (e.g., `/health`, `/ping`, `/api/health`)

## Directory Structure

For an app called `myapp` in the `default` namespace, create:

```
kubernetes/apps/default/myapp/
  ks.yaml
  app/
    kustomization.yaml
    ocirepository.yaml
    helmrelease.yaml
    externalsecret.yaml      # only if secrets are needed
    pvc.yaml                 # only if extra PVCs beyond volsync are needed
```

Then register the app by editing the namespace kustomization at `kubernetes/apps/<namespace>/kustomization.yaml` — add `- ./<appname>/ks.yaml` to the `resources` list in alphabetical order. This is not optional; the app won't be deployed without it.

## File Templates

Read the reference templates at `references/templates.md` for the exact YAML to generate for each file. The templates contain the precise patterns, schemas, annotations, and conventions used in this cluster.

Key conventions to follow exactly:
- YAML anchors: `&app` for the app name, `&port` for the port, `&probes` for probe reuse, `&envFrom` for shared secret refs
- Container is always named `app`
- Controller name matches the app name
- `reloader.stakater.com/auto: "true"` on every controller
- Security context: `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities: { drop: ["ALL"] }`
- Pod security: `runAsNonRoot: true`, `fsGroupChangePolicy: OnRootMismatch`, `seccompProfile: { type: RuntimeDefault }`
- Resources: always set `requests.cpu` and `limits.memory`, never set `limits.cpu`
- `TZ: Pacific/Auckland` in every container's env
- Every app gets an `emptyDir` for `/tmp`
- Route `sectionName: https` is always set
- OCIRepository name matches the app name, always points to `oci://ghcr.io/bjw-s-labs/helm/app-template` tag `4.6.2`
- HelmRelease `chartRef` references the OCIRepository by the app name
- The `ks.yaml` sourceRef is `GitRepository/flux-cluster` in `flux-system`
- ExternalSecret target is always `<appname>-secret`, secretStoreRef is `ClusterSecretStore/onepassword-connect`

## Persistence Patterns

Choose the right pattern based on what the app needs:

### VolSync-backed config storage (most apps)
Add the volsync component to `ks.yaml` and reference the PVC in helmrelease:
- `ks.yaml`: add `components: [../../../../components/volsync]` and set `VOLSYNC_CAPACITY` in postBuild.substitute
- `ks.yaml`: add `dependsOn` for `rook-ceph-cluster` (namespace: `flux-system`)
- HelmRelease: `persistence.config.existingClaim: "{{ .Release.Name }}"`

### Extra PVCs (cache, data that doesn't need backup)
Create a separate `pvc.yaml` with `storageClassName: ceph-block`.

### NFS media mount
```yaml
persistence:
  media:
    type: nfs
    server: 172.20.0.1
    path: /volume1/Media
    globalMounts:
      - path: /media
```

### emptyDir (always include for /tmp)
```yaml
persistence:
  tmp:
    type: emptyDir
```

## Secrets Pattern (ExternalSecrets + 1Password)

When the app needs secrets:
- Add `dependsOn` for `external-secrets-stores` (namespace: `kube-system`) in `ks.yaml`
- Create `externalsecret.yaml` pulling from the `onepassword-connect` ClusterSecretStore
- The Kubernetes Secret name is always `<appname>-secret`
- In HelmRelease, use `envFrom: [{secretRef: {name: "<appname>-secret"}}]`
- Use the `&envFrom` / `*envFrom` anchor pattern when init containers also need the secrets

### Postgres database pattern
When the app needs Postgres, add an init container:
```yaml
initContainers:
  init-db:
    image:
      repository: ghcr.io/home-operations/postgres-init
      tag: 18
    envFrom: &envFrom
      - secretRef:
          name: <appname>-secret
```
And in the ExternalSecret, include the `INIT_POSTGRES_*` vars plus pull from the `cloudnative-pg` 1Password item. The Postgres host is `postgres17-rw.database.svc.cluster.local`.

## Route Patterns

Routes always need explicit `rules` with `backendRefs` — don't rely on implicit routing. This ensures the Gateway API knows exactly which service and port to target.

### Internal route (default for most apps)
```yaml
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
```

### External route (public-facing apps)
```yaml
route:
  app:
    parentRefs:
      - name: envoy-external
        namespace: networking
        sectionName: https
    hostnames:
      - "{{ .Release.Name }}.mcgrath.nz"
    rules:
      - backendRefs:
          - identifier: app
            port: http
```

## After Generating Files

1. **Edit the namespace kustomization** — this is not a suggestion, do it. Open `kubernetes/apps/<namespace>/kustomization.yaml` and add `- ./<appname>/ks.yaml` to the `resources` list in alphabetical order.
2. Remind the user to create the 1Password item if they're using ExternalSecrets
3. If using Postgres, remind them the database will be auto-created by the init container
4. Mention they can `git add` and push to trigger Flux reconciliation
5. Offer to add Gatus monitoring annotations if desired
