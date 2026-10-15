# VolSync Template

## Flux Kustomization

This requires `postBuild` configured on the Flux Kustomization

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app plex
  namespace: flux-system
spec:
  # ...
  postBuild:
    substitute:
      APP: *app
      VOLSYNC_CAPACITY: 5Gi
      VOLSYNC_LOCAL_SCHEDULE: "<unused minute> * * * *"
      VOLSYNC_REMOTE_SCHEDULE: "<next free 5-minute slot> * * *"
```

and then call the template in your applications `kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  # ...
  - ../../../../templates/volsync
```

## Required `postBuild` vars:

- `APP`: The application name
- `VOLSYNC_CAPACITY`: The PVC size
- `VOLSYNC_LOCAL_SCHEDULE`: Hourly MinIO backup cron, on a minute no other app uses
- `VOLSYNC_REMOTE_SCHEDULE`: Nightly R2 backup cron, on a free 5-minute slot

See "VolSync schedules" in the repo's `AGENTS.md` for how to pick the schedule slots.
