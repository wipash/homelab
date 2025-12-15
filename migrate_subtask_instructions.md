# Migration Subtask Instructions

Migrate the HelmRelease for **{APP_NAME}** from app-template 3.x to 4.5.0 following /home/sean/homelab/template_instructions.md

Location: /home/sean/homelab/kubernetes/main/apps/{NAMESPACE}/{APP_NAME}/app/

## Tasks

1. Read the current helmrelease.yaml and kustomization.yaml
2. Create ocirepository.yaml with correct format (see template_instructions.md)
3. Modify helmrelease.yaml according to the template instructions
4. Update kustomization.yaml to include ocirepository.yaml

## DO NOT

- Commit any changes
- Run the migration script
- Push anything

## Required Changes (from template_instructions.md)

- Replace `chart.spec` with `chartRef` pointing to OCIRepository
- Change `interval` from `30m` to `1h`
- Remove `install` section (handled by Flux defaults)
- Remove `upgrade` section (handled by Flux defaults)
- Remove `maxHistory`, `uninstall` sections if present
- Remove `controller: <name>` from service definitions ONLY for single-controller apps
- KEEP `controller: <name>` on services when the app has multiple controllers (the chart cannot auto-detect which controller a service belongs to)
- Update kustomization.yaml to include ocirepository.yaml

## Cleanup/Standardization

- Move `controllers.<name>.pod.securityContext` to `defaultPodOptions.securityContext`
- Add container-level `securityContext` if missing (allowPrivilegeEscalation, readOnlyRootFilesystem, capabilities)
- Rename `ingress.main` to `ingress.app` for consistency
- Add `tmp: type: emptyDir` persistence if container has `readOnlyRootFilesystem: true`
- Replace YAML anchors (`*app`) with `"{{ .Release.Name }}"` for existingClaim, secretRef, ingress hosts
- Use `reloader.stakater.com/auto: "true"` annotation for apps with secrets/configmaps
- Remove specific reloader annotations (`secret.reloader.stakater.com/reload`, etc.)
- Add `TZ: Pacific/Auckland` env var to all containers
- Remove `enabled: true` from persistence, ingress, serviceMonitor, service, route
- Remove `serviceName` from serviceMonitor
- For multi-PVC apps, add `suffix: <key>` to `type: persistentVolumeClaim` entries (4.x names PVCs as release name only by default)

## Security Context Exceptions

**DO NOT add strict security contexts to these apps:**

- **s6-overlay images** (linuxserver.io, paperless, karakeep/hoarder): Remove `runAsUser`, `runAsGroup`, `runAsNonRoot`, and container securityContext
- **Images with startup scripts that modify files** (excalidraw, etc.): Remove `readOnlyRootFilesystem` and potentially `runAsUser`
- **Don't mount emptyDir over paths containing files from the image** (this hides the original files)
