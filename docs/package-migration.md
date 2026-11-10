# GHCR package migration

Packages now publish under `ghcr.io/jonathanagustin/uds-takserver`.
The repository rename did not move existing registry artifacts.

The manual **Migrate legacy GHCR packages** workflow inventories both namespaces.
Run it with `apply: false` to inspect the plan, or `apply: true` to copy artifacts.
It preserves manifests, architecture indexes, blobs, and signature metadata without
rebuilding images. Historical release provenance is verified before and after copying.

Existing destination tags are preserved. When a historical tag has a different
digest, its artifact receives a `legacy-<full SHA-256 digest>` tag instead.
Conflicting signature metadata stops the migration. Each successful copy is checked
through anonymous registry reads and recorded in the workflow artifact.

Legacy packages remain available because previously released bundles contain fixed
registry URLs. The migration never deletes packages or overwrites current tags.
The `k3d-core-slim-dev` checkpoint keeps its descriptive name because it creates a
k3d cluster; only its repository namespace moves.

To resume one family after an interrupted run, select it explicitly. The same
global concurrency lock prevents overlapping migration jobs:

```sh
gh workflow run migrate-packages.yaml --ref main -f apply=true -f family=packages/atak-device
```

The selected family is inventoried again. Existing matching tags are verified;
only missing artifacts are copied. Package-family names are validated against a
fixed allowlist. Historical release provenance checks apply when `takserver` or
`all` is selected. Per-family receipts identify the scope of each run.
