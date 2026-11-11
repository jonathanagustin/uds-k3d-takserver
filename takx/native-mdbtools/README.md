# Historical MDBTools source profile

This optional Linux amd64 profile builds genuine MDBTools 1.0.0 from the official ATAK source archive with its original portability patch. It fills the actual `mdb` native dependency used by Kernel's MS Access provider. It does not build that provider, full Kernel/JNI or TAKX.

The lock binds the immutable official archive, every patch pre/postimage (including added Windows files), GPL/LGPL license texts and compiler/tool versions. The recipe builds a static PIC `libmdb.a`, with the upstream fakeglib implementation selected by `--disable-glib` and genuine glibc iconv selected by configure. There are no fake SDK libraries, host MDBTools/GLib/libiconv substitutions or codec claims. SQL, manual pages and NLS are disabled. This profile does not establish security suitability, distribution obligations or target ABI acceptance for this historical library.

The release build uses supported `--disable-maintainer-mode` and the consumer
selects `_XOPEN_SOURCE=700` for the official header's POSIX types. Earlier
failed attempts remain preserved separately; none has a success receipt.

Run with reviewed GCC 14.2.0, GNU Make 4.4.1 and binutils 2.44:

```sh
python3 -B takx/native-mdbtools/build.py \
  --output /private/new-mdb-output --cache /private/source-cache \
  --with-upstream-fixture
```

Network is off by default. `--fetch-dependencies` explicitly permits only locked official-source and fixture URLs. Output must be new, outside the repository and separate from cache. One make job, a 600-second aggregate command deadline and a 4 GiB output/cache check bound the experiment. The size check runs between commands and is not a filesystem quota. Build logs remain private. Missing tools, sources, checksums or controls stop the run without `complete.json`.

`--with-upstream-fixture` explicitly opts into private use of the pinned upstream `mdbtools/mdbtestdata` Northwind MDB. That repository describes its files as Internet-sourced tests and provides no license grant. This repository does not vendor or redistribute the database; review rights separately before distributing test data. Its bytes are fetched only on request or supplied through the verified private cache. Controls read a real catalog and Customers table, verify 91 rows and ALFKI's contact Maria Anders, rewind the cursor, reject a missing table and missing file, and close the database. They are real MDBTools API controls, not fabricated database bytes or proof of the Kernel provider. The owned consumer also compiles and links the exact `mdb_ole_read_next` header signature, and the recipe verifies that function plus `mdb_set_boolean_fmt_numbers` are genuinely defined global symbols. No OLE runtime behavior is claimed. A whole-archive `--no-undefined` shared link and TEXTREL check establish PIC for the built library. Runtime inventories bind the genuine libc/libm loader closure.

Offline guards:

```sh
python3 -B -m unittest discover -s takx/native-mdbtools -p test_build.py -v
```

For a completed fresh run, set `TAKX_NATIVE_MDBTOOLS_PROOF` to its private output and `TAKX_NATIVE_MDBTOOLS_FIXTURE` to the pinned cached database when invoking the same checks. Receipt validation rechecks recipe, source inventory, installed files, output files, tools and runtime libraries, then replays the actual row controls. No success receipt is produced by an incomplete build. Kernel provider integration and complete Cesium/S2/Abseil closure remain subsequent milestones.
