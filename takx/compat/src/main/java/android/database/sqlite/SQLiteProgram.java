// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database.sqlite;
import java.sql.PreparedStatement;
import java.sql.Types;
/** Real prepared statement and 1-based SQLite bindings. */
public class SQLiteProgram implements AutoCloseable {
    final SQLiteDatabase database;
    final PreparedStatement statement;
    private boolean closed;
    SQLiteProgram(SQLiteDatabase db,PreparedStatement statement){
        database=db;
        this.statement=statement;
    }
    void check(){
        if(closed)throw new IllegalStateException("statement closed");
    }
    public void bindNull(int i){
        database.operation(()->{
            check();
            statement.setNull(i,Types.NULL);
            return null;
        });
    }
    public void bindLong(int i,long v){
        database.operation(()->{
            check();
            statement.setLong(i,v);
            return null;
        });
    }
    public void bindDouble(int i,double v){
        database.operation(()->{
            check();
            statement.setDouble(i,v);
            return null;
        });
    }
    public void bindString(int i,String v){
        java.util.Objects.requireNonNull(v);
        database.operation(()->{
            check();
            statement.setString(i,v);
            return null;
        });
    }
    public void bindBlob(int i,byte[] v){
        java.util.Objects.requireNonNull(v);
        database.operation(()->{
            check();
            statement.setBytes(i,v);
            return null;
        });
    }
    public void clearBindings(){
        database.operation(()->{
            check();
            statement.clearParameters();
            return null;
        });
    }
    void bindAll(Object[] values){
        for(int i=0;i<values.length;i++){
            Object v=values[i];
            if(v==null)bindNull(i+1);
            else if(v instanceof byte[])bindBlob(i+1,(byte[])v);
            else if(v instanceof Float||v instanceof Double)bindDouble(i+1,((Number)v).doubleValue());
            else if(v instanceof Number)bindLong(i+1,((Number)v).longValue());
            else if(v instanceof Boolean)bindLong(i+1,(Boolean)v?1:0);
            else bindString(i+1,v.toString());
        }
    }
    @Override public void close(){
        if(closed)return;
        if(!database.isOpen()){
            closed=true;
            return;
        }
        database.operation(()->{
            if(!closed){
                statement.close();
                closed=true;
            }
            return null;
        });
    }
}
