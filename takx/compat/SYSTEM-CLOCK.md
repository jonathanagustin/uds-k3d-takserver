# Linux SystemClock runtime slice

This adds only the two `android.os.SystemClock` methods consumed by the reviewed
public Kernel: `elapsedRealtime()` and `uptimeMillis()`. It is original
GPL-3.0-only Java/JNI C source, explicitly requiring a separately source-built
Linux native library. It is not a Java-only timing alias, an Android SDK
replacement or complete engine/client runtime acceptance.

## Clock and origin semantics

- `elapsedRealtime()` reads Linux `CLOCK_BOOTTIME`: milliseconds since kernel
  boot, including suspend.
- `uptimeMillis()` reads Linux `CLOCK_MONOTONIC`: milliseconds since kernel boot,
  excluding suspend.

Both convert the kernel timespec to integer milliseconds without substituting a
JVM/class initialization epoch or wall clock. Neither calls `System.nanoTime()`.
Clock errors throw `IllegalStateException`; invalid/overflowing timespec values
throw `ArithmeticException`. Missing native library or unsupported OS fails
explicitly; no fallback clock, zero value or no-op implementation is returned.
A pending JNI exception is the only reason the C error helper contains a return
value of zero; Java callers receive the exception instead of that value.

The semantic references are official AOSP Android14:

- [SystemClock.java](https://android.googlesource.com/platform/frameworks/base/+/299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368/core/java/android/os/SystemClock.java)
  documents boot origins and the suspend distinction. Source SHA256:
  `bfaabc5904901bd312bf59b62a76f5da8aaa2783b7a1494c544048999b748cca`.
- [system/core SystemClock.cpp](https://android.googlesource.com/platform/system/core/+/refs/tags/android-14.0.0_r1/libutils/SystemClock.cpp)
  maps uptime to `SYSTEM_TIME_MONOTONIC` and elapsed time to `CLOCK_BOOTTIME`.
  Source SHA256:
  `a77da175eceed494dbc434e7f34dfd80fde9f8fd01ab173267828f35d64202d2`.
- [Timers.cpp](https://android.googlesource.com/platform/system/core/+/refs/tags/android-14.0.0_r1/libutils/Timers.cpp)
  maps `SYSTEM_TIME_MONOTONIC` to `CLOCK_MONOTONIC`. Source SHA256:
  `b2c4bb4d2e9f90fe4af65df28ba0e6ea12c502a20ef660b2d6fbea55c98d217a`.
- [Linux clock_gettime documentation](https://man7.org/linux/man-pages/man2/clock_gettime.2.html)
  specifies the same two kernel clocks; `CLOCK_BOOTTIME` requires Linux2.6.39+.

No AOSP implementation is copied into this original helper. Unlike AOSP's
historical error-to-zero path, this desktop implementation intentionally fails
closed on clock errors.

## Build and runtime requirement

Use a Linux JDK with JNI development headers and a C compiler/linker supporting
the flags used by the helper. The local proof used Temurin17 and GCC14 on
x86_64 Linux, compiling Java for release11:

```sh
python3 takx/compat/build-system-clock.py \
  --java-home /path/to/jdk17 --output /path/to/native-output
java -Djava.library.path=/path/to/native-output ...
```

`JAVA_HOME` or the installed `javac` can supply the JDK when `--java-home` is
omitted. `--cc`/`CC` selects a compiler executable. The build has no network fetch,
uses temporary intermediate files, and writes only `libuds_desktop_clock.so`
into the explicitly selected output directory. Build the library for the actual
runtime architecture and supply it alongside the compatibility Java classes.
Java compilation alone does not provide this runtime dependency. No normal
server deployment or default workflow builds/loads it.

## Bounded tests and limits

```sh
python3 takx/compat/test-system-clock.py --java-home /path/to/jdk17
```

The test source-builds the actual runtime library and an independent reference
JNI library, then brackets 100 reads of each public Java method with native
reads of the corresponding kernel clock. Sleep progression, ordering and boot
origin are checked (203 real-kernel assertions). Separate, explicitly named
link-time fixtures supply distinct clock values and test clock selection,
truncation to milliseconds, errors and overflow. Those fixtures are not included
in the runtime library and do not count as real suspend tests. Missing-library
and unsupported-OS cases verify explicit failures. Every compilation/JVM command
has a deadline; all artifacts are temporary.

No host suspend, clock setting, privileged operation, native GIS/graphics build
or engine runtime probe is performed. The kernel API semantics establish the
suspend distinction; no actual suspend/resume experiment is claimed. Other
SystemClock APIs (sleep, nanosecond APIs, thread time or setting wall time) are
absent because the reviewed Kernel consumers do not call them. Real consumers
include OAuthAccessToken, GLDiagnostics and tile/GDAL timing paths; this slice
supplies their clock primitives without claiming those complete consumer graphs
or full TAKX have been compiled and run. Both official client profiles remain
under investigation.
