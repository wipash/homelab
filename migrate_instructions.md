# App-Template 4.5.0 Migration Instructions

## Overview

We are migrating HelmReleases from app-template 3.x (using HelmRepository) to 4.5.0 (using OCIRepository). This involves:

1. Creating an `ocirepository.yaml` file for each app
2. Modifying the `helmrelease.yaml` to use `chartRef` instead of `chart.spec`
3. Applying various cleanup/standardization changes per the template
4. Updating `kustomization.yaml` to include the new ocirepository.yaml

After the YAML changes are committed, workloads need to be recreated due to an immutable label change (`app.kubernetes.io/component` → `app.kubernetes.io/controller`).

## Step 1: Identify Apps to Migrate

Run the migration script to list pending apps:
```bash
/home/sean/homelab/scripts/migrate-helmrelease.sh --list-pending
```

Select a range of apps to migrate (e.g., all apps starting with a specific letter, or a specific namespace).

## Step 2: Run Migration Subtasks (Parallel)

For each app that needs migration, launch a parallel subtask using the instructions in `/home/sean/homelab/migrate_subtask_instructions.md`.

Launch these subtasks in parallel for faster processing.

## Step 3: Review Changes (Subtask)

After all migration subtasks complete, launch a review subtask using the instructions in `/home/sean/homelab/review_subtask_instructions.md`.


## Step 4: Commit Changes

After review passes, commit all the migrated apps:
```bash
git add kubernetes/main/apps/... && git commit -m "feat: migrate {APP_NAMES} to app-template 4.5.0"
```

## Step 5: Trigger Workload Recreation

After the commit is pushed and Flux has attempted reconciliation (which will fail due to immutable labels), run:

```bash
/home/sean/homelab/scripts/migrate-helmrelease.sh --failing
```

This will:
1. Auto-detect all failing HelmReleases
2. Suspend them all in parallel
3. Delete their workloads in parallel
4. Resume them all in parallel (triggering recreation with new labels)

## Troubleshooting Common Post-Migration Issues

### PVC Name Conflicts (rollback fails with "storage: Forbidden: field can not be less than")

**Cause:** In 4.x, PVCs are named after the release name only (e.g., `hoarder`), not `{release}-{persistence-key}` (e.g., `hoarder-meilisearch`). This causes conflicts when an app has multiple PVCs.

**Fix:** Add `suffix: <key>` to persistence entries that use `type: persistentVolumeClaim`:
```yaml
persistence:
  meilisearch:
    type: persistentVolumeClaim
    suffix: meilisearch  # Creates "hoarder-meilisearch"
```

### s6-overlay Permission Denied ("/run belongs to uid 0")

**Cause:** Apps using s6-overlay (linuxserver.io, paperless, karakeep/hoarder) need root at startup to configure `/run`.

**Fix:** Remove security context restrictions for the main container:
- Remove `runAsUser`, `runAsGroup`, `runAsNonRoot` from `defaultPodOptions.securityContext`
- Remove container-level `securityContext` entirely
- Keep `fsGroup` only for sidecar containers that need it (apply via `controllers.<name>.pod.securityContext`)

### Startup Script Permission Denied ("sed: can't create temp file")

**Cause:** Container has `readOnlyRootFilesystem: true` but startup script needs to modify files, OR container runs as non-root user but files are root-owned.

**Fix:**
- Remove `readOnlyRootFilesystem: true` from container securityContext
- Remove `runAsUser`/`runAsNonRoot` to let container run as its default user
- Don't mount emptyDir over paths that contain files from the image

### Immutable Selector Labels (handled by migrate script)

**Cause:** Label changed from `app.kubernetes.io/component` to `app.kubernetes.io/controller`.

**Fix:** Already handled by Step 5 - the migrate script deletes and recreates workloads.

## Reference Files

- `/home/sean/homelab/template_instructions.md` - Detailed migration template and checklist
- `/home/sean/homelab/migrate_subtask_instructions.md` - Subtask prompt template for migrations
- `/home/sean/homelab/review_subtask_instructions.md` - Subtask prompt template for reviews
- `/home/sean/homelab/scripts/migrate-helmrelease.sh` - Migration helper script
