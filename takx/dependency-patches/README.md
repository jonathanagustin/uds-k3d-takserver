# Native dependency patch provenance

`curl-8.9.1-sigpipe-init.patch` is the one-line upstream curl correction from
[3eec5afbd0b6377eca893c392569b2faf094d970](https://github.com/curl/curl/commit/3eec5afbd0b6377eca893c392569b2faf094d970)
(2024-08-05), “sigpipe: init the struct so that first apply ignores.” It fixes
upstream issue 14344, a regression from 17e6f06ea37136c36d2712b3433ef0d3b118ec0d.
Upstream curl's [COPYING](https://github.com/curl/curl/blob/curl-8_9_1/COPYING)
contains its copyright and permission notice; this patch does not change that
license. It changes no public curl API or reported version.

The input remains the official ATAK-pinned curl 8.9.1 archive, followed by its
existing `curl-pgsc.patch` and this explicit project backport. `sources.lock.json`
binds the source archive, patch and exact changed header bytes. The native
recipe applies this separately from the CommonCommo source patches. It does not
modify the upstream checkout or reuse an incompatible completed-prefix key.

The real Linux/JNI signal regression and TLS coverage are described in
[TLS.md](../TLS.md). This specific correction does not establish a secure or
complete native dependency closure. In particular, all other old native library
versions and host-detected curl features still require review.

## Separate current-release assessment

At the 2026-11-10 review, the official latest release was
[curl 8.23.0](https://github.com/curl/curl/releases/tag/curl-8_23_0), published
2026-10-14 (source commit `3163ec065643ba20709f190111f42c3e1fe95273`).
Its `lib/sigpipe.h` retains this initialization. Its official
`docs/INSTALL.md` still documents the OpenSSL/quictls backend, an explicit
OpenSSL prefix and static builds. That makes a current-source candidate
plausible; it does not prove a drop-in replacement for this profile.

Adoption needs a separate archive lock, review of the older TAK changes to the
generated configure script, feature/protocol and host-library closure comparison,
a real native rebuild and CommonCommo HTTP/enrollment/mission-package tests in
addition to the streaming tests. None of those broader runtime contracts follows
from this backport or the Java/JNI streaming evidence. No newer curl artifact is
silently substituted here.
