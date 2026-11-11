# Public CommonCommo native/JNI experiment

This opt-in Linux amd64 profile builds the complete public CommonCommo 1.17.2 core,
JNI library and Java JAR from official ATAK commit 9f6893. It retains the real
ngtcp2/quictls QUIC implementation. It does not install TAKX or establish a full
SDK, target ABI, TAK Server interoperability or historical dependency security.

The profile reuses verified source-built zlib 1.3.1, libiconv 1.15, libxml 2.13.3 and
quictls 3.0.14 proofs. It builds the five locked remaining dependencies, including
a real same-version host protoc and target protobuf-lite. Input receipts are
checked against owned producer recipes, source and installed inventories, not
machine-specific golden receipt hashes. These are unsigned local cache-integrity
checks, not publisher authentication.

Provide new external output/cache paths, the pinned official ATAK Git repository,
existing accepted proof roots, JDK 17 and an owned genuine Debian Ant/dos2unix
prefix. The tool metadata directory must contain the exact signed InRelease,
Packages.xz and two locked package files. No package manager or source acquisition
runs unless explicitly requested; dependencies can be placed in cache by SHA256.
The host Debian archive keyring is an explicit trust prerequisite.

```sh
python3 takx/native-commoncommo/build.py \
  --source /path/to/official-atak-git \
  --output /new/owned/output --cache /owned/source-cache \
  --spatial-proof /proof/kernel-spatial-db \
  --zlib-proof /proof/assimp --quictls-proof /proof/crypto-isolation \
  --tools-root /owned/debian-tools --tool-metadata /owned/signed-metadata \
  --java-home /verified/jdk17
```

The command uses one compiler job, a 30-minute total command deadline,2 GiB output
bound and bounded private logs. It preserves the first stopped output and never
marks an incomplete build successful. Source archives total 13,164,232 bytes;
Debian tool packages total 2,680,504 bytes. The separate signed compressed index is
9,678,380 bytes, from the recorded September 2026 trixie snapshot; these pins do not
claim current security updates. No root installation or fake tool aliases.

Acceptance requires strict undefined-symbol checks, no shared crypto fallback,
hiding the complete actual crypto archive symbol union, and genuine constructor,
signal, loopback routing and mutual TLS/endpoint-identity controls under
`-Xcheck:jni`. QUIC source compilation is separate from a completed peer handshake.
The original CommonCommo patches preserve stream identity/SNI checks; the curl
patch preserves the caller's SIGPIPE state. No full SDK or client acceptance is
inferred from these controls.

Offline guards:

```sh
python3 -m unittest discover -s takx/native-commoncommo -p test_build.py
```

The first frozen run stopped at extractor-induced autotools timestamp ordering;
the next compiled the real core/JNI/JAR, then stopped at a C-only runtime check
that rejected the expected system C++ runtime. Both outputs remain incomplete.
The corrected runner retains original release timestamps, checks aggregate disk
use while children run, and routes certificate fixtures through the same deadline
and log bounds. System C/C++ runtime paths and all host compiler/JDK bytes are
recorded; shared crypto or other native providers remain forbidden.

The full native attempt built all products and passed functional controls, but
strict JNI checks rejected unchecked enum and logger exceptions. A later JNI-only
build applied the owned patch below and passed constructor, signal, routing,
mutual TLS/endpoint identity and throwing-logger controls with zero JNI warnings.
Dependencies, Core, the JAR and generated headers were reused after complete
integrity checks; only JNI was rebuilt. This is a scoped local result, not a new
full-source build or a qualified SDK cache.

## Owned JNI exception variant

The two-file patch keeps CommonCommo 1.17.2 and its public Java/native signatures.
Enum callbacks now check exceptions before the next JNI operation and preserve
load failures. JNI loading stops on pending failures. The best-effort logger
checks and clears only exceptions raised by that callback; an already-pending
caller exception is preserved. Other callback exception paths remain unproven.
A real always-throwing logger control requires usable constructors, native PKCS12,
callsign updates and repeated shutdown under `-Xcheck:jni`.

For this local investigation, `stage.py` can audit the exact stopped c992 producer
without adopting its failed JNI acceptance. It verifies the complete old tree,
source/configuration, real static archives, original JAR/JDK-generated headers,
accepted providers and tools. Pass the reviewed report SHA256 explicitly to
`resume.py` together with `--stage`, `--stage-audit`, `--output`, the three proof
roots and the same tool/JDK inputs. The original prefix remains unchanged. This
is an unsigned local checkpoint, not an authenticated OCI cache or a new full
source build. The JNI-only entrypoint records dependencies/core as reused and JNI
as fresh, with original producer and new patch/recipe lineage. It has a ten-minute
command deadline and retains every strict runtime and identity test.
