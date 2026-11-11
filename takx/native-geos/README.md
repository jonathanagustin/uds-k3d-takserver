# Historical GEOS source profile

This optional Linux amd64 component experiment builds official GEOS 3.4.3 with its original ATAK portability patch. It does not build the Kernel SDK or TAKX client.

The lock pins the official archive, LGPL 2.1 license text, three patch pre/postimages and tool versions. The recipe uses checked-in configure, static PIC libraries and C++11, with no host GEOS fallback. It checks real C geometry intersection, distance, buffer validity/area and malformed-input error handling, plus a whole-archive PIC link. This does not establish security suitability for this historical release, distribution obligations, C++/target ABI or full upstream test-suite acceptance.

Run only with the reviewed tools and verified cache (network remains off by default):

```sh
python3 takx/native-geos/build.py --output /private/new-geos-output --cache /private/source-cache
```

`--fetch-dependencies` explicitly allows only the locked official archive and patch downloads. Output must be new and outside the repository. One make job and a 600-second total command budget bound the experiment; failures stop and retain bounded local diagnostics, without a success receipt. Keep output private. No automatic source compatibility edits or retries occur. The output/cache size check is a between-command check, not a filesystem quota.

Cheap offline checks:

```sh
python3 -B -m unittest discover -s takx/native-geos -p test_build.py -v
```

An actual completed proof can be checked with `TAKX_NATIVE_GEOS_PROOF=/private/new-geos-output` using the same command. The receipt binds recipe/helper bytes, exact patched source inventory, installed files, tools, output artifacts and runtime closure. Full SDK, Spatialite, renderer, JNI, other target architectures and live TAKX remain separate gates.

The first local attempt built and installed both real libraries, then stopped at a
probe assertion that incorrectly omitted the official runtime SVN suffix. The
corrected probe requires exactly `3.4.3-CAPI-1.8.3 r4285`, as defined by the locked
source. The original stopped evidence is retained separately; any successful
receipt must come from a new complete entrypoint run, not continued old outputs.
That fresh corrected run passed, including independent source/output verification
and replay of the geometry controls.
