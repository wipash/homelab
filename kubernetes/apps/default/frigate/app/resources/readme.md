# Frigate configuration migrations

`config.yml` is mounted read-only from a Flux-managed ConfigMap. Frigate cannot
save automatic migrations; apply the target release's migration in Git instead.

For [0.18](https://github.com/blakeblackshear/frigate/releases/tag/v0.18.0),
the config matches upstream `migrate_018_0`: named masks with unchanged
coordinates, a named GenAI provider with `descriptions` and `chat` roles, and
`version: "0.18-0"`. Existing zones already use coordinate mappings.

Validate with the target image's `FrigateConfig.parse(..., safe_load=False)`.
Do not rely on `--validate-config`'s exit status alone: 0.18 can fall back to
safe mode after validation errors. After Flux reconciliation, verify camera
processing and detector statistics, not just HTTP readiness.
