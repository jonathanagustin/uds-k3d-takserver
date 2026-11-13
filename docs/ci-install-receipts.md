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
| `core_oci_digest` | Immutable Open Container Initiative (OCI) identity of the Core package actually selected for this architecture. |
| `image_digests` | Exactly the six Team Awareness Kit (TAK) image names, `cloudtak` and `postgis`, each mapped to its packaged image-manifest SHA-256 digest. |
| `uds_version` | The Unified Defense Stack (UDS) command-line interface (CLI) semantic version used by the scenario. |

These eight image roles are a curated identity set, not the complete transitive
dependency closure or proof of equivalent acceptance.

All digests use `sha256:` followed by 64 lowercase hexadecimal characters.
The encoder validates shape. The collector reads the real generated OCI-layout
bundle, checks digest-addressed Core/app manifests and package configuration,
then validates all eight image manifests/configurations against the packaged
image index and architecture. It does not resolve mutable image/Core tags after
the test or invent missing evidence. The exact flavored package archive must
match the unflavored copy consumed by bundle creation.

Collect that manifest after the job pins its images. `pin-image-tags.sh` edits
the working tree, so the original checkout tree alone does not describe the
pinned package. Conversely, the dev-package key excludes continuous integration (CI), tests and bundles;
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
small JavaScript Object Notation (JSON) objects and the complete collector has a 150-second outer deadline.

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

Current acquisition validation also emits a small run/attempt-bound selected
checkpoint record and marks validation successful for the current task step.
The deployment helper clears prior proof before attempting validation. The
collector requires this current proof and rehashes that exact archive; it
cannot reconstruct successful validation from a stale cache sidecar after a
current digest check rejected it.

The collector additionally runs the pinned CLI's local-only
`uds zarf package inspect digest <absolute-archive>` and requires its canonical
OCI manifest digest to equal the generated bundle's selected `takserver`
manifest. Matching flavored/plain archive hashes alone is insufficient. This
software development kit (SDK) command validates the local package and uses a dedicated temporary
directory which is removed after the bounded 45-second command. It does not
resolve a registry tag or query the cluster. A second archive hash detects
changes during collection. Local UDS 0.41 actions-only format proof confirmed
that its canonical archive digest equals the selected bundle manifest.

Local command output is read through a bounded pipe (at most 1025 bytes held,
1024 bytes accepted), with a deadline and cleanup of the owned process group.
It deliberately does not inherit a file-size resource limit: the official local
package digest command must unpack legitimate SDK files larger than 1 KiB.
A real actions-only package with a 4 KiB definition reproduced the former
limit failure and succeeded with the pipe bound, producing the same canonical
digest as direct official CLI inspection.

Omission logging reports only a fixed allowlisted stage (for example
`checkpoint-archive`, `local-package-oci` or `bundle-oci`). Exception text,
environment values, payloads and filesystem paths are never printed. A stage
identifies where collection stopped; it does not prove a root cause or turn
missing evidence into a successful receipt.

## Read-only shadow checker

`.github/scripts/install-reuse-shadow.py` inspects one signed receipt without
changing workflow decisions. Run it manually from independently reviewed source:

```sh
python3 .github/scripts/install-reuse-shadow.py \
  --receipt /private/install-receipt-install-amd64.json \
  --bundle /private/install-receipt-install-amd64.jsonl \
  --pr PR_NUMBER --target EXACT_SQUASH_COMMIT --policy-ref REVIEWED_POLICY_COMMIT \
  --gh /path/to/gh
```

Use exact 40-character commit IDs. The policy commit must be selected independently
of downloaded evidence; it supplies the approved workflow and selected producer files.
The checker compares the workflow plus five helper files, including the directly
executed dev-package key helper. This is a partial dependency policy, not validation
of the complete acquisition, test and sanitization dependency closure; that
limitation remains an explicit permanent blocker. It does not trust an arbitrary
PR's claim of approved code. The supplied receipt and Sigstore bundle are data files,
never executable inputs. GitHub CLI must support `attestation verify` with exact
certificate, issuer, source and signer restrictions; unsupported tools or denied
application programming interface (API) reads produce a fresh-execution decision. No installation or workflow dispatch
is performed. Authenticated read access to the repository's Actions metadata,
artifacts and attestations is needed.

The checker enforces actual synthetic-merge parents, a same-repository merged PR,
a single-parent squash target and exact tested/pushed tree equality. The tested
synthetic merge's first parent must equal the squash target's only parent; its
second parent must equal the PR's current head. The PR base SHA can retain an older
fork-point snapshot after main advances, so it is not the authority for the tested
base. Different actual tested/merged parents still require fresh execution even
when their trees happen to match. Same-repository, merged-main and exact PR merge
commit bindings remain required. It reads all
bounded run/job/artifact pages, rejects superseded attempts and newer applicable
runs, requires the whole job and real execution steps to pass, and requires offline
egress restoration. GitHub may clear run `pull_requests` arrays after merge, so
selected-run affiliation comes from the verified signed PR merge ref and exact
source/head/merged-target bindings. The latest-run check conservatively includes
all same-repository PR runs for that exact workflow and head SHA, even with empty
association arrays. Returned rows must match those identities; missing or
contradictory identities require fresh execution. A newer failed, cancelled or
queued run invalidates older green evidence. Other applicable runs must be completed
first attempts: an older run ID can have a later rerun, whose order is unproven.
An older settled first-attempt failure or cancellation may be superseded by the
newer successful run. The checker does not infer rerun order from timestamps.
Positively identified foreign forks
remain ineligible. It verifies the signed receipt subject, workflow, GitHub issuer,
numeric repository identity and exact run/attempt invocation. It also downloads the
unique unexpired artifact and compares its bytes to the signed receipt. Archives
must contain one small regular receipt file; paths, symlinks and extra entries are
rejected. API/crypto commands have 45-second limits and 4 MiB output limits, with
at most ten pages per listing. Output limits apply to drained stdout/stderr
pipes, not to unrelated GitHub CLI cache files. Missing, malformed or ambiguous evidence falls back
to fresh execution. Errors omit response bodies and credentials.

Every output says `decision: execute-fresh` and `reuse_authorized: false`.
`evidence_qualified` only describes the historical evidence checks. It cannot
establish prospective package/input equivalence or runner execution-class policy,
and those blockers remain even when historical evidence passes. It cannot enable
reuse, satisfy the Test verifier or replace fresh upgrades. This checker deliberately
has no CI job, scheduling hook or skip output.

The combined PR433 trial produced authenticated AMD ordinary/offline receipts for
synthetic merge `e51c23d1712b74ddbbf348751426d07958174cf6`, whose tree matches its PR
head's tree. This does not establish that a sequence of constituent PR squash merges
is an eligible same-PR squash. Its ARM receipt authentication failed before upload;
ARM has no signed artifact and must execute fresh. Producer omission remains
independent of successful application acceptance.

Run the offline structural-policy and transport guards with
`python3 -B -m unittest tests.test_install_reuse_shadow -v`. Fixture verification
objects test policy parsing only; they are not signatures or evidence of actual
cryptographic qualification. The CLI obtains verification results only from its
cryptographic verifier.
