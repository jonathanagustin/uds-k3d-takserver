# Two genuine crypto groups in one process

This optional Linux amd64 experiment tests ELF ownership of two real source-built OpenSSL implementations. It does not build CommonCommo, full Kernel/JNI or a TAKX client. Its `q_*` and `m_*` entrypoints are owned test adapters, never replacement SDK APIs.

The first group builds the official ATAK quictls **3.0.14+quic1** archive with its original Windows portability patch, pinned source pre/postimages and license text. It builds genuine PIC static `libssl.a` and `libcrypto.a`. The second group reuses the normative `native-sqlcipher` producer's complete OpenSSL **3.5.9** and SQLCipher **4.5.7** proof. Reuse verifies producer recipe, source/archive/license identity, untouched source inventory, installed bytes, positive outputs, actual build tools and runtime library hashes. No golden private path or receipt digest alone grants acceptance.

Both real experiment DSOs link their exact static inputs with GNU ld `--exclude-libs,libcrypto.a:libssl.a:libsqlite3.a`, a narrow owned API export script and `--no-undefined`. Static crypto alone would still export/interpose symbols; the recipe checks actual dynamic symbols, dependencies, runtime maps and TEXTREL status. There are no renamed libraries, crypto aliases or fabricated isolation.

The first preserved attempt built quictls and passed its real DSO symbol/dependency checks, then stopped at the modern wrapper because the owned compiler command omitted the producer’s `SQLITE_HAS_CODEC` declaration flag. The corrected recipe explicitly uses that flag; it does not alter library source or controls.

Each fresh process loads both groups using **RTLD_NOW | RTLD_GLOBAL**, first quictls→modern and then modern→quictls. After both loads it checks exact runtime/header backend version identity, known NIST AES-128 block encryption/decryption through each real EVP implementation and repeated genuine quictls TLS1.3 ClientHello emission through `SSL_QUIC_METHOD` callbacks. The modern group executes the existing producer's real SQLCipher encrypted write/reopen/exact-value/wrong-key controls. The driver checks that crypto entrypoints are absent from the process global lookup namespace, records actual mapped paths and closes both handles.

The callback control tests the actual quictls ABI and emitted initial handshake data; it does not complete a QUIC handshake or exercise CommonCommo/ngtcp2. Full CommonCommo loading, TCP/TLS routing, complete QUIC transport, Kernel/JNI initialization, external provider modules, target ABI and live TAKX remain separate acceptance gates. No opaque OpenSSL objects cross the group boundary.

```sh
python3 -B takx/native-crypto/build.py \
  --output /private/new-crypto-output --cache /private/crypto-source-cache \
  --modern-proof /private/completed-native-sqlcipher-proof
```

Network is off by default; `--fetch-dependencies` permits only locked official archive/patch URLs. New downloads are 15.48 MB compressed and 54.64 MB expanded source, under the 32 MiB/512 MiB source bounds. Reused inputs are read-only and not charged as new source downloads. Output and this dedicated cache must be external, separate and new where required. One make job, a 1200-second total command budget, bounded private logs and a 2 GiB between-command output/cache check limit the experiment. This is not a filesystem quota. First failure stops and preserves diagnostics without a success receipt. Nothing installs into the host.

Offline checks:

```sh
python3 -B -m unittest discover -s takx/native-crypto -p test_build.py -v
```

For a completed fresh proof, set `TAKX_NATIVE_CRYPTO_PROOF` to its output and `TAKX_NATIVE_CRYPTO_MODERN` to its normative SQLCipher input proof. The same checks verify sources, producer, installed/output/tool/mapped-file inventories and actual symbol policy, then replay both load orders and encryption controls in fresh processes. This establishes only the documented two-group experiment, not SDK acceptance or security suitability of historical quictls.
