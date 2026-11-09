# Android Pair on the desktop

`android.util.Pair` retains the AOSP implementation from
[frameworks/base 299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368](https://github.com/aosp-mirror/platform_frameworks_base/blob/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/core/java/android/util/Pair.java)
(`android-14.0.0_r1`). Only the unavailable `Nullable` annotation was removed.
The original Apache 2.0 notice remains in the source; the license is in
[LICENSE-Apache-2.0.txt](LICENSE-Apache-2.0.txt).

Run `./takx/compat/test-pair.sh` with JDK 17. It compiles with Java 11
compatibility and checks typed creation, reference preservation, nullable ordered
equality, XOR hash behavior, map-key lookup, subclass equality, public final
fields and exact string formatting against the pinned AOSP contract.

Both official TAKX source profiles use this API in
`Client/src/main/java/gov/takx/core/globe/tak/features/CompositeFeatureProvider.java`:
5.7 at `0b59a9bb2d0e90dc35c9edfff1c2056daab2b713` and 5.8 at
`af54a3e1fe8796b6e109e2e5925dbef524ea7e31`. The public Kernel at
`9f6893dd657feacc35ec5de03dad721c2e44170e` uses it in
`com/atakmap/opengl/GLTriangulate.java`. Their dependent engine/client types
remain incomplete. These consumers have not been compiled or executed by this
standalone test. No substitute dependencies, native renderer, or full client
acceptance is implied.
