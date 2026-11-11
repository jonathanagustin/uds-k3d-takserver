# Public SQLCipher source profile

Build SQLCipher 4.5.7 with its own source-built Tcl 8.6.18 generator and OpenSSL 3.5.9 LTS provider. The opt-in Linux amd64 profile produces static PIC libraries and tests encrypted database creation, correct-key reopen, exact data, wrong-key rejection, and whole-archive shared linking.

This proves one native dependency component. Historical SQLCipher/SQLite security review, target-image ABI, Spatialite/Kernel integration, TTP QUIC compatibility, full SDK, and TAKX validation remain open. There is no FIPS claim.

## Run locally

Use GCC 14.2.0, GNU Make 4.4.1, Perl 5.40.1, Binutils 2.44, and standard Linux development tools. Put each verified official archive in an external cache named by its SHA256 from [inputs.lock.json](inputs.lock.json). This profile has no download option or network requests.

```sh
python3 takx/native-sqlcipher/build.py \
  --cache /absolute/external/source-cache \
  --output /absolute/external/new-sqlcipher-proof --jobs 2
```

The output must not exist. Source/cache/build paths stay outside the repository. The recipe rejects modified archives, foreign headers, existing outputs, and overlapping paths. It preserves release timestamps for Tcl's own bootstrap and compiles Tcl's bundled zlib 1.3.2. Compiler, Perl, Tcl, OpenSSL, and Make overrides are removed from child environments; proxy and CA configuration are preserved.

Each stage has a 20-minute limit, with 45 minutes total, at most two compile jobs, bounded logs/process groups, and a 12 GiB source/cache/output budget checked between commands. Build failures retain private logs and `failed.json`; only a complete run writes `complete.json`. The receipt binds source, recipe, tool, selected license notice, installed product, runtime, and probe hashes. Builds use unchanged sources out of tree. SQLCipher uses a Linux-only upstream recipe; the TTP Cygwin path patch is not applied.

## Verify

```sh
python3 -B -m unittest discover -s takx/native-sqlcipher -p test_build.py -v
TAKX_SQLCIPHER_PROOF=/absolute/external/new-sqlcipher-proof \
  python3 -B -m unittest discover -s takx/native-sqlcipher -p test_build.py -v
```

Default Unit checks run only offline refusal tests. The real test skips unless explicitly enabled; it verifies receipt bindings before executing the source-built controls on a fresh database.

OpenSSL's official release checksum is verified. Tcl's checksum was computed from its official-page-designated distribution, whose Fossil identity and shared official mirror files were checked; an independent publisher SHA256 was not located. Selected notices supplement the complete verified source archives. The current OpenSSL provider does not establish security acceptance for historical SQLCipher 4.5.7 / SQLite 3.45.3.
