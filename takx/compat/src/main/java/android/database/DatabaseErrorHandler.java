// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database;
import android.database.sqlite.SQLiteDatabase;
public interface DatabaseErrorHandler {
    void onCorruption(SQLiteDatabase database);
}
