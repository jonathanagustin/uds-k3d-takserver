// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database.sqlite;
import java.sql.PreparedStatement;
public final class SQLiteQuery extends SQLiteProgram {
    SQLiteQuery(SQLiteDatabase db,PreparedStatement statement){
        super(db,statement);
    }
}
