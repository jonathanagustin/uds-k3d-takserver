# Supplementary release-binding policy

`release-binding.py` adds a supplementary pre-promotion gate for issue #470.
Existing default SLSA provenance and draft-promotion checks remain intact.
The new source is locally tested; live publication acceptance remains unproven.

The versioned predicate binds the repository, checked release tag/ID/application
commit, workflow commit/run/attempt/ref and exactly two native OCI manifest
digests. Its in-toto subject is the canonical index digest. Raw index bytes must
match that digest. Only the observed OCI index format with `os: multi` is
accepted. Additional manifests are rejected unless explicitly typed Docker
attestation descriptors referring to one of the accepted architecture manifests.

The metadata input must come from trusted release-readiness checks and verified
registry output. Supplying unchecked manual metadata is insufficient. Ordinary
publication and recovery use the same schema; in recovery the application commit
can differ from the workflow commit. Already-public backfill uses only these
read-only generation/verification operations and must not bypass any publishing
policy.

`generate --metadata CHECKED.json --index RAW-INDEX.json` emits the predicate.
`verify` additionally takes `--verified-output GH-VERIFIED.json`, the successful
modern `gh attestation verify --format=json` result. This policy helper does not
cryptographically authenticate arbitrary JSON. Its eventual caller must check
gh's exit status and enforce the expected OCI digest, custom predicate type,
GitHub issuer, signer workflow, signer digest and source digest. The certified
source digest refers to the invoking workflow context, not the separately
checked application checkout. The helper also checks certificate repository IDs,
workflow identity/digest and run invocation against the expected checked context.

Field shapes were checked against retained independently verified 0.13.0 recovery
output and the 0.12.1 OCI index. The test output fixtures model policy inputs;
they are not cryptographic specimens. The workflow now revalidates the release API/tag/application source and trusted
workflow checkout before generating its checked metadata receipt. It retrieves
exact bounded index bytes from anonymous public GHCR, verifying their SHA-256.
No token or redirect target comes from an arbitrary host. After custom signing,
`verify-live` revalidates the API binding and the current registry tag, then runs
cryptographic `gh attestation verify` before enforcing the strict output policy.
The subprocess has a deadline and bounded private capture; failures disclose no
raw commands, tokens or verifier output. The verified bundle is stored separately
from default SLSA provenance before the existing promotion step.

Both API/application checks and certificate/workflow checks must pass. A recovery
certificate matching the publisher source cannot substitute for the application
commit resolved from the immutable release tag. Multiple custom attestations in
readback currently fail closed; rerun/backfill should be reviewed rather than
silently choosing one. A real approved publication is required to establish live
acceptance.
