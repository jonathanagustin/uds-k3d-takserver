// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import org.sqlite.SQLiteConfig;

/** Actual independently source-built JDBC/native tests; no Android facade. */
public final class SQLiteSourceSmoke {
    static int checks;
    static void check(boolean result, String message) { checks++; if (!result) throw new AssertionError(message); }
    static long number(Connection c, String sql) throws Exception {
        try (Statement s=c.createStatement(); ResultSet r=s.executeQuery(sql)) { check(r.next(),"scalar row"); return r.getLong(1); }
    }
    static List<Object[]> materialize(ResultSet r, int maxRows) throws Exception {
        List<Object[]> rows=new ArrayList<>();
        while(r.next()) {
            if(rows.size()>=maxRows) throw new IllegalStateException("explicit row limit reached");
            Object[] row=new Object[r.getMetaData().getColumnCount()];
            for(int i=0;i<row.length;i++) { Object v=r.getObject(i+1); row[i]=v instanceof byte[] ? ((byte[])v).clone() : v; }
            rows.add(row);
        }
        return rows;
    }
    public static void main(String[] args) throws Exception {
        Class.forName("org.sqlite.JDBC");
        check(args.length==1,"expected own native path argument");
        try(Connection c=DriverManager.getConnection("jdbc:sqlite::memory:")) {
            try(Statement s=c.createStatement(); ResultSet r=s.executeQuery("SELECT sqlite_version(),sqlite_source_id()")) {
                check(r.next(),"native version row"); check("3.54.1".equals(r.getString(1)),"actual native version");
                check(r.getString(2).endsWith("555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76"),"official locked SQLite source id");
                String mapped=Files.readString(Path.of("/proc/self/maps"));
                check(mapped.contains(Path.of(args[0]).toRealPath().toString()),"own source-built JNI is actually mapped");
                System.out.println("Loaded own native="+Path.of(args[0]).toRealPath());
                System.out.println("Native SQLite version="+r.getString(1)+" source_id="+r.getString(2));
            }
            Set<String> flags=new TreeSet<>();
            try(Statement s=c.createStatement(); ResultSet r=s.executeQuery("PRAGMA compile_options")) { while(r.next())flags.add(r.getString(1)); }
            for(String flag:List.of("ENABLE_COLUMN_METADATA","ENABLE_FTS5","ENABLE_RTREE","ENABLE_UPDATE_DELETE_LIMIT","THREADSAFE=1","JDBC_EXTENSIONS")) check(flags.contains(flag),"required flag "+flag);
            System.out.println("Native compile_options="+String.join(",",flags));
            try(Statement s=c.createStatement()) { s.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, text_value TEXT UNIQUE, bytes BLOB, n INTEGER, r REAL, z)"); }
            byte[] bytes={0,1,(byte)255,0};
            try(PreparedStatement s=c.prepareStatement("INSERT INTO sample(text_value,bytes,n,r,z) VALUES(?,?,?,?,?)")) {
                s.setString(1,"quote ' ? -- text"); s.setBytes(2,bytes); s.setLong(3,Long.MIN_VALUE+7); s.setDouble(4,1.25); s.setNull(5,Types.NULL);
                check(s.executeUpdate()==1,"insert count"); s.clearParameters();
            }
            check(number(c,"SELECT last_insert_rowid()")==1,"last inserted rowid");
            try(PreparedStatement s=c.prepareStatement("SELECT text_value AS Alias,bytes,n,r,z FROM sample WHERE id=?")) {
                s.setInt(1,1);
                try(ResultSet r=s.executeQuery()) {
                    check(r.getType()==ResultSet.TYPE_FORWARD_ONLY,"actual forward-only cursor");
                    List<Object[]> rows=materialize(r,10);
                    check(rows.size()==1,"materialized count"); Object[] row=rows.get(0);
                    check(row[0].equals("quote ' ? -- text"),"bound text is not SQL"); check(Arrays.equals((byte[])row[1],bytes),"blob bytes including zero");
                    check(((Number)row[2]).longValue()==Long.MIN_VALUE+7,"64-bit integer"); check(((Number)row[3]).doubleValue()==1.25,"double"); check(row[4]==null,"SQL NULL preserved");
                    check(r.getMetaData().getColumnLabel(1).equals("Alias"),"column alias");
                }
            }
            try(Statement s=c.createStatement(); ResultSet r=s.executeQuery("SELECT reverse('abc'),replicate('x',3)")) {
                check(r.next() && "cba".equals(r.getString(1)) && "xxx".equals(r.getString(2)),"real retained extension functions");
            }
            c.setAutoCommit(false);
            try(Statement s=c.createStatement()) { s.executeUpdate("INSERT INTO sample(text_value) VALUES('rolled back')"); }
            c.rollback(); check(number(c,"SELECT count(*) FROM sample")==1,"rollback");
            try(Statement s=c.createStatement()) { s.executeUpdate("INSERT INTO sample(text_value) VALUES('committed')"); }
            c.commit(); c.setAutoCommit(true); check(number(c,"SELECT count(*) FROM sample")==2,"commit");
            c.setAutoCommit(false); Savepoint point=c.setSavepoint("nested");
            try(Statement s=c.createStatement()) { s.executeUpdate("INSERT INTO sample(text_value) VALUES('savepoint')"); }
            c.rollback(point); c.releaseSavepoint(point); c.commit(); c.setAutoCommit(true);
            check(number(c,"SELECT count(*) FROM sample")==2,"real savepoint rollback");
            try(Statement s=c.createStatement()) {
                check(s.executeUpdate("UPDATE sample SET r=2 WHERE id=1")==1,"update changes");
                check(s.executeUpdate("DELETE FROM sample WHERE text_value='committed'")==1,"delete changes");
                try { s.executeUpdate("INSERT INTO sample(text_value) VALUES('quote '' ? -- text')"); throw new AssertionError("constraint accepted"); }
                catch(SQLException expected) { check(expected.getErrorCode()==19,"real constraint error"); }
            }
            try(Statement s=c.createStatement(); ResultSet r=s.executeQuery("SELECT NULL,0,'',X''")) {
                check(r.next(),"null row"); check(r.getInt(1)==0 && r.wasNull(),"NULL int conversion/wasNull");
                check(r.getInt(2)==0 && !r.wasNull(),"zero is not NULL"); check(r.getString(3).equals(""),"empty text"); check(r.getBytes(4).length==0,"empty BLOB");
            }
            try(Statement s=c.createStatement(); ResultSet r=s.executeQuery("SELECT 1 UNION ALL SELECT 'two' UNION ALL SELECT X'00FF' UNION ALL SELECT NULL")) {
                List<Object[]> rows=materialize(r,4); check(rows.size()==4,"mixed dynamic types");
                check(rows.get(0)[0] instanceof Number && rows.get(1)[0] instanceof String && rows.get(2)[0] instanceof byte[] && rows.get(3)[0]==null,"per-row storage classes preserved");
                check(rows.get(2)[0] instanceof byte[],"random cached row access");
            }
            try(Statement s=c.createStatement(); ResultSet r=s.executeQuery("SELECT 1 UNION ALL SELECT 2")) {
                try { materialize(r,1); throw new AssertionError("row bound ignored"); } catch(IllegalStateException expected) { check(true,"bounded cursor materialization refuses overflow"); }
            }
            try(Statement s=c.createStatement()) { s.execute("CREATE TABLE limit_test(n)");s.execute("INSERT INTO limit_test VALUES(1),(2),(3)");check(s.executeUpdate("DELETE FROM limit_test LIMIT 1")==1,"compiled update/delete LIMIT works"); }
        }
        Path dir=Files.createTempDirectory("sqlite-source-smoke-"); Path file=dir.resolve("real.sqlite");
        try {
            try(Connection c=DriverManager.getConnection("jdbc:sqlite:"+file);Statement s=c.createStatement()) {s.execute("PRAGMA user_version=7");s.execute("CREATE TABLE persisted(v)");s.execute("INSERT INTO persisted VALUES(42)");}
            SQLiteConfig readOnly=new SQLiteConfig();readOnly.setReadOnly(true);
            try(Connection c=DriverManager.getConnection("jdbc:sqlite:"+file,readOnly.toProperties())) {
                check(number(c,"PRAGMA user_version")==7,"persistent user_version");check(number(c,"SELECT v FROM persisted")==42,"persistent file query");
                try(Statement s=c.createStatement()) {try{s.executeUpdate("INSERT INTO persisted VALUES(43)");throw new AssertionError("read-only write accepted");}catch(SQLException expected){check(expected.getErrorCode()==8,"real read-only error");}}
            }
            check(Files.size(file)>0,"real SQLite file");
        } finally {try(var paths=Files.walk(dir)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.delete(path);}}
        System.out.println("PASS actual source-built SQLite JDBC/native: "+checks+" SQL/bind/cursor/transaction/file assertions; no Android facade or engine JNI claim");
    }
}
