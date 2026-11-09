// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database.sqlite;
import android.database.AbstractWindowedCursor;
import android.database.CursorWindow;
import java.sql.ResultSet;
/** Executes only after a CursorFactory has bound the real SQLiteQuery. */
public final class SQLiteCursor extends AbstractWindowedCursor {
    private final String[] names;
    private final SQLiteQuery query;
    private final SQLiteCursorDriver driver;
    private int count;
    public SQLiteCursor(SQLiteCursorDriver driver,String table,SQLiteQuery query){
        this.query=query;
        this.driver=driver;
        names=query.database.operation(()->{
            query.check();
            mWindow=new CursorWindow("JDBC");
            try(ResultSet rows=query.statement.executeQuery()){
                int columns=rows.getMetaData().getColumnCount();
                String[] names=new String[columns];
                for(int i=0;i<columns;i++)names[i]=rows.getMetaData().getColumnLabel(i+1);
                mWindow.setNumColumns(columns);
                while(rows.next()){
                    mWindow.allocRow();
                    for(int i=0;i<columns;i++){
                        Object value=rows.getObject(i+1);
                        if(value==null)mWindow.putNull(count,i);
                        else if(value instanceof byte[])mWindow.putBlob((byte[])value,count,i);
                        else if(value instanceof Float||value instanceof Double)mWindow.putDouble(((Number)value).doubleValue(),count,i);
                        else if(value instanceof Number)mWindow.putLong(((Number)value).longValue(),count,i);
                        else mWindow.putString(value.toString(),count,i);
                    }
                    count++;
                }
                return names;
            }
            catch(RuntimeException|java.sql.SQLException e){
                mWindow.close();
                throw e;
            }
        });
    }
    @Override public String[] getColumnNames(){
        checkOpen();
        return names.clone();
    }
    @Override public int getCount(){
        checkOpen();
        return count;
    }
    @Override public void close(){
        if(!isClosed()){
            super.close();
            driver.cursorClosed();
        }
    }
}
