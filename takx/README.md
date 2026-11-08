# Experimental TAKX foundation

This opt-in component builds **public CommonCommo 1.17.2**, including its Java JAR and Linux amd64 JNI implementation. It does not build TAKX, create a desktop container, provide a replacement SDK, or complete [issue 376](https://github.com/jonathanagustin/uds-takserver/issues/376).

The existing `upstream/atak-civ` gitlink supplies the official source. [sources.lock.json](sources.lock.json) pins its revision, the actual CommonCommo version and nine source archives by SHA256, size and official public URL. TAKX source revisions in that file are research references, not additional checkouts or build inputs. No TAK.gov account or private artifact is used by this foundation.

## Run locally

Use Linux amd64, JDK 17 (`JAVA_HOME`), Python 3, Git, GNU make, GCC/G++, Perl, Ant, dos2unix, patch, tar, pkg-config, coreutils and the usual C/C++ build headers. The source archive configure scripts are already generated. These are optional local prerequisites; no default task or GitHub workflow installs or runs this component.

```bash
GIT_LFS_SKIP_SMUDGE=1 git submodule update --init upstream/atak-civ
export JAVA_HOME=/path/to/jdk-17
./takx/build-commoncommo.sh
```

The script retrieves only the nine locked source archives through official public raw/media URLs, validating bytes before materializing them. It rejects a wrong source revision, changed tracked build/code inputs, an unexpected CommonCommo version, or corrupt archives/cache entries. `TAKX_OFFLINE=true` forbids downloads; already verified source archives must be present or cached.

Caller-controlled paths and resource limits:

| Variable | Default / meaning |
|---|---|
| `ATAK_SOURCE_DIR` | Existing initialized `upstream/atak-civ`; an alternate official checkout must match the lock |
| `TAKX_BUILD_DIR` | `takx/.build/commoncommo`, isolated install/build prefix |
| `TAKX_CACHE_DIR` | `takx/.cache/sources`, SHA256-addressed public source archives |
| `TAKX_JOBS` | `2`; only `1` or `2` accepted; dependency installs stay serial |
| `TAKX_OFFLINE` | `false`; `true` disables archive downloads |

Use `--verify-only` to check/materialize source inputs without compiling. Use `--smoke-only` to exercise an already built JAR/JNI pair without compiling native code or marking it as a completed build cache. A successful normal build records local artifact hashes and the recipe/toolchain identity in `build-state.json`; subsequent unchanged invocations verify that state, skip native compilation, and still run the real smoke.

Source/output paths must not contain whitespace because the upstream Makefiles do not quote every path. Output/cache are ignored. A build may take several minutes and uses an isolated prefix; it does not replace system OpenSSL or other libraries. The local cache is an optimization, not an official artifact signature or a reproducible-build attestation. Remove `build-state.json` to force the recipe to run again.

## What is built and tested

The pinned native inputs are zlib, libiconv, libxml2, quictls/OpenSSL, nghttp2, curl, ngtcp2, protobuf and libmicrohttpd. Dependency installs are ordered because upstream's parallel multi-output OpenSSL install can race. The exact host protoc is built once; only the actual same-version PIC protobuf-lite library and headers are built for the target. CommonCommo's real static core is linked into its JNI shared library, and upstream Ant produces the auto-initializing Java JAR. No source patch is required for this foundation.

The smoke constructs a real native Commo instance, generates an ephemeral PKCS12, parses it with Java KeyStore and shuts down. It configures no network interfaces and saves no certificate/private key. It proves local Java/JNI/crypto initialization, not TAK Server connectivity, CoT delivery, enrollment, map rendering or full TAKX compatibility.

The successful native investigation used the isolated quictls `libssl.so.81.3` / `libcrypto.so.81.3`. Curl also detected host libraries for IDN2, RTMP, PSL, Zstandard and Brotli; the JNI runtime additionally needs the usual C/C++ runtime and loader. This recipe is **not yet a hermetic runtime package**: a future container must capture/audit that closure or deliberately configure dependency features and retest. The cache fingerprint does not pin every host library.

## Compatibility boundary

Current TAKX requires CommonCommo 1.22.3. Public 1.17.2 supports the inspected enrollment, streaming transport and mission-package call shapes, but lacks `configKnownEndpointForContact(uid, callsign, streamId)`. Its older fixed-UDP endpoint API has different routing and discovery semantics and is not a safe alias. A real backport or an explicit, tested capability restriction is required before a client port can claim compatibility. Full TAKX also needs the Kernel, patched WorldWind and other dependencies.

Keep upstream changes as reviewable diffs under [patches](patches/README.md). Do not relabel this library as 1.22.3, fabricate SDK classes or silently suppress unsupported functionality.

## Check the foundation

```bash
python3 -B -m unittest discover -s takx -p 'test_source_inputs.py' -v
bash -n takx/build-commoncommo.sh
```

Source/hash guard tests are local and do not fetch archives or compile native dependencies. They complement the actual JAR/JNI smoke, which requires the real source-built outputs.
