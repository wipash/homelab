# GitBored

Public URL: https://bored.mcgrath.nz. The HTTPRoute uses `envoy-external`;
the existing external-dns and Cloudflare wildcard tunnel provide public access.
GitBored handles GitHub sign-in and account isolation.

Configure the GitHub App callback URL as
`https://bored.mcgrath.nz/api/auth/callback`.
External Secrets reads `TOKEN_ENCRYPTION_KEY`, `GITHUB_CLIENT_SECRET`,
`GITHUB_CLIENT_ID` and `TLDRAW_KEY` from the `gitbored` item in 1Password.
The tldraw key must cover `bored.mcgrath.nz`; the application publishes it to the
browser for SDK validation. Reloader restarts the pod after secret changes;
reload an open browser tab to load the replacement key. The encryption key must
be 64 hexadecimal characters and remain stable across deployments and restores.

One replica uses `Recreate` updates and a 5Gi `synology-iscsi` PVC. SQLite and its
journal files live under `/data/gitbored`, owned by UID 1000. The subdirectory
allows the app to set its permissions without changing the PVC root ownership.
VolSync snapshots the whole volume hourly at minute 2 to MinIO and nightly at
03:37 UTC to R2, using the shared backup credentials. Keep the encryption key
in 1Password when restoring the volume; it is not included in the volume backup.

The `latest` image is pinned by digest and pulled using the existing
`ghcr-imagepullsecret`. Update the digest to deploy a later build.
Readiness, liveness and startup probe `/api/health`, including SQLite.

After Flux reconciles, check the external URL, sign in, create a board, and
confirm it reopens. Check that `gitbored` and `gitbored-r2` ReplicationSources
complete their first backups. Live GitHub sign-in requires the callback above
to be registered on the GitHub App.
