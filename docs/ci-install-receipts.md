# Install execution receipt foundation

`.github/scripts/install-receipt.py` produces a small, strictly typed record for
one successful ordinary install or AMD air-gap install. It does not change any
workflow decisions. No runtime workflow invokes it or uploads its output yet.
There is no receipt consumer, automatic skip, or authorization to reuse a test.
Every version 1 record explicitly sets `reuse_authorized` to `false`.

This is the producer foundation for #419, not completion of safe install reuse.
An emitted record is a caller's statement. Its `success` field is not independent
proof that the test step, cleanup, or entire job passed. A later authenticated
consumer must verify those facts against GitHub and the receipt artifact.

Git reads have five-second limits, disable lazy fetch and remote protocols, and
omit missing or oversized workflow objects rather than fetching them.

The producer records the actual checkout's `HEAD` commit and tree, rather than
assuming that the PR head or `GITHUB_SHA` was tested. This matters because PR
checkout normally uses a synthetic merge commit. It also hashes the workflow
file from that committed checkout and records the repository, event, run ID,
attempt, architecture, scenario and expected execution-step name.

## Curated input manifest

The caller must supply a JSON object with exactly these fields:

| Field | Meaning |
| --- | --- |
| `package_key` | Architecture and the existing dev-package input key. |
| `package_archive_sha256` | SHA-256 of the actual package archive deployed by the scenario. |
| `checkpoint_oci_digest` | Immutable OCI identity of the checkpoint actually selected for this architecture. |
| `core_oci_digest` | Immutable OCI identity of the Core package actually selected for this architecture. |
| `image_digests` | Exactly the six TAK image names, `cloudtak` and `postgis`, each mapped to the deployed image's SHA-256 digest. |
| `uds_version` | The UDS CLI semantic version used by the scenario. |

All digests use `sha256:` followed by 64 lowercase hexadecimal characters.
The producer validates the manifest's shape, not the truth or origin of these
identities. It does not resolve registry tags or invent missing input evidence.
A reviewed CI collector still needs to obtain them from the actual deployment.

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

A separate reviewed implementation must first wire successful execution to
receipt collection and an authenticated artifact. It must then check the exact
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
