# Schema and process-bound follow-up

One fresh run used the unchanged accepted CommonCommo JNI/JAR and JDK 17, with
no native build or accepted-prefix mutation. The profile now exercises the actual
JAXP SchemaFactory/Validator against the pinned unchanged MITRE base CoT XSD.
External DTD/schema access is disabled. The owned synthetic message validates,
including its unknown nested detail through the schema's lax wildcard. Missing
UID, invalid numeric latitude and invalid date are rejected. The unchanged
historical official marker lacks the newer required access attribute and is
rejected; its genuine codec-normalized output validates with access=Undefined.
Individual detail-schema coverage remains unqualified.

The runner preserves system HOME/CODEX_HOME, uses owned application/temp paths,
and limits heap/metaspace, active processors, Java compilation target and annotation
processing. Child hard file-size, core-dump and CPU limits, live free-space checks
and final-receipt budget reservations are active. No warning-suppression option
was added. Six offline guards include a real child hard-limit test and environment
preservation/injection checks.

Fresh receipt: `/workspace/cot-protocol-conformance-proof-08/complete.json`,
SHA-256 `de16cf0ec677bc0fbb7ff927e0e8db61dd83c95f3f989f6c8832fd9fd749a72e`.
It records 40 assertions, zero strict JNI warnings, 19 prehashed executable ELF
providers and normal process exit after native shutdown. All bound source,
fixture, tool and provider hashes rechecked unchanged. Source and process-limit
vectors are recorded in the receipt. Proofs 06/07 and all failed attempts remain
untouched. This document was added after run 08 and was not a runtime input.

Six offline guards, repository-relative codespell, actionlint, owned-source
license checks and diff checks pass. Earlier qualification documents are
historical checkpoints. Callback FIFO, all detail schemas, TLS/QUIC, live TAK
Server, Android, TAKX client, renderer and full SDK qualification remain outside
this slice.
