# Helm charts in GHCR

New packages use `ghcr.io/jonathanagustin/uds-takserver`. The separate
[GHCR migration](package-migration.md) preserves historical artifacts and keeps
legacy URLs available for older releases.

The charts publisher handles the two existing charts independently:

| Source | OCI chart name | Scope |
| --- | --- | --- |
| `charts/takserver` | `ghcr.io/jonathanagustin/uds-takserver/charts/uds-takserver-config` | TAK's UDS configuration resources |
| `charts/cloudtak` | `ghcr.io/jonathanagustin/uds-takserver/charts/uds-cloudtak` | CloudTAK resources used by the package |

These are not an all-in-one TAK Helm installation. The application package
orders the upstream TAK chart, UDS configuration, Pepr behavior and related
components. UDS Core CRDs, certificates, values and package substitutions also
matter. Use the signed Zarf package for that installation flow. Chart
publication does not change local chart paths, Helm release names or templates.

## Inspect a published chart

A version is available after its charts workflow succeeds. For example, after
backfilling 0.11:

```sh
VERSION=0.11.0
helm pull oci://ghcr.io/jonathanagustin/uds-takserver/charts/uds-takserver-config --version "$VERSION"
helm show chart "uds-takserver-config-${VERSION}.tgz"
```

For content verification, prefer the immutable OCI digest printed by the
publisher. Its keyless packaging attestation can be checked with:

```sh
gh attestation verify oci://ghcr.io/jonathanagustin/uds-takserver/charts/uds-takserver-config@sha256:<digest> --owner jonathanagustin
```

The attestation identifies the packaging workflow. Packaged chart and OCI
annotations identify the actual source repository and tag commit. No image
compilation or complete application validation is implied by this packaging
attestation.

## Publish a release or backfill charts only

Future Release Please releases call `charts.yaml` directly, since a release
created with `GITHUB_TOKEN` does not trigger another release event. Ordinary
published release events also work. Both routes validate an existing stable
`vMAJOR.MINOR.PATCH` tag, its Release Please manifest and ancestry on main.

A manual dispatch on main can backfill an existing tag without rebuilding
images, republishing Zarf packages or starting clusters:

```sh
gh workflow run charts.yaml --ref main -f tag=v0.11.0
```

The publisher implementation comes from the invoking workflow checkout; chart
sources are archived separately from the validated tag. The old tag does not
need to contain this new publisher script. Both packaged chart versions match
the project release; each chart's original `appVersion` remains unchanged.
Source/revision, tag URL and license annotations are added to the packages, not
the source charts. Each archive also includes the actual root LICENSE from
that same tag.

Packages have deterministic archive metadata based on the tag commit. An
existing version is accepted only when its exact chart layer bytes and source
annotations match. Both charts are checked before either is published, and
publication is serialized per release tag. A conflicting version fails rather
than replacing it. Registry authentication, TLS and transport failures are not
interpreted as missing versions.

Each result is pulled by digest and compared with the local package, then
pulled again with empty registry credentials. This tests actual public access;
repository association alone does not prove package visibility. A failed
anonymous pull stops the workflow. No package deletion or visibility setting
change is performed by the publisher.

## Local checks

Packaging can be reviewed without contacting a registry:

```sh
uv run --no-project --with pyyaml==6.0.3 python .github/scripts/publish-charts.py \
  --tag v0.11.0 --output /tmp/helm-charts
```

The script requires the pinned Helm and crane tools on `PATH`. Unit tests cover
source/version validation, deterministic packaging, render preservation,
collision handling and fail-closed registry errors. Loopback-only plain HTTP
is available for an ephemeral local OCI registry; production always uses TLS.
