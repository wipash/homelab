You need to migrate three HelmReleases from app-template 3.x to 4.5.0 following the instructions in /home/sean/homelab/template_instructions.md

Migrate these apps:
1. ...
2. ...

For each app, you need to:
1. Read the current helmrelease.yaml
2. Read the kustomization.yaml
3. Create a new ocirepository.yaml file
4. Modify the helmrelease.yaml according to the template instructions
5. Update the kustomization.yaml to include ocirepository.yaml

DO NOT:
- Commit any changes
- Run the migration script
- Push anything

Follow ALL the instructions in template_instructions.md including:
- Required changes (chartRef, remove install/upgrade sections, remove service controller field, etc.)
- Cleanup/Standardization (securityContext location, ingress naming, templated names using {{ .Release.Name }}, tmp emptyDir, reloader annotations, TZ env var, removing enabled: true from persistence/ingress/serviceMonitor, removing serviceName from serviceMonitor, etc.)

The apps are located in /home/sean/homelab/kubernetes/main/apps/default/
