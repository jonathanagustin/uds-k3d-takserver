# Real GLES dispatch on local Mesa

This optional Linux amd64 experiment builds genuine libglvnd 1.7.0 EGL, GLESv2/v3 and GLdispatch libraries from NVIDIA's official source. It uses existing hash-pinned Khronos headers for its consumer and the local Debian Mesa software driver for actual rendering. It does not use the Kernel's GLES-stub library or provide replacement rendering symbols.

The real control creates a surfaceless EGL pbuffer and ES 3 context, requires Mesa llvmpipe, clears its framebuffer, reads an actual RGBA pixel and checks the result. It records every observed loaded ELF provider and its hash, plus Debian package ownership/version for host libraries. Mesa, LLVM and other host dependencies are **not** source-built by this profile; this is local execution evidence, not a self-contained graphics SDK, hardware acceleration, conformance, renderer/client integration, security or target ABI acceptance.

The source archive, official tag commit, 125 source license notices, pure-Python Meson wheel and 11 public headers are pinned. No vendor source algorithm is patched. The one official in-tree uthash directory symlink is recorded and its six archive-owned headers are deterministically materialized; other links are rejected. The original extractor failure and missing Meson module-path failure remain separate evidence. The corrected owned environment passes the same verified Python package to Ninja's generator subprocesses.

```sh
python3 -B takx/native-gles/build.py --output /private/new-gles-output --cache /private/source-cache --headers /verified/native-deps/install/include --ninja /verified/ninja
```

Source download is off by default; `--fetch-dependencies` permits the exact locked official archive and Meson package. Existing Ninja and GCC 14.2 are build tools, not newly downloaded binaries. The local Mesa vendor JSON, software DRI target and mapped libraries must exist and remain unchanged. This profile currently expects Debian amd64 paths/package metadata and refuses unreviewed providers.

Bounds: 64 MiB downloads, 512 MiB expanded inputs, one job, 10-minute command deadline, 1 GiB output. Actual locked downloads total 1.83 MB and expanded inputs about 10.5 MB. The output check runs between commands, not as a filesystem quota. There are no host package installs or changes. Logs and runtime receipts stay in the owned private output directory. Preserved source notices are evidence of licenses, not distribution/legal acceptance.

Offline guards: `python3 -B -m unittest discover -s takx/native-gles -p test_build.py -v`. Set `TAKX_NATIVE_GLES_PROOF=/private/completed-output` to also validate the receipt and replay the real context/readback. No default test builds or runs graphics code.
