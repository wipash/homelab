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

Example prompt for each subtask:
```
Migrate the HelmRelease for **{APP_NAME}** from app-template 3.x to 4.5.0 following /home/sean/homelab/template_instructions.md

Location: /home/sean/homelab/kubernetes/main/apps/{NAMESPACE}/{APP_NAME}/app/

Tasks:
1. Read the current helmrelease.yaml and kustomization.yaml
2. Create ocirepository.yaml
3. Modify helmrelease.yaml per the template instructions
4. Update kustomization.yaml to include ocirepository.yaml

DO NOT commit. Follow ALL instructions including: chartRef, remove install/upgrade sections, remove service controller field, securityContext placement, templated names {{ .Release.Name }}, reloader annotations, TZ env var, remove enabled:true from persistence/ingress/serviceMonitor, tmp emptyDir, etc.
```

Launch these subtasks in parallel for faster processing.

## Step 3: Review Changes (Subtask)

After all migration subtasks complete, launch a review subtask using the instructions in `/home/sean/homelab/review_subtask_instructions.md`.

Example prompt for review subtask:
```
Review the app-template 4.5.0 migrations for these apps and verify they follow /home/sean/homelab/template_instructions.md:

1. /home/sean/homelab/kubernetes/main/apps/{NAMESPACE}/{APP1}/app/
2. /home/sean/homelab/kubernetes/main/apps/{NAMESPACE}/{APP2}/app/
... (list all migrated apps)

For each app, verify:
1. ocirepository.yaml exists with correct format
2. helmrelease.yaml has chartRef (not chart.spec)
3. No install/upgrade sections remain
4. No controller field in service
5. defaultPodOptions.securityContext exists (if original had pod.securityContext)
6. Container securityContext present
7. TZ: Pacific/Auckland present
8. tmp emptyDir present (if readOnlyRootFilesystem: true)
9. Templated names used ({{ .Release.Name }})
10. No enabled: true in persistence/ingress/serviceMonitor
11. No serviceName in serviceMonitor
12. kustomization.yaml includes ocirepository.yaml

Report any issues found.
```

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

## Reference Files

- `/home/sean/homelab/template_instructions.md` - Detailed migration template and checklist
- `/home/sean/homelab/migrate_subtask_instructions.md` - Subtask prompt template for migrations
- `/home/sean/homelab/review_subtask_instructions.md` - Subtask prompt template for reviews
- `/home/sean/homelab/scripts/migrate-helmrelease.sh` - Migration helper script
