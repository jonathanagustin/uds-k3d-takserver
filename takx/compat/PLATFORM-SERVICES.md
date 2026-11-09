# Desktop storage and small platform contracts

`Environment.getExternalStorageDirectory()` returns a real desktop directory.
Set the absolute `TAK_EXTERNAL_STORAGE` property or environment variable to
choose it. Otherwise it uses `external` under `TAK_APP_DATA_PATH`, or
`~/.tak/desktop/external` when no app path is configured. The method creates
the directory and returns its canonical path; invalid paths and filesystem
failures are reported. This is app-owned desktop storage, without Android
shared-volume, mount-state or permission APIs.

`Patterns.IP_ADDRESS` retains the exact legacy IPv4 regex from pinned AOSP
Android 14. In particular, it excludes IPv6 and a zero first octet, and has
legacy leading-zero choices. It is not a general numeric-address validator.
The rest of Android's `Patterns` API is absent.

`SuppressLint` retains the actual AOSP annotation definition: class-file
retention, its six declaration targets, and a string-array value. It adds
metadata rather than changing program execution. The original Apache notices
remain; trailing source whitespace is normalized. Source URLs and hashes are in
[platform-source.lock.json](platform-source.lock.json).

Run `python3 takx/compat/test-platform-services.py` with JDK 17. The tests create
and read actual files, check configured/default paths and failures, exercise
legacy IPv4 boundaries, and inspect annotation metadata. These checks do not
run the complete Kernel filesystem/native-library dependency graph.
