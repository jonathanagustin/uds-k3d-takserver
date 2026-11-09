# Bounded desktop Parcel values

`Parcel` is an in-memory primitive codec for the source-backed Kernel use cases,
not Android Binder or a general IPC implementation. It supports int32, int64,
IEEE double bits, UTF-16 strings, byte arrays, byte positions and raw byte copies.
The buffer is limited to 16 MiB. Recycled instances are rejected rather than
pooled. Reads reject truncated/invalid lengths; positions cannot exceed the
written size. Malformed-input error types are desktop validation, not a claim
of exact Android native error recovery.

Format references are official AOSP Android 14:

- [frameworks/native `bfcf75076e562945bae131a4929f29a90d0d2481`, Parcel.cpp](https://android.googlesource.com/platform/frameworks/native/+/bfcf75076e562945bae131a4929f29a90d0d2481/libs/binder/Parcel.cpp): `writeAligned`, `writeString16`, `writeByteArray` and four-byte padding.
- [frameworks/base `299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368`, Parcelable.java](https://github.com/aosp-mirror/platform_frameworks_base/blob/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/core/java/android/os/Parcelable.java): retained Apache-2.0 source with unavailable annotations removed.
- `BaseBundle.java` and `Bundle.java` at that base revision: int getters default
  to zero or the caller fallback, typed mismatch returns fallback/null, and
  byte-array values retain their reference. Desktop Bundle implements only
  these in-memory int/byte-array methods. It has no parcel serialization.

Golden bytes test the little-endian Android targets used here: int/long/double,
UTF-16 code-unit length, surrogate pairs, terminal NUL, four-byte padding and
null sentinels. This does not promise a cross-version Android IPC wire protocol.
No Java serialization, Binder objects, file descriptors, native handles,
class-loader parcelables, Android permission checks or process transport exists.
Unsupported methods are absent, not successful no-ops.

Run the opt-in test using the five already locked public classpath JARs:

```sh
python3 takx/compat/test-port.py --source "$ATAK_SOURCE_DIR" \
  --classpath-dir /path/to/locked-jars --parcel-consumer
```

The runner checks the clean official source revision, compiles all 77 port and
six annotation files, then adds the unchanged engine `Icon.java`. Its real
builder writes two URI/color states and metrics through `writeToParcel`, and
its real `CREATOR` reads them back. Tests also exercise overwrite/positions,
truncation, recycled access, Bundle reference/type behavior and fixed wire bytes.
GeoPoint and CoordinatedTime use these primitives too, but their additional
engine dependencies have not been substituted or executed. Full engine/client
and Android IPC acceptance remain unproven.

The copied Parcelable interface also normalizes trailing comment whitespace.
