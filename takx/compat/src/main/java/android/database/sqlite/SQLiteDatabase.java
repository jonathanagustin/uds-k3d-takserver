// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database.sqlite;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.DatabaseErrorHandler;
import java.sql.*;
import java.util.*;
import java.util.concurrent.locks.ReentrantLock;
/** Plain SQLite JDBC desktop backend; SQLCipher, SpatiaLite and native engine pointers are absent. */
public final class SQLiteDatabase implements AutoCloseable {
    public static final int OPEN_READWRITE=0, OPEN_READONLY=1, NO_LOCALIZED_COLLATORS=16, CREATE_IF_NECESSARY=0x10000000;
    public interface CursorFactory {
        Cursor newCursor(SQLiteDatabase db,SQLiteCursorDriver driver,String table,SQLiteQuery query);
    }
    interface Operation<T>{
        T run() throws java.sql.SQLException;
    }
    final Connection connection;
    private final String path;
    private final boolean readOnly;
    private final CursorFactory factory;
    private final DatabaseErrorHandler errorHandler;
    private final ReentrantLock lock=new ReentrantLock(true);
    private final Deque<Boolean> transactions=new ArrayDeque<>();
    private volatile Thread owner;
    private boolean transactionFailed;
    private volatile boolean closed;
    private SQLiteDatabase(Connection connection,String path,boolean readOnly,CursorFactory factory,DatabaseErrorHandler handler){
        this.connection=connection;
        this.path=path;
        this.readOnly=readOnly;
        this.factory=factory;
        this.errorHandler=handler;
    }
    public static SQLiteDatabase openDatabase(String path,CursorFactory factory,int flags){
        return openDatabase(path,factory,flags,null);
    }
    public static SQLiteDatabase openDatabase(String path,CursorFactory factory,int flags,DatabaseErrorHandler handler){
        Objects.requireNonNull(path,"path");
        if((flags&~(OPEN_READONLY|NO_LOCALIZED_COLLATORS|CREATE_IF_NECESSARY))!=0)throw new IllegalArgumentException("unsupported SQLite open flags");
        boolean readOnly=(flags&OPEN_READONLY)!=0;
        if(!path.equals(":memory:")&&(flags&CREATE_IF_NECESSARY)==0&&!new java.io.File(path).isFile())throw new SQLiteException("database file does not exist");
        try{
            Class.forName("org.sqlite.JDBC");
            Properties config=new Properties();
            config.setProperty("open_mode",Integer.toString(readOnly?1:2|((flags&CREATE_IF_NECESSARY)!=0?4:0)));
            return new SQLiteDatabase(DriverManager.getConnection("jdbc:sqlite:"+path,config),path,readOnly,factory,handler);
        }
        catch(ClassNotFoundException|java.sql.SQLException e){
            throw new SQLiteException("cannot open SQLite database",e);
        }
    }
    public static SQLiteDatabase openOrCreateDatabase(String path,CursorFactory factory){
        return openDatabase(path,factory,CREATE_IF_NECESSARY);
    }
    public static SQLiteDatabase openOrCreateDatabase(java.io.File path,CursorFactory factory){
        return openOrCreateDatabase(path.getPath(),factory);
    }
    public static SQLiteDatabase create(CursorFactory factory){
        return openOrCreateDatabase(":memory:",factory);
    }
    <T>T operation(Operation<T> action){
        lock.lock();
        try{
            if(closed)throw new IllegalStateException("database closed");
            return action.run();
        }
        catch(java.sql.SQLException e){
            if(errorHandler!=null&&(e.getErrorCode()==11||e.getErrorCode()==26))errorHandler.onCorruption(this);
            throw new SQLiteException("SQLite operation failed (code "+e.getErrorCode()+")",e);
        }
        finally{
            lock.unlock();
        }
    }
    public void execSQL(String sql){
        execSQL(sql,new Object[0]);
    }
    public void execSQL(String sql,Object[] args){
        Objects.requireNonNull(args,"bind arguments");
        supportedSQL(sql);
        try(SQLiteStatement statement=compileStatement(sql)){
            statement.bindAll(args);
            statement.execute();
        }
    }
    private static void supportedSQL(String sql){
        Objects.requireNonNull(sql,"sql");
        if(sql.matches("(?is)\\s*PRAGMA\\s+(?:\\w+\\.)?(?:key|rekey|cipher_\\w*)\\b.*"))throw new UnsupportedOperationException("SQLCipher is not provided");
    }
    public SQLiteStatement compileStatement(String sql){
        supportedSQL(sql);
        return operation(()->new SQLiteStatement(this,connection.prepareStatement(sql)));
    }
    public Cursor rawQuery(String sql,String[] args){
        return rawQueryWithFactory(factory,sql,args,null);
    }
    public Cursor rawQueryWithFactory(CursorFactory factory,String sql,String[] args,String editTable){
        supportedSQL(sql);
        SQLiteQuery query=operation(()->new SQLiteQuery(this,connection.prepareStatement(sql)));
        try{
            if(args!=null)query.bindAll(args);
            SQLiteCursorDriver driver=new SQLiteCursorDriver(){
                public void cursorClosed(){
                    query.close();
                }
            };
            return factory==null?new SQLiteCursor(driver,editTable,query):factory.newCursor(this,driver,editTable,query);
        }
        catch(RuntimeException|Error e){
            query.close();
            throw e;
        }
    }
    public Cursor query(String table,String[] columns,String selection,String[] args,String groupBy,String having,String orderBy){
        return query(table,columns,selection,args,groupBy,having,orderBy,null);
    }
    public Cursor query(String table,String[] columns,String selection,String[] args,String groupBy,String having,String orderBy,String limit){
        return rawQuery(SQLiteQueryBuilder.buildQueryString(false,table,columns,selection,groupBy,having,orderBy,limit),args);
    }
    public Cursor query(boolean distinct,String table,String[] columns,String selection,String[] args,String groupBy,String having,String orderBy,String limit){
        return rawQuery(SQLiteQueryBuilder.buildQueryString(distinct,table,columns,selection,groupBy,having,orderBy,limit),args);
    }
    private static String name(String value){
        if(!value.matches("[A-Za-z_][A-Za-z0-9_]*"))throw new IllegalArgumentException("simple SQL identifier required");
        return '"'+value+'"';
    }
    public long insert(String table,String nullColumnHack,ContentValues values){
        try{
            return insertOrThrow(table,nullColumnHack,values);
        }
        catch(SQLiteException failed){
            return -1;
        }
    }
    public long insertOrThrow(String table,String nullColumnHack,ContentValues values){
        List<String> columns=values==null?List.of():new ArrayList<>(values.keySet());
        String sql;
        Object[] args=new Object[columns.size()];
        if(columns.isEmpty()){
            if(nullColumnHack==null)sql="INSERT INTO "+name(table)+" DEFAULT VALUES";
            else sql="INSERT INTO "+name(table)+" ("+name(nullColumnHack)+") VALUES(NULL)";
        }
        else{
            List<String> quoted=new ArrayList<>();
            for(int i=0;i<columns.size();i++){
                quoted.add(name(columns.get(i)));
                args[i]=values.get(columns.get(i));
            }
            sql="INSERT INTO "+name(table)+" ("+String.join(",",quoted)+") VALUES ("+String.join(",",Collections.nCopies(columns.size(),"?"))+")";
        }
        try(SQLiteStatement statement=compileStatement(sql)){
            statement.bindAll(args);
            return statement.executeInsert();
        }
    }
    public int update(String table,ContentValues values,String where,String[] args){
        if(values==null||values.size()==0)throw new IllegalArgumentException("empty update");
        List<String> assignments=new ArrayList<>();
        List<Object> bound=new ArrayList<>();
        for(String key:values.keySet()){
            assignments.add(name(key)+"=?");
            bound.add(values.get(key));
        }
        if(args!=null)Collections.addAll(bound,args);
        try(SQLiteStatement s=compileStatement("UPDATE "+name(table)+" SET "+String.join(",",assignments)+(where==null||where.isEmpty()?"":" WHERE "+where))){
            s.bindAll(bound.toArray());
            return s.executeUpdateDelete();
        }
    }
    public int delete(String table,String where,String[] args){
        try(SQLiteStatement s=compileStatement("DELETE FROM "+name(table)+(where==null||where.isEmpty()?"":" WHERE "+where))){
            if(args!=null)s.bindAll(args);
            return s.executeUpdateDelete();
        }
    }
    public boolean isReadOnly(){
        return readOnly;
    }
    public boolean isOpen(){
        return !closed;
    }
    public String getPath(){
        return path;
    }
    public int getVersion(){
        try(Cursor c=rawQuery("PRAGMA user_version",null)){
            if(!c.moveToFirst())throw new SQLiteException("missing user_version");
            return c.getInt(0);
        }
    }
    public void setVersion(int version){
        if(version<0)throw new IllegalArgumentException("negative version");
        execSQL("PRAGMA user_version="+version);
    }
    public void beginTransaction(){
        lock.lock();
        boolean keep=false;
        try{
            if(closed)throw new IllegalStateException("database closed");
            if(!transactions.isEmpty()&&transactions.peek())throw new IllegalStateException("cannot nest after transaction marked successful");
            if(transactions.isEmpty()){
                connection.setAutoCommit(false);
                owner=Thread.currentThread();
                transactionFailed=false;
            }
            transactions.push(false);
            keep=true;
        }
        catch(java.sql.SQLException e){
            throw new SQLiteException("cannot begin transaction",e);
        }
        finally{
            if(!keep)lock.unlock();
        }
    }
    private void transactionOwner(){
        if(owner!=Thread.currentThread()||transactions.isEmpty())throw new IllegalStateException("no transaction owned by this thread");
    }
    public void setTransactionSuccessful(){
        transactionOwner();
        if(transactions.peek())throw new IllegalStateException("transaction already successful");
        transactions.pop();
        transactions.push(true);
    }
    public boolean inTransaction(){
        return owner==Thread.currentThread()&&!transactions.isEmpty();
    }
    public void endTransaction(){
        transactionOwner();
        try{
            if(!transactions.pop())transactionFailed=true;
            if(transactions.isEmpty()){
                try{
                    if(transactionFailed)connection.rollback();
                    else connection.commit();
                    connection.setAutoCommit(true);
                }
                catch(java.sql.SQLException e){
                    try{
                        connection.rollback();
                        connection.setAutoCommit(true);
                    }
                    catch(java.sql.SQLException recovery){
                        e.addSuppressed(recovery);
                        try{
                            connection.close();
                        }
                        catch(java.sql.SQLException ignored){
                            e.addSuppressed(ignored);
                        }
                        closed=true;
                    }
                    throw new SQLiteException("transaction completion failed",e);
                }
                finally{
                    owner=null;
                    transactionFailed=false;
                }
            }
        }
        finally{
            lock.unlock();
        }
    }
    @Override public void close(){
        if(inTransaction())throw new IllegalStateException("end transaction before closing");
        lock.lock();
        try{
            if(!closed){
                try{
                    connection.close();
                }
                catch(java.sql.SQLException e){
                    throw new SQLiteException("close failed",e);
                }
                finally{
                    closed=true;
                }
            }
        }
        finally{
            lock.unlock();
        }
    }
}
