# Real desktop XML pull parsing

`android.util.Xml.newPullParser()` returns a real upstream kXML2 2.3.0 parser,
with namespace processing enabled. `FEATURE_RELAXED` is the same mutable public
field and feature URI used by Android. The bridge exposes only these used APIs;
it does not fabricate Android serializers or binary XML support.

This is deliberately scoped differently from Android 14's
[factory](https://github.com/aosp-mirror/platform_frameworks_base/blob/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/core/java/android/util/Xml.java):
Android's fork enables processing document declarations by default. Upstream
kXML2 does not implement that feature. It reports false and throws for either
true or false requests instead of pretending to apply a setting. It skips
DTDs and does not automatically expand their internal or external entities.
A strict parse rejects unresolved entities; relaxed mode can drop their text.
Relaxed malformed-attribute parsing can emit `ERR: ...` text. Callers must not
interpret tolerant parsing as validation or assume Android-fork error recovery.
This bridge does not silently override the upstream behavior.

The actual unchanged public Kernel `XMLUtils.getXmlPullParser()` requests no
DTD processing, no namespace processing and relaxed mode. Its source catches
unsupported feature requests. Tests compile that real file at
`9f6893dd657feacc35ec5de03dad721c2e44170e` and exercise those resulting settings.

```sh
python3 takx/compat/test-xml.py --source "$ATAK_SOURCE_DIR" \
  --kxml-jar /path/to/kxml2-2.3.0.jar
```

The runner checks the already verified JAR SHA-256
`f264dd9f79a1fde10ce5ecc53221eff24be4c9331c830b7d52f2f08a7b633de2`
and reads the consumer from the exact official Git revision. It downloads
nothing. Real namespace/attribute/text parsing, predefined entities, strict and
relaxed modes, unsupported DTD feature requests, internal entities and external
file/HTTP entity non-expansion are tested. An HTTP handler fails the test if
external resolution is attempted; a temporary file contains a marker that must
never appear in the parsed text.

Skipping DTDs is not a general parser resource limit or comprehensive XML
security assessment. Application-defined entity replacements remain upstream
parser functionality. Full engine/client acceptance is separate. The complete
public-port classpath must include the verified kXML2 dependency before building
all compatibility sources; this isolated change does not update that lock.
