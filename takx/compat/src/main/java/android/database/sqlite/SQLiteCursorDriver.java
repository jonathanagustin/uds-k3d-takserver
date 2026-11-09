// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database.sqlite;
/** Identity passed to a CursorFactory; JDBC resource ownership stays with SQLiteQuery. */
public interface SQLiteCursorDriver {
    void cursorClosed();
}
