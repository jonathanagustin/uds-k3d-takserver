# Install execution receipts

`.github/scripts/install-receipt.py` produces a small, strictly typed record for
one successful ordinary install or AMD air-gap install. It does not change any
workflow decisions. The Test workflow optionally collects and authenticates records
after successful ordinary installs and sanitization.
There is no receipt consumer, automatic skip, or authorization to reuse a test.
Every version 1 record explicitly sets `reuse_authorized` to `false`.

This is the producer side of #419, not completion of safe install reuse. The
collector requires the correct execution step to succeed, and air-gap cleanup
to succeed. Its `success` field is not independent proof that the entire job
passed. A later consumer must verify GitHub provenance, execution and job status.

Git reads have five-second limits, disable lazy fetch and remote protocols, and
omit missing or oversized workflow objects rather than fetching them.

The producer records the actual checkout's `HEAD` commit and tree, rather than
assuming that the PR head or `GITHUB_SHA` was tested. This matters because PR
checkout normally uses a synthetic merge commit. It also hashes the workflow
file from that committed checkout and records the repository, event, run ID,
attempt, architecture, scenario and expected execution-step name.

## Curated input manifest

The low-level encoder accepts exactly these fields. The workflow collector
derives them from controlled install inputs; workflow inputs cannot supply them:

| Field | Meaning |
| --- | --- |
| `package_key` | Architecture and the existing dev-package input key. |
| `package_archive_sha256` | SHA-256 of the actual package archive deployed by the scenario. |
| `checkpoint_oci_digest` | Verified immutable checkpoint source index; the acquisition sidecar also binds its architecture manifest. |
| `core_oci_digest` | Immutable OCI identity of the Core package actually selected for this architecture. |
| `image_digests` | Exactly the six TAK image names, `cloudtak` and `postgis`, each mapped to its packaged image-manifest SHA-256 digest. |
| `uds_version` | The UDS CLI semantic version used by the scenario. |

All digests use `sha256:` followed by 64 lowercase hexadecimal characters.
The encoder validates shape. The collector reads the real generated OCI-layout
bundle, checks digest-addressed Core/app manifests and package configuration,
then validates all eight image manifests/configurations against the packaged
image index and architecture. It does not resolve mutable image/Core tags after
the test or invent missing evidence. The exact flavored package archive must
match the unflavored copy consumed by bundle creation.

Collect that manifest after the job pins its images. `pin-image-tags.sh` edits
the working tree, so the original checkout tree alone does not describe the
pinned package. Conversely, the dev-package key excludes CI, tests and bundles;
it cannot establish equivalent acceptance by itself. No rendered values,
private gateway fixtures, credentials, kubeconfig or environment dumps belong
in the manifest. Unknown fields and freeform values are rejected without being
copied into error messages or output. Existing output files are never replaced.

The producer accepts `install` on either native architecture and
`install-airgap` on AMD. It refuses unsuccessful/skipped/cancelled execution,
upgrade scenarios, private-gateway or diagnostic modes, missing identities and
architecture/key mismatches. It does not make a whole-job success claim.

## Before enabling reuse

A separate reviewed consumer must check the exact
workflow, run and latest applicable attempt, all jobs pages, expected unique
scenario jobs, real successful execution and cleanup, and the entire job result.
A receipt from an earlier green attempt must not override a newer failure or
cancellation. Same-repository identity, squash-merge ancestry, tested/pushed tree
identity, workflow/mode/schema and every relevant input still need verification.
Missing, stale, denied, malformed or ambiguous evidence must run normally.

Only install reuse is in scope for that future consumer. Both regular and both
PostgreSQL 15 upgrades must remain fresh on main. PR, manual and diagnostic
coverage must remain unchanged. Report reused install evidence explicitly;
never describe reused or skipped scenarios as newly executed acceptance.

Local proof uses synthetic git histories and malformed/secret-bearing fixture
manifests: `python3 -B -m unittest tests.test_install_receipt -v`. These tests need
no cluster, credentials, registry calls or hosted acceptance run.

Checkpoint acquisition evidence is an optional prerequisite, enabled by
`INSTALL_RECEIPT_METADATA=true`; it does not enable receipts or reuse. Fresh
pulls use the verified immutable index digest and can retain a small adjacent
`.receipt.json` sidecar containing the public source, architecture, version,
verified OCI index/platform-manifest digests, and exact archive hash. Registry
metadata is bounded to 1 MiB and eight seconds per request; the optional helper
is bounded to 30 seconds. The official Zarf checkpoint uses the `multi` OS
platform, not a Linux image platform. The helper validates the Zarf config and
layer descriptor schema and digest-addressed manifest bytes.

Cached archives are never repulled or looked up by a mutable tag for evidence.
A missing sidecar, different archive bytes/source/version/architecture/digest,
or unavailable metadata omits this optional identity while deployment continues.
A sidecar is local acquisition metadata, not an authenticated execution receipt
or proof of application acceptance. Source capture enables this option only for
ordinary same-repository install jobs; upgrades, forks, trust and focused
diagnostics omit receipt collection.

The checkout commit/tree and committed workflow hash are captured before image
pinning, then rechecked at collection. The actual post-pinning package key and
CLI version are captured immediately after pinning by bounded local commands
and must still match after execution. Metadata parsing never extracts
archive paths or emits configuration bodies; it retains at most 32 MiB of
small JSON objects and the complete collector has a 150-second outer deadline.

Collection, attestation and small artifact upload are optional and cannot fail
application acceptance. Upload requires successful GitHub build-provenance
attestation of the exact receipt file, and same-repository execution. If
acquisition proof, execution, cleanup, sanitization, identities or provenance
are unavailable, there is no authenticated receipt for that scenario. Missing
receipts are never counted as passed evidence. The existing matrices/verifier
remain responsible for acceptance.

Focused producer tests are `python3 -B -m unittest tests.test_install_receipt
tests.test_checkpoint_identity tests.test_install_artifact_inputs
tests.test_collect_install_receipt -v`. They use actual local Git repositories,
small zstd OCI fixtures, and malformed/security cases. A local UDS 0.41
actions-only package/bundle creation also confirmed the real archive schema;
it did not deploy or run a cluster and is not application acceptance.
