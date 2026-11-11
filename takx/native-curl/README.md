# Current Curl provider for the Core crypto group

This opt-in Linux source profile builds genuine Curl **8.23.0**, the official
stable release published 2026-10-14. Its complete static libcurl archive is built
with PIC by upstream CMake. The pinned release asset SHA256 and complete source
inventory are verified before compilation and again afterward. No Curl source
patch, extracted implementation, substitute API or automatic dependency fetch
is used.

The crypto provider is actual OpenSSL **3.5.9** from the verified SQLCipher
producer, with actual zlib **1.3.1** from the verified Assimp producer. Their
recipes, sources, tools, installed products and positive controls are checked;
this profile does not import CommonCommo's quictls group. Compiler drivers,
backend, binutils, CMake and Ninja identities are recorded and checked again.

```sh
python3 takx/native-curl/build.py \
  --output /new/owned/output --archive /verified/curl-8.23.0.tar.xz \
  --openssl-proof /verified/sqlcipher-producer \
  --zlib-proof /verified/assimp-producer
```

There is no download or host package installation in the entrypoint. Bounds are
8 MiB compressed source, 64 MiB expanded source, 512 MiB output, one compilation
job and a ten-minute deadline. The owned process group is killed on timeout or
log/disk quota failure; disk checks remain active after output-stream EOF.
Earlier output directories and first failures are preserved.

HTTP and HTTPS remain enabled with the genuine OpenSSL and threaded resolver
backends. Unavailable optional providers are explicitly disabled: HTTP/2,
HTTP/3, libpsl, IDN, SSH, Brotli, Zstd, LDAP, GSSAPI, GSASL, libuv and libbacktrace.
Other upstream built-in protocol defaults remain compiled; they are not all
runtime-qualified. Automatic OpenSSL configuration and host default CA bundle
and path discovery are disabled. Any later network consumer must configure its
trust material explicitly; this profile makes no network-transfer or TLS-peer
acceptance claim.

Acceptance whole-archive links real Curl, SSL, crypto and zlib into a strict PIC
shared object. The complete actual SSL/crypto archive symbol union must remain
absent from its dynamic symbol table. Its exact loaded provider plus standard
system runtime is observed. Controls check the actual Curl/OpenSSL/zlib versions,
feature bits, HTTP/HTTPS presence, percent encoding of special and UTF-8 bytes,
embedded NUL with explicit length, empty input, repeated allocation/free and a
real easy handle. This exercises the real legacy `curl_escape` and `curl_free`
APIs used by Core without replacing their implementation.

The installed upstream CMake package exports `CURL::libcurl_static` and its
upstream `CURL::libcurl` alias, real headers and transitive OpenSSL, zlib and
thread targets. Parent CMake must bind the verified modern OpenSSL/zlib roots
before loading this package; it must not allow dependency discovery to select
another crypto group. A final shared Core link must preserve the crypto archive
hiding policy (for example `--exclude-libs,libssl.a:libcrypto.a`). Full Kernel,
JNI, SDK assembly and client acceptance remain separate integration gates.

Receipts bind source, headers, tool and provider identities, configuration,
objects, installed outputs and controls. They are local integrity evidence, not
publisher authentication against a hostile metadata author.

Offline guards: `python3 -m unittest discover -s takx/native-curl -p 'test_*.py'`.
