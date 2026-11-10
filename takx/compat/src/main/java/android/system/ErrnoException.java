// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.system;

/** Typed filesystem failures with the corresponding Linux errno value. */
public final class ErrnoException extends Exception {
    private static final long serialVersionUID = 1L;
    public final String functionName;
    public final int errno;

    public ErrnoException(String functionName, int errno, Throwable cause) {
        super(functionName + " failed: errno=" + errno, cause);
        this.functionName = functionName;
        this.errno = errno;
    }
}
