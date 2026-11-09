// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database;
public interface Cursor extends AutoCloseable {
    int FIELD_TYPE_NULL=0, FIELD_TYPE_INTEGER=1, FIELD_TYPE_FLOAT=2, FIELD_TYPE_STRING=3, FIELD_TYPE_BLOB=4;
    int getCount();
    int getPosition();
    boolean move(int offset);
    boolean moveToPosition(int position);
    boolean moveToFirst();
    boolean moveToLast();
    boolean moveToNext();
    boolean moveToPrevious();
    boolean isFirst();
    boolean isLast();
    boolean isBeforeFirst();
    boolean isAfterLast();
    int getColumnIndex(String name);
    int getColumnIndexOrThrow(String name);
    String getColumnName(int column);
    String[] getColumnNames();
    int getColumnCount();
    byte[] getBlob(int column);
    String getString(int column);
    short getShort(int column);
    int getInt(int column);
    long getLong(int column);
    float getFloat(int column);
    double getDouble(int column);
    int getType(int column);
    boolean isNull(int column);
    boolean isClosed();
    void close();
}
