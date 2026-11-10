// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.os;

/** Linux clock semantics for the two public Kernel timing APIs. */
public final class SystemClock {
    static {
        if (!"Linux".equals(System.getProperty("os.name"))) {
            throw new UnsupportedOperationException("Desktop SystemClock requires Linux");
        }
        System.loadLibrary("uds_desktop_clock");
    }

    private SystemClock() { }

    /** Milliseconds since boot, including time spent suspended (CLOCK_BOOTTIME). */
    public static long elapsedRealtime() { return clockMillis(true); }

    /** Milliseconds since boot, excluding suspend (CLOCK_MONOTONIC). */
    public static long uptimeMillis() { return clockMillis(false); }

    private static native long clockMillis(boolean includeSuspend);
}
