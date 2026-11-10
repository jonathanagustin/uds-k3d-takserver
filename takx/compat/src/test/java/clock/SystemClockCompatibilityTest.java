// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package clock;

import android.os.SystemClock;

public final class SystemClockCompatibilityTest {
    private static int checks;
    private static void check(boolean value) {
        checks++;
        if (!value) throw new AssertionError("clock check " + checks);
    }
    private static native long reference(int identifier);
    private static void failure(Class<? extends Throwable> type, Runnable call) {
        try { call.run(); } catch (Throwable error) {
            while (error.getCause() != null) error = error.getCause();
            check(type.isInstance(error)); return;
        }
        throw new AssertionError("clock failure was silently replaced with a value");
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "real":
                System.loadLibrary("uds_clock_reference");
                for (int i = 0; i < 100; i++) {
                    long before = reference(7); // Linux CLOCK_BOOTTIME ABI.
                    long elapsed = SystemClock.elapsedRealtime();
                    long after = reference(7);
                    check(before <= elapsed && elapsed <= after);
                    before = reference(1); // Linux CLOCK_MONOTONIC ABI.
                    long uptime = SystemClock.uptimeMillis();
                    after = reference(1);
                    check(before <= uptime && uptime <= after);
                }
                long before = SystemClock.uptimeMillis();
                Thread.sleep(30);
                check(SystemClock.uptimeMillis() >= before + 20);
                long uptimeFirst = SystemClock.uptimeMillis();
                check(SystemClock.elapsedRealtime() >= uptimeFirst);
                check(SystemClock.uptimeMillis() > 1000); // Host boot origin, not class/JVM startup.
                break;
            case "routing":
                check(SystemClock.elapsedRealtime() == 123456987L);
                check(SystemClock.uptimeMillis() == 234567987L);
                break;
            case "error":
                failure(IllegalStateException.class, SystemClock::elapsedRealtime);
                failure(IllegalStateException.class, SystemClock::uptimeMillis);
                break;
            case "overflow":
                failure(ArithmeticException.class, SystemClock::elapsedRealtime);
                failure(ArithmeticException.class, SystemClock::uptimeMillis);
                break;
            case "missing": failure(UnsatisfiedLinkError.class, SystemClock::elapsedRealtime); break;
            case "unsupported": failure(UnsupportedOperationException.class, SystemClock::uptimeMillis); break;
            default: throw new AssertionError("unknown test mode");
        }
        System.out.println("PASS SystemClock " + args[0] + ": " + checks + " checks");
    }
}
