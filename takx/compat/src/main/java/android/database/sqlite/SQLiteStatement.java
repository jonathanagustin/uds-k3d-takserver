// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database.sqlite;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
public final class SQLiteStatement extends SQLiteProgram {
    SQLiteStatement(SQLiteDatabase db,PreparedStatement statement){
        super(db,statement);
    }
    public void execute(){
        database.operation(()->{
            check();
            statement.execute();
            return null;
        });
    }
    public int executeUpdateDelete(){
        return database.operation(()->{
            check();
            return statement.executeUpdate();
        });
    }
    public long executeInsert(){
        return database.operation(()->{
            check();
            if(statement.executeUpdate()==0)return -1L;
            try(java.sql.Statement s=database.connection.createStatement();
            ResultSet r=s.executeQuery("SELECT last_insert_rowid()")){
                if(!r.next())throw new java.sql.SQLException("missing rowid");
                return r.getLong(1);
            }
        });
    }
    public long simpleQueryForLong(){
        return database.operation(()->{
            check();
            try(ResultSet r=statement.executeQuery()){
                if(!r.next())throw new SQLiteException("query returned no rows");
                return r.getLong(1);
            }
        });
    }
    public String simpleQueryForString(){
        return database.operation(()->{
            check();
            try(ResultSet r=statement.executeQuery()){
                if(!r.next())throw new SQLiteException("query returned no rows");
                return r.getString(1);
            }
        });
    }
}
