# CoT and TAK protocol conformance slice

This opt-in profile exercises the genuine public CommonCommo 1.17.2 Java/JNI codec
and its TCP streaming negotiation/parser. It builds only its small Java test
harness against an existing qualified JAR/native prefix. It does not build a
native library, fetch dependencies or contact a TAK server.

The pinned source is maintained official ATAK-CIV revision
`9f6893dd657feacc35ec5de03dad721c2e44170e`. The older archived
`deptofdefense/AndroidTacticalAssaultKit-CIV` is a different revision.
`provenance.json` binds every unchanged official snapshot to its source path and
SHA-256. The protobuf files come from the actual CommonCommo producer directory:
its contact schema includes `altendpoints`, unlike the duplicate top-level schema.

Run offline provenance guards (no compiler, JVM or native loading):

```sh
python3 takx/cot-conformance/check.py
PYTHONDONTWRITEBYTECODE=1 python3 takx/cot-conformance/test_check.py
```

Run the actual codec/loopback controls explicitly with an existing accepted prefix,
its complete receipt, JDK 17 and a fresh private output directory:

```sh
python3 takx/cot-conformance/check.py --run \
  --prefix /path/to/accepted/install --receipt /path/to/accepted/complete.json \
  --jdk /path/to/jdk17 --output /path/to/new-private-output
```

The runner requires the exact accepted JNI/JAR/producer receipt hashes, verifies
the consumed producer schema hashes, checks class origin and actual mapped ELF
providers, sanitizes Java/loader injection variables, and rehashes inputs after
execution. Trusted host C/C++ and JDK runtimes are recorded separately. Commands
have process-group cleanup, a 90-second total deadline, 30-second Java compilation
and 45-second runtime limits, 1 MiB per log, 8 MiB output cap and 2 GiB free-space
floor checked while each child runs. The runner preserves `HOME` and `CODEX_HOME`;
owned application/temp directories use Java properties and `TMPDIR`. Both Java
tools have 128 MiB heap/metaspace limits and one active processor; compilation
targets Java 17 with annotation processing disabled. Child processes have hard
1 MiB file-size, zero core-dump and 30/45-second CPU limits. A 128 KiB final-receipt
reserve is checked before commands. Existing source/native prefixes are not modified. Default CI should run
only the offline guards; the actual runtime requires explicitly supplied inputs.

Controls cover:

- Real JAXP validation with the unchanged MITRE base XSD, external DTD/schema
  access disabled: valid synthetic unknown extensions, missing UID, invalid
  numeric coordinates and invalid dates. The unchanged historical marker lacks
  the schema's newly required `access` attribute and is rejected; its genuine
  codec-normalized XML supplies `access=Undefined` and validates. The base's lax
  detail wildcard is exercised; individual detail schemas are not all validated.
  The retained `__chat` snapshot has unresolved local include dependencies and is
  provenance/reference material only, not a claimed validated chat schema.

- Genuine XML→TAK v1 broadcast-header→XML conversion, including `altendpoints`,
  Unicode, nested unknown details, extra attributes on a typed element and duplicate
  typed details using whole-element XML fallback.
- An unchanged official historical marker fixture, including duplicate details.
  It is codec input, not a fresh location report or live map event.
- Invalid XML, missing required fields, unsupported output versions, empty binary,
  wrong magic, unsupported binary version and truncated protobuf rejection.
- Actual client negotiation request, accepted v1 with fragmented/coalesced stream
  frames, and denied v1 with XML fallback. Peer transport framing follows the
  official specification; every binary event payload comes from the real codec.

This is not full CoT-detail XSD coverage, a schema compiler, exhaustive fuzzing, TLS/QUIC,
TAK Server interoperability, a running TAKX client or full SDK qualification.
The explicit null/native failures remain failures; Java exit zero alone is insufficient.

## Callback ordering limit

The first local control expected wire-order callbacks and failed: both messages
arrived intact but in reverse order. Diagnostic evidence confirms the public
`CoTMessageListener` contract does not promise FIFO. The upstream streaming queue
uses `push_back` and `back`/`pop_back`; coalesced arrivals can reverse callbacks.
The suite checks the exact two-message set and payloads and records observed order;
it does not qualify FIFO. A follow-up upstream review should consider whether
same-UID updates could regress state. That consequence has not been tested here.
No queue patch or native rebuild is included.

## Source and fixture licenses

Owned harness/runner/guards and synthetic input: GPL-3.0-only. Official snapshots
are unchanged and retain their notices. Upstream `LICENSE.md` contains GPLv3;
its README distinguishes US federal public-domain contributions from licensing
elsewhere. `THIRDPARTY.md` requires checking individual notices. The MITRE base XSD
has its own copyright and approved-public-release/distribution-unlimited notice;
do not describe the complete corpus as uniformly permissively licensed.
