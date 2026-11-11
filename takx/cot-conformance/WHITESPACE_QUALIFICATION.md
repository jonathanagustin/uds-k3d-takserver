# Significant-whitespace follow-up

The semantic XML comparison now ignores only whitespace-only text nodes and
preserves all other text exactly. The synthetic unknown nested element contains
leading/trailing spaces, an ampersand and Unicode. A direct assertion checks the
exact decoded text `  Ω preserve & text 漢字  ` in addition to subtree comparison.

One fresh genuine run passed 34 assertions, zero strict JNI checker warnings,
19 prehashed executable ELF providers and normal shutdown/process exit. Receipt:
`/workspace/cot-protocol-conformance-proof-07/complete.json`, SHA-256
`a9d697a68ec85d006413eefaa964931d1ab00d73e346c73f83d48148a7f29898`.
All receipt-bound inputs rehashed unchanged. No native code or accepted prefix
changed; proof 06 and all earlier attempts remain untouched. The earlier
QUALIFICATION checkpoint describes the previous source revision and remains
historical evidence. This follow-up document was added after run 07 and was not
an executed runtime input.

Four offline guards, repository-relative codespell, actionlint, owned-source
license-header checks and diff checks pass. The callback-ordering and all other
scope limitations in README still apply. This is not a new SDK/client qualification.
