# Local qualification checkpoint

The existing accepted CommonCommo JNI/JAR pair was reused unchanged. No native
library, dependency, SDK or vendor source was rebuilt. The accepted producer
receipt is SHA-256
`851cc79d3189f42117579d8b6785a4f2affab7fefa5b2a26ed5bd0f6285c48ce`.

The final fresh local receipt is
`/workspace/cot-protocol-conformance-proof-06/complete.json`, SHA-256
`8844f2a12af62d2cc914aede8ffae9e2f4b222b03cf2da55f859cbda1b18d7d7`.
It records 33 actual codec/loopback assertions, two compiled harness classes,
19 actual executable ELF mappings checked against prehashed providers, zero
strict JNI checker warnings and normal process exit after native shutdown.
Output allocation was 77,824 bytes. The receipt binds source/fixture/tool/JAR/JNI
inputs, output classes, commands, log hashes, trusted host runtime inputs and
mapped providers before/after. These private paths are evidence locations, not
portable defaults or downloadable build artifacts.

Four offline guards pass. Default Unit CI adds only those guards and does not
compile Java or load native code. Official snapshots are excluded from automatic
license-header insertion and spelling changes to preserve their recorded bytes;
owned source files carry GPL-3.0-only notices.

## Preserved failed attempts

- `cot-protocol-conformance-proof-01`: ordered callback assertion failed.
- `cot-protocol-conformance-diagnostic-02`: added native diagnostics confirmed
  intact reverse-order callbacks. No vendor patch followed. The documented public
  listener contract does not promise FIFO; final checks qualify exact delivery
  and payloads, not callback ordering or same-UID state progression.
- `cot-protocol-conformance-proof-03`: runtime controls passed, but provider audit
  omitted the already-hashed Java executable from its allowlist.
- `cot-protocol-conformance-proof-04`: runtime controls passed, but the audit tried
  to reopen a temporary non-executable JVM performance-data mapping after exit.
  The final audit reads executable ELF mappings, excluding data mappings.
- `cot-protocol-conformance-proof-05`: runtime controls passed; strict provider
  audit rejected JDK17's glibc compatibility DSOs. Final policy explicitly freezes
  `librt`, `libdl` and `libpthread` as trusted host inputs before execution.

Expected malformed-input libxml diagnostics and peer-close native error messages
remain in bounded logs. They were not hidden by changing JVM warning settings.
No native input or accepted prefix changed. These results do not qualify FIFO,
full XSD validation, TLS, QUIC, an actual TAK Server, TAKX, Android, renderer or SDK.
