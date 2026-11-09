// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database.sqlite;
public class SQLiteException extends android.database.SQLException {
    public SQLiteException() {
    }
    public SQLiteException(String message) {
        super(message);
    }
    public SQLiteException(String message, Throwable cause) {
        super(message,cause);
    }
}
