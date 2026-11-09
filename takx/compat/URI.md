# Android URI parsing on the desktop

The parser, builder and codec come from Apache-2.0 AOSP frameworks/base
[`299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368`](https://github.com/aosp-mirror/platform_frameworks_base/tree/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/core/java/android/net)
(`android-14.0.0_r1`). Original copyright/license notices remain in both sources.
This preserves Android's forgiving parsing and percent-encoding behavior;
`java.net.URI` is not used as a substitute.

Two upstream comment spelling errors are corrected. Desktop changes remove annotations, Android logging, the Parcelable interface,
parcel serialization/deserialization methods and creator, and Android-only
`getCanonicalUri`, `checkFileUriExposed` and
`checkContentUriWithoutPermission`. Those APIs are absent, not no-op adapters.
`UriCodec` has no executable changes. No ContentResolver, Android storage
policy, permission checks or parcel implementation is supplied.

Run `./takx/compat/test-uri.sh` with JDK 17 (Java 11 target). Forty unchanged
AOSP `UriTest.java` test bodies run in a standalone assertion harness, covering
opaque/hierarchical parsing, file paths, encoded paths, builder copying,
percent encoding/decoding, repeated/empty/escaped query keys, plus handling,
identity and hash semantics. Android IPC tests and tests requiring unrelated
ContentUris APIs are excluded explicitly. This is parser acceptance, not
Android IPC or full-client acceptance.

Original source SHA-256 values:

| Source at the pinned revision | SHA-256 |
| --- | --- |
| `core/java/android/net/Uri.java` | `f4bc8f778649066ddf8e318437c600f1e3579791457e86121e7aafcd9acf590c` |
| `core/java/android/net/UriCodec.java` | `19ed9a4c5fc0c1ab322cc91c09e80c8b99e1637b00ae0a2b648afd76d2c50f78` |
| `core/tests/coretests/src/android/net/UriTest.java` | `a45900b55b19aca963cb8c38c67ec6a95b47b65279504e03878d915ff063735f` |

Public Kernel `9f6893dd657feacc35ec5de03dad721c2e44170e` uses parsing,
file URI construction and decoded path/query/host access in
`com/atakmap/android/maps/graphics/GLBitmapLoader.java` and resource references.
Both pinned TAKX profiles still have incomplete engine/client dependencies.
No unchanged engine/client consumer compilation or rendering is claimed here.
