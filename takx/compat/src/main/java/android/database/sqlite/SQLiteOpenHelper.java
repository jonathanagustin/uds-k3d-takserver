// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database.sqlite;
import android.content.Context;
import java.io.File;
/** Actual plain-SQLite schema lifecycle, including rollback of failed version upgrades. */
public abstract class SQLiteOpenHelper implements AutoCloseable {
    private final Context context;
    private final String name;
    private final SQLiteDatabase.CursorFactory factory;
    private final int version;
    private SQLiteDatabase database;
    private boolean initializing;
    public SQLiteOpenHelper(Context context,String name,SQLiteDatabase.CursorFactory factory,int version){
        if(version<1)throw new IllegalArgumentException("version must be positive");
        this.context=context;
        this.name=name;
        this.factory=factory;
        this.version=version;
    }
    public synchronized SQLiteDatabase getWritableDatabase(){
        if(database!=null&&database.isOpen()&&!database.isReadOnly())return database;
        if(initializing)throw new IllegalStateException("recursive database initialization");
        initializing=true;
        SQLiteDatabase opened=null;
        try{
            String path=":memory:";
            if(name!=null){
                File file=new File(name);
                if(!file.isAbsolute())file=new File(new File(context.getFilesDir(),"databases"),name);
                File parent=file.getParentFile();
                if(parent!=null&&!parent.isDirectory()&&!parent.mkdirs())throw new SQLiteException("cannot create database directory");
                path=file.getPath();
            }
            opened=SQLiteDatabase.openOrCreateDatabase(path,factory);
            onConfigure(opened);
            int old=opened.getVersion();
            if(old!=version){
                opened.beginTransaction();
                try{
                    if(old==0)onCreate(opened);
                    else if(old<version)onUpgrade(opened,old,version);
                    else onDowngrade(opened,old,version);
                    opened.setVersion(version);
                    opened.setTransactionSuccessful();
                }
                finally{
                    opened.endTransaction();
                }
            }
            onOpen(opened);
            if(database!=null)database.close();
            database=opened;
            opened=null;
            return database;
        }
        finally{
            initializing=false;
            if(opened!=null)opened.close();
        }
    }
    public synchronized SQLiteDatabase getReadableDatabase(){
        if(database!=null&&database.isOpen())return database;
        try{
            return getWritableDatabase();
        }
        catch(SQLiteException writableFailure){
            if(name==null)throw writableFailure;
            File file=new File(name);
            if(!file.isAbsolute())file=new File(new File(context.getFilesDir(),"databases"),name);
            SQLiteDatabase readOnly=SQLiteDatabase.openDatabase(file.getPath(),factory,SQLiteDatabase.OPEN_READONLY);
            try{
                onConfigure(readOnly);
                if(readOnly.getVersion()!=version)throw new SQLiteException("cannot change read-only schema version",writableFailure);
                onOpen(readOnly);
                database=readOnly;
                return database;
            }
            catch(RuntimeException|Error failure){
                readOnly.close();
                throw failure;
            }
        }
    }
    public String getDatabaseName(){
        return name;
    }
    public void onConfigure(SQLiteDatabase db){
    }
    public abstract void onCreate(SQLiteDatabase db);
    public abstract void onUpgrade(SQLiteDatabase db,int oldVersion,int newVersion);
    public void onDowngrade(SQLiteDatabase db,int oldVersion,int newVersion){
        throw new SQLiteException("downgrade requires explicit implementation");
    }
    public void onOpen(SQLiteDatabase db){
    }
    @Override public synchronized void close(){
        if(initializing)throw new IllegalStateException("close during initialization");
        if(database!=null){
            database.close();
            database=null;
        }
    }
}
