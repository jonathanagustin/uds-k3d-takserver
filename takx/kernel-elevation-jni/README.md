# Public elevation JNI source corrections

Official Kernel 8.30.5 at `9f6893dd657feacc35ec5de03dad721c2e44170e`
looks up the QueryParameters constructor on the unrelated ElevationSource class.
Real attached-source bulk sampling aborts under `-Xcheck:jni` with `Wrong object
class or methodID passed to JNI call`. The patch obtains the constructor from its
declaring class and checks the actual source/query/chunk callback boundaries.

A pending callback error stops further ordinary JNI operations. Cursor, listener
and chunk cleanup saves the first Java error, clears it while attempting cleanup,
and restores it afterward. A later cleanup error cannot replace that first error.
The source lookup checks its wrapper callback before creating/interning a managed
source. Query allocation/boxing and metadata callbacks are checked before their
results are passed to subsequent JNI operations.

All three original source images, corrected images, patch bytes and both owned
control sources are locked. Default verification starts no process. Explicit
preparation copies the exact cached official sources into a fresh disjoint output,
applies the closed three-file patch without fuzz, and checks every postimage and
unchanged input. It builds and loads nothing and changes no cached source.

```sh
python3 -B takx/kernel-elevation-jni/prepare.py
python3 -B -m unittest discover -s takx/kernel-elevation-jni -p 'test_*.py' -v
python3 -B takx/kernel-elevation-jni/prepare.py --phase prepare \
  --source /path/to/cached/official/source --output /path/to/new/source-output
```

The original two fixtures use actual public elevation interfaces, the real native registry,
source builder, chunk sampler and bulk sampling. The positive fixture checks an
owned analytic plane's 81 values, attach/detach and absence after detach (166
checks). The fault fixture wraps the actual public interfaces to inject errors;
it does not shadow SDK classes. Thirteen cases cover source naming/query, cursor
iteration/get/close, chunk metadata/sampling/disposal, and secondary cleanup errors.
Each case verifies the primary exception identity and successful sampling recovery;
cases owning cursor/chunk state also require their cleanup to be attempted.
The fixtures take an independently authenticated native load-order manifest; they
are not loader/authentication front doors and are never launched by default CI.

The original complete composition aborts and emits two JNI warnings. Its failure
receipt is `1d90b0ae9ac1b83354ffe1cd36f5a0ea256af8cb8a32de1634a22aab892f3cbe`.
The constructor-only causal relink passes 166 functional checks but still fails
strict validation on seven warnings; receipt
`97c5c34d8508cdec446330a03078065f2ae163daa75ea9570d2e4cefe584cb6f`.
A separate three-source causal recompile/relink passes the same positive control
with zero strict JNI diagnostics (receipt
`37d0b1f1b05be12780dace18c6a347b7031172f064635da3f09e019c3e1d7206`)
and all 13 fault cases with zero strict JNI diagnostics (receipt
`955456d32c585e3b04d4b9381d9669c1aaa6f13d79365e59684690f3180cc81f`).
All prior failures, objects, original sources and consumed recipe snapshots remain
retained. The causal relinks are not adopted as fresh full native variants.

Four offline guards and real exact preparation pass. A new complete 815-unit
composition and actual-library replays now pass; see [QUALIFICATION.md](QUALIFICATION.md).
The public source preparer is still not a portable native builder. Other elevation entry points, successful mesh materialization,
concurrency and rendering remain outside the current 13-case qualification scope.
No full elevation API, SDK or client acceptance follows from these source fixes.
Refs #374 and #486.

The owned listener/bounds control consists of `tests/ElevationListenerProbe.java`
and `tests/ElevationListenerProbe.cpp`. It requires the actual complete Kernel
Java classes and native libraries plus the matching source headers; it is not a
standalone SDK implementation. Compile Java with `javac --release 17 -proc:none`
and the reviewed Java classpath. Compile the C++ probe as a shared library against
that build's `interop/elevation/ManagedElevationSource.h`, JNI headers,
`libtakenginejni` and `libtakengine` with `-Wl,-z,defs`. Run the Java main with
`-Xcheck:jni`, the reviewed runtime-native SHA-256 manifest, and the probe library
path as its two arguments. The source preparer verifies all six owned control
files but performs no compilation or native execution. Scoped results and
remaining gates are recorded in `QUALIFICATION.md`.

The direct chunk control uses `tests/ElevationChunkProbe.java` and
`tests/ElevationChunkProbe.cpp` with the same build/classpath requirements,
compiling against `ManagedElevationChunk.h`. Run `ElevationChunkProbe` with the
runtime-native manifest and its separately compiled probe library. It covers
actual primitive accessors and sampling, constructor metadata failures,
`createData` callback failure, pending-exception entry guards, destructor error
preservation and fresh-chunk recovery. It does not qualify successful mesh
materialization or concurrent chunk access.

### Opt-in frozen-build consumer

`python3 -B takx/kernel-elevation-jni/controls.py` verifies the owned source
profile without starting a process. To replay the listener and chunk probes,
explicitly supply the reviewed Native07 root, canonical Java producer root,
reviewed JDK root, and a fresh output directory:

```sh
python3 -B takx/kernel-elevation-jni/controls.py --phase run \
  --native /path/to/context-fresh-native-07 \
  --java /path/to/client-java-native07-01 \
  --jdk /path/to/reviewed-jdk \
  --output /path/to/fresh-consumer-output
```

This consumer requires the exact frozen producer receipts and their recorded
absolute dependency/JDK paths. It verifies staged native/Java sources, closed
class/header membership, classpath archives, the native load manifest, mapped
ELFs, compiler/JDK bytes, JNI headers and the owned control sources before any
compiler or JVM starts. Inputs and closed compiled products are rechecked between
commands. Each command has a 40-second deadline; failures retain logs and a typed
first-failure receipt. An existing, overlapping or symlink output refuses before
execution. Runtime acceptance requires the exact 112/231 check markers and zero
strict JNI diagnostics. The receipt fingerprints commands, inputs, products and
logs while keeping all broad acceptance flags false.

It does not build Native07, download dependencies, relocate the frozen layout,
or provide a hermetic compiler toolchain. System compiler headers remain part of
the qualified local host environment. A portable native producer remains an open
gate; a matching receipt digest alone does not grant SDK/client acceptance.
