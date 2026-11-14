# Stock SDK and CommonCommo coexistence controls

This opt-in Linux amd64 runner consumes a resource-complete, runtime-qualified
public Kernel 8.30.5 component SDK and the current fresh public CommonCommo 1.17.2
source producer. Both receipts require explicit independently reviewed SHA-256
values. CommonCommo also requires the seven explicit input roots documented in
[the fresh CoT consumer](../cot-conformance/README.md#explicit-current-fresh-producer).
These are local integrity checks, not publisher authentication or OCI cache admission.

The default `inspect` phase verifies the complete source/tool/dependency bindings,
SDK package inventories and current recipes, then writes `verified-inputs.json`.
It uses the bounded source verification tools but starts no Java compiler, JVM or
SDK native library. Output must be new, private, external and disjoint from inputs.

```sh
python3 -B takx/sdk-coexist/build.py \
  --sdk-proof /proofs/resource-complete-sdk --sdk-sha256 REVIEWED_SDK_SHA256 \
  --commoncommo-proof /proofs/fresh-commoncommo --commoncommo-sha256 REVIEWED_COMMO_SHA256 \
  --commoncommo-bindings /inputs/commoncommo-roots.json \
  --java-home /tools/qualified-jdk17 --output /proofs/new-input-inspection
```

Add `--phase qualify` and choose another fresh output for actual controls. It
compiles the owned probes against only the assembled SDK, its third-party JARs
and the verified CommonCommo JAR. Original SDK probe class bytes must match its
qualification receipt. Production class families remain inside their JARs.

Two fresh checked-JNI JVMs initialize SDK first and CommonCommo first. The actual
ELF maps must show only the selected first group before the other is initialized.
Both groups then remain loaded while the probes exercise stock SDK resources,
geometry/projection, GDAL MEM, read-only file behavior and encrypted Database2
reopen/wrong-key checks; CommonCommo constructor/PKCS12, SIGPIPE preservation,
loopback TCP/UDP routing and throwing-logger checks; then Kernel controls again.
CommonCommo enters through its normal `Commo` class initializer, which establishes
its one-time initialization guard before JNI class resolution.

All nine SDK providers must come from that process's private stock resource cache.
CommonCommo JNI must come from its verified producer prefix. Host/JDK libraries
must match the qualified identities; original SDK build paths, shared crypto or
SQLite, unexpected ELF providers and JNI/startup diagnostics fail acceptance.
The final producer, package, tools and source inputs are rechecked.

The runner has a 300-second total deadline, 256 MiB inclusive output cap, 2 GiB
free-space floor, 1 MiB complete streamed log per command, and 128 MiB per data
file. The independent data-file limit permits genuine native resource extraction.
Both JVMs use separate private application, home and extraction directories.
Child process groups are reaped on failure; crash reports remain in private output.
HOME and CODEX_HOME remain unchanged. No source download or native compilation runs.

This is co-load, resource, database, signal and loopback routing qualification.
Full SDK/client/renderer, mutual TLS under co-load, QUIC peer and actual TAK Server
interoperability remain separate gates. Failed outputs remain failed.

Offline guards load no native library or compiler:

```sh
python3 -B -m unittest discover -s takx/sdk-coexist -p test_build.py
```
