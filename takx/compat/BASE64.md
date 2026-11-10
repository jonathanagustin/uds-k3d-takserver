# Android Base64 desktop source adapter

This adds the real `android.util.Base64` static API to
`uds-desktop-android-compat`, retaining Android's decoding and flag contracts.
It is not a renamed SDK artifact or a completed TAKX engine/client build.

The source is official AOSP Android 14 commit
[`299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368`](https://android.googlesource.com/platform/frameworks/base/+/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/core/java/android/util/Base64.java),
decoded source SHA256
`bd7b1e83953dda51fda1b96b5211cf43e375105db8f7f5a6dd678efb57fb3364`.
[base64-source.lock.json](base64-source.lock.json) records the source URL, revision
and hash. The original AOSP copyright/Apache-2.0 notice and existing complete
[license](LICENSE-Apache-2.0.txt) are retained. The adaptations remove the
Android-only `UnsupportedAppUsage` annotation/import and explicitly select UTF-8
for String decoding, matching Android's default charset independently of the
desktop locale. All remaining source bytes
match the pinned implementation; the test refuses deviations before compiling.

## Contracts and validation

`DEFAULT`, `NO_PADDING`, `NO_WRAP`, `CRLF` and `URL_SAFE` retain actual Android
behavior. Default encoding wraps at 76 characters and ends nonempty output with
a newline; `CRLF` chooses the newline sequence and `NO_WRAP` suppresses it.
`NO_PADDING` independently suppresses padding. The decoder permits missing
padding and skips non-alphabet bytes, not merely whitespace. Incorrect padding
or trailing data after padding still fail. Unused tail bits are not tightened.
The implementation deliberately does not substitute Java's basic or MIME decoder,
whose acceptance differs. `NO_CLOSE` remains the official constant, with no effect
on these non-stream APIs.

The offline test compiles the adapter and actual pinned source in an isolated
oracle package, with annotation removal only. The adapter runs under an
ISO-2022-JP default charset and the oracle under Android-equivalent UTF-8;
Unicode non-alphabet input must decode identically. Each runs 25,773 assertions
covering lengths 0–200 and all 32 combinations of the defined bits, randomized
binary round trips, independent Java encoder expectations with Android line
formatting, malformed input, padding, whitespace/non-alphabet skips, URL-safe
symbols, and offsets. Additional range/null/overflow outcomes and exception
classes are compared between both source variants, preserving surprising AOSP
behavior such as an empty result for certain negative-length/overflow cases.
No stricter range contract is silently invented.

With a JDK supporting `--release 11`, fetch and base64-decode the locked AOSP
`format=TEXT` response into an external cache, then run:

```sh
python3 takx/compat/test-base64.py --aosp-source /path/to/decoded/Base64.java
```

The test itself is offline, uses temporary compiler outputs, and rejects changed
upstream bytes. It does not execute native engine code or dispatch workflows.

## Actual public engine consumers and limits

Official public ATAK revision
[`9f6893dd657feacc35ec5de03dad721c2e44170e`](https://github.com/TAK-Product-Center/atak-civ/tree/9f6893dd657feacc35ec5de03dad721c2e44170e)
imports this class in five engine consumers:

- `GLBitmapLoader`
- `AtakAuthenticationDatabase`
- `AtakCertificateDatabaseBase`
- `AtakAuthenticationHandlerHTTP`
- `WebProtocolHandler`

They use static encoding/decoding; no Base64 input/output stream API or stream
ownership contract is required by those sources. `AtakAuthenticationDatabase`
uses `NO_WRAP`. `WebProtocolHandler` encodes its UTF-8 Basic credentials using
`DEFAULT`, which retains the trailing newline. This adapter preserves that
actual behavior; it does not silently repair or claim acceptance of the HTTP
consumer. That consumer also requires real certificate-manager and URI/IO
infrastructure; the others depend on graphics or certificate/database engine
infrastructure. No complete unchanged native-free consumer was proven in this
bounded slice. No dependency stubs or consumer exclusions are supplied.

The complete public Kernel port compile and its existing runtime checks can
include this adapter, but that is separate from engine networking, certificate
storage, native graphics and full TAKX acceptance. Both official TAKX 5.7 and
5.8 remain candidates, with 5.8 preferred only when actual evidence supports it.
