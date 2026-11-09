// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package com.atakmap.database.android;
import android.database.*;
import android.database.sqlite.*;
import android.content.ContentValues;
import com.atakmap.database.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
public final class DesktopSQLiteTest {
    static int checks;
    static void check(boolean value,String label){
        checks++;
        if(!value)throw new AssertionError(label);
    }
    static long scalar(SQLiteDatabase db,String sql){
        try(Cursor c=db.rawQuery(sql,null)){
            check(c.moveToFirst(),"scalar row");
            return c.getLong(0);
        }
    }
    static void failure(Class<? extends Throwable> type,Runnable action){
        try{
            action.run();
            throw new AssertionError("expected "+type);
        }
        catch(Throwable e){
            if(!type.isInstance(e))throw new AssertionError("wrong failure "+e,e);
            checks++;
        }
    }
    public static void main(String[] args)throws Exception{
        try(SQLiteDatabase db=SQLiteDatabase.create(null)){
            db.execSQL("CREATE TABLE sample(id INTEGER PRIMARY KEY, name TEXT UNIQUE, n INTEGER, data BLOB, f REAL, z)");
            ContentValues values=new ContentValues();
            values.put("name","quote ' ? -- text");
            values.put("n",Long.MIN_VALUE+1);
            values.put("data",new byte[]{
                0,(byte)255
            });
            values.put("f",1.25);
            values.putNull("z");
            check(db.insertOrThrow("sample",null,values)==1,"real inserted rowid");
            check(db.insert("sample",null,values)==-1,"nonthrowing insert failure");
            try(Cursor c=db.rawQuery("SELECT * FROM sample",null)){
                check(c.getCount()==1&&c.getPosition()==-1&&c.isBeforeFirst(),"initial cursor position/count");
                failure(IndexOutOfBoundsException.class,()->c.getLong(0));
                check(c.moveToFirst(),"move first");
                check(c.getLong(c.getColumnIndex("N"))==Long.MIN_VALUE+1,"64-bit integer/case-insensitive column");
                check(Arrays.equals(c.getBlob(3),new byte[]{
                    0,(byte)255
                }),"actual BLOB");
                check(c.getDouble(4)==1.25&&c.getType(4)==Cursor.FIELD_TYPE_FLOAT,"real float type");
                check(c.isNull(5)&&c.getInt(5)==0&&c.getString(5)==null,"NULL getters");
                check(!c.moveToNext()&&c.isAfterLast()&&c.getPosition()==1,"after-last position");
                check(c.moveToPrevious()&&c.isFirst()&&c.isLast(),"backward navigation");
                check(!c.moveToPosition(-10)&&c.getPosition()==-1,"before-first clamp");
            }
            // Unchanged upstream query factory binds BLOB/numeric values before executing SQLiteCursor.
            try(QueryIface query=new AndroidQueryStatement(db,"SELECT n,data FROM sample WHERE data=? AND n=?")){
                query.bind(1,new byte[]{
                    0,(byte)255
                });
                query.bind(2,Long.MIN_VALUE+1);
                check(query.moveToNext(),"actual upstream factory query");
                check(query.getLong(0)==Long.MIN_VALUE+1&&Arrays.equals(query.getBlob(1),new byte[]{
                    0,(byte)255
                }),"factory preserves typed binds");
                query.reset();
                query.bind(2,7);
                check(!query.moveToNext(),"query reset/rebind");
            }
            StatementIface upstreamStatement=new AndroidStatementAdapter(db.compileStatement("UPDATE sample SET n=? WHERE id=?"),AndroidStatementAdapter.STMT_TYPE_UPDATE);
            try{
                upstreamStatement.bind(1,7);
                upstreamStatement.bind(2,1);
                upstreamStatement.execute();
                upstreamStatement.clearBindings();
            }
            finally{
                upstreamStatement.close();
            }
            check(scalar(db,"SELECT n FROM sample")==7,"actual upstream statement adapter");
            CursorIface source=new AndroidCursorAdapter(db.rawQuery("SELECT n,data,NULL FROM sample UNION ALL SELECT 8,X'01','end'",null));
            try(CursorIfaceAdapter window=new CursorIfaceAdapter(source)){
                check(window.getCount()==2,"actual upstream window getCount");
                check(window.moveToPosition(1)&&window.getLong(0)==8&&window.getString(2).equals("end"),"actual upstream random window row");
                check(window.moveToFirst()&&window.getType(2)==Cursor.FIELD_TYPE_NULL,"actual upstream backward type");
            }
            finally{
                source.close();
            }
            // Pinned CursorIfaceAdapter itself does not close its delegate.
            db.beginTransaction();
            db.execSQL("INSERT INTO sample(name) VALUES('outer')");
            db.beginTransaction();
            db.execSQL("INSERT INTO sample(name) VALUES('inner')");
            db.endTransaction();
            db.setTransactionSuccessful();
            db.endTransaction();
            check(scalar(db,"SELECT count(*) FROM sample")==1,"unsuccessful inner forces complete rollback");
            db.beginTransaction();
            db.beginTransaction();
            db.execSQL("INSERT INTO sample(name) VALUES('committed')");
            db.setTransactionSuccessful();
            db.endTransaction();
            db.setTransactionSuccessful();
            failure(IllegalStateException.class,db::setTransactionSuccessful);
            failure(IllegalStateException.class,db::beginTransaction);
            db.endTransaction();
            check(scalar(db,"SELECT count(*) FROM sample")==2,"nested successful commit");
            failure(IllegalStateException.class,db::endTransaction);
            db.beginTransaction();
            ExecutorService executor=Executors.newSingleThreadExecutor();
            try{
                CountDownLatch started=new CountDownLatch(1);
                Future<Long> blocked=executor.submit(()->{
                    started.countDown();
                    return scalar(db,"SELECT count(*) FROM sample");
                });
                check(started.await(2,TimeUnit.SECONDS),"other thread started");
                Thread.sleep(100);
                check(!blocked.isDone(),"other thread cannot enter transaction connection");
                db.endTransaction();
                check(blocked.get(2,TimeUnit.SECONDS)==2,"other thread resumes after transaction");
            }
            finally{
                if(db.inTransaction())db.endTransaction();
                executor.shutdownNow();
            }
            ContentValues update=new ContentValues();
            update.put("n",9);
            check(db.update("sample",update,"id=?",new String[]{
                "1"
            })==1,"affected update rows");
            check(db.delete("sample","name=?",new String[]{
                "committed"
            })==1,"affected delete rows");
            SQLiteQueryBuilder builder=new SQLiteQueryBuilder();
            builder.setTables("sample");
            builder.appendWhere("id>0");
            try(Cursor c=builder.query(db,new String[]{
                "n"
            },"id=?",new String[]{
                "1"
            },null,null,null,"1")){
                check(c.moveToFirst()&&c.getInt(0)==9,"query builder/bound selection");
            }
            failure(IllegalArgumentException.class,()->SQLiteQueryBuilder.buildQueryString(false,"sample",null,null,null,null,null,"1; DROP TABLE sample"));
            failure(UnsupportedOperationException.class,()->db.execSQL("PRAGMA key='not-supported'"));
            Cursor cursor=db.rawQuery("SELECT 1",null);
            cursor.close();
            cursor.close();
            failure(IllegalStateException.class,cursor::moveToFirst);
            SQLiteStatement statement=db.compileStatement("SELECT 1");
            statement.close();
            failure(IllegalStateException.class,statement::simpleQueryForLong);
            try(Cursor c=db.rawQuery("SELECT ' 12.75xyz', '999999999999999999999999'",null)){
                c.moveToFirst();
                check(c.getLong(0)==12&&c.getDouble(0)==12.75,"numeric text prefix conversion");
                check(c.getLong(1)==Long.MAX_VALUE,"integer overflow clamp");
            }
            try(SQLiteStatement insert=db.compileStatement("INSERT INTO sample(name,f) VALUES(?,?)")){
                insert.bindString(1,"nan");
                insert.bindDouble(2,Double.NaN);
                insert.executeInsert();
            }
            try(Cursor c=db.rawQuery("SELECT f FROM sample WHERE name='nan'",null)){
                c.moveToFirst();
                check(c.isNull(0),"SQLite converts NaN to NULL");
            }
            CursorWindow conversions=new CursorWindow("conversions");
            conversions.setNumColumns(1);
            conversions.allocRow();
            conversions.putString("012",0,0);
            check(conversions.getLong(0,0)==10,"AOSP window strtoll base-zero octal");
            conversions.putString("-0x10",0,0);
            check(conversions.getLong(0,0)==-16,"AOSP window hex prefix");
            conversions.putString("0x1.8p1",0,0);
            check(conversions.getDouble(0,0)==3,"window hex double");
            conversions.putString("abc",0,0);
            check(Arrays.equals(conversions.getBlob(0,0),new byte[]{
                97,98,99,0
            }),"AOSP window string storage includes terminator");
            conversions.putString("NaN",0,0);
            check(Double.isNaN(conversions.getDouble(0,0)),"window string NaN");
            conversions.putDouble(1,0,0);
            check(conversions.getString(0,0).equals("1"),"window native percent-g formatting");
            conversions.putBlob(new byte[]{
                1
            },0,0);
            failure(SQLiteException.class,()->conversions.getLong(0,0));
            failure(SQLiteException.class,()->conversions.getDouble(0,0));
            conversions.close();
            CursorWindow budget=new CursorWindow("bound");
            budget.setNumColumns(1);
            budget.allocRow();
            failure(SQLiteException.class,()->budget.putBlob(new byte[17*1024*1024],0,0));
            budget.close();
        }
        Path dir=Files.createTempDirectory("desktop-sqlite-");
        String path=dir.resolve("file.sqlite").toString();
        try{
            SQLiteOpenHelper first=helper(path,1,false);
            SQLiteDatabase db=first.getWritableDatabase();
            check(db.getVersion()==1&&scalar(db,"SELECT count(*) FROM lifecycle")==1,"helper create/version");
            first.close();
            SQLiteOpenHelper broken=helper(path,2,true);
            failure(IllegalStateException.class,broken::getWritableDatabase);
            try(SQLiteDatabase reopened=SQLiteDatabase.openDatabase(path,null,0)){
                check(reopened.getVersion()==1,"failed upgrade rolls back version");
                check(scalar(reopened,"SELECT count(*) FROM lifecycle")==1,"failed upgrade rolls back data");
            }
            SQLiteOpenHelper upgrade=helper(path,2,false);
            check(upgrade.getWritableDatabase().getVersion()==2,"successful helper upgrade");
            upgrade.close();
            SQLiteOpenHelper readable=new SQLiteOpenHelper(null,path,null,2){
                public void onConfigure(SQLiteDatabase configured){
                    if(!configured.isReadOnly())throw new SQLiteException("test policy requires read-only");
                }
                public void onCreate(SQLiteDatabase configured){
                    throw new AssertionError("must not create read-only schema");
                }
                public void onUpgrade(SQLiteDatabase configured,int oldVersion,int next){
                    throw new AssertionError("must not upgrade read-only schema");
                }
            };
            SQLiteDatabase readableDb=readable.getReadableDatabase();
            check(readableDb.isReadOnly()&&readable.getReadableDatabase()==readableDb,"helper read-only fallback/cache");
            readable.close();
            try(SQLiteDatabase readOnly=SQLiteDatabase.openDatabase(path,null,SQLiteDatabase.OPEN_READONLY)){
                check(readOnly.isReadOnly()&&readOnly.getVersion()==2,"read-only real file/version");
                failure(SQLiteException.class,()->readOnly.execSQL("INSERT INTO lifecycle VALUES(3)"));
            }
            Path corrupt=dir.resolve("corrupt.sqlite");
            Files.writeString(corrupt,"not a database");
            boolean[] handled={
                false
            };
            SQLiteDatabase bad=SQLiteDatabase.openDatabase(corrupt.toString(),null,0,database->{
                handled[0]=true;
                database.close();
            });
            failure(SQLiteException.class,bad::getVersion);
            check(handled[0]&&!bad.isOpen(),"real corruption error callback");
        }
        finally{
            try(var paths=Files.walk(dir)){
                for(Path p:paths.sorted(Comparator.reverseOrder()).collect(java.util.stream.Collectors.toList()))Files.delete(p);
            }
        }
        System.out.println("Desktop SQLite: "+checks+" assertions, real JDBC/JNI and unchanged upstream adapter consumers PASS");
    }
    static SQLiteOpenHelper helper(String path,int version,boolean fail){
        return new SQLiteOpenHelper(null,path,null,version){
            public void onCreate(SQLiteDatabase db){
                db.execSQL("CREATE TABLE lifecycle(n)");
                db.execSQL("INSERT INTO lifecycle VALUES(1)");
            }
            public void onUpgrade(SQLiteDatabase db,int old,int next){
                db.execSQL("INSERT INTO lifecycle VALUES(2)");
                if(fail)throw new IllegalStateException("upgrade test failure");
            }
        };
    }
}
