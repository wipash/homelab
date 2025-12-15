Review the app-template 4.5.0 migrations for these 7 apps and verify they follow /home/sean/homelab/template_instructions.md:

1. /home/sean/homelab/kubernetes/main/apps/default/authelia/app/
2. /home/sean/homelab/kubernetes/main/apps/default/autobrr/app/
3. /home/sean/homelab/kubernetes/main/apps/default/cross-seed/app/
4. /home/sean/homelab/kubernetes/main/apps/default/cups/app/
5. /home/sean/homelab/kubernetes/main/apps/default/cyberchef/app/
6. /home/sean/homelab/kubernetes/main/apps/networking/cloudflare-ddns/app/
7. /home/sean/homelab/kubernetes/main/apps/networking/cloudflared/app/

For each app, verify:
1. ocirepository.yaml exists with correct format
2. helmrelease.yaml has chartRef (not chart.spec)
3. No install/upgrade sections remain
4. No controller field in service (unless multi-controller app)
5. defaultPodOptions.securityContext exists (if original had pod.securityContext)
6. Container securityContext present (EXCEPT s6-overlay apps - see below)
7. TZ: Pacific/Auckland present
8. tmp emptyDir present (if readOnlyRootFilesystem: true)
9. Templated names used ({{ .Release.Name }})
10. No enabled: true in persistence/ingress/serviceMonitor
11. No serviceName in serviceMonitor
12. kustomization.yaml includes ocirepository.yaml
13. Multi-PVC apps have `suffix: <key>` on `type: persistentVolumeClaim` entries
14. No emptyDir mounted over paths that contain files from the image

## Security Context Exceptions

These apps should NOT have strict security contexts:
- **s6-overlay images** (linuxserver.io, paperless, karakeep/hoarder): No runAsUser/runAsGroup/runAsNonRoot, no container securityContext
- **Images with startup scripts** (excalidraw, etc.): No readOnlyRootFilesystem, possibly no runAsUser

Report any issues found.
