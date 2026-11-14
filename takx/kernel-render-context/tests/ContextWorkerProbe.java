// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package com.atakmap.map.opengl;

/** Test-only JNI diagnostics, never a production provider or API alias. */
final class ContextWorkerProbe {
    static native void hold(long actualContextPointer);
    static native void queuePending(long actualContextPointer);
    static native void requireRetired(long actualContextPointer);
    static native long[] terminalCounts();
}
