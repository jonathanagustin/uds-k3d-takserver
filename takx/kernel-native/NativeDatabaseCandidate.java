// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.database.DatabaseIface;
import com.atakmap.database.CursorIface;
import com.atakmap.database.StatementIface;
import com.atakmap.database.impl.DatabaseImpl;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Real native Database2 controls; invoke after verified explicit provider loading. */
public final class NativeDatabaseCandidate {
  static void check(boolean ok,String text){if(!ok)throw new AssertionError(text);}
  static String scalar(DatabaseIface db,String sql){
    CursorIface c=db.query(sql,null);try{check(c!=null&&c.moveToNext(),"scalar row");return c.getString(0);}finally{if(c!=null)c.close();}
  }
  static void verifyRow(DatabaseIface db){
    CursorIface c=db.query("SELECT label,payload,n FROM proof WHERE id=1",null);
    try{check(c!=null&&c.moveToNext(),"native database row");check("native-encrypted-payload".equals(c.getString(0)),"native text");check(Arrays.equals(new byte[]{0,1,42,(byte)255},c.getBlob(1)),"native BLOB");check(c.getLong(2)==9007199254740993L,"native int64");check(!c.moveToNext(),"one row");}finally{if(c!=null)c.close();}
  }
  public static void run(Path privateDirectory) throws Exception {
    Path file=privateDirectory.resolve("native-database2-encrypted.sqlite").toAbsolutePath();check(!Files.exists(file),"new owned database required");
    String correct="private-proof-correct-key-0123",wrong="private-proof-wrong-key-0987";
    DatabaseIface db=DatabaseImpl.open(file.toString(),correct,DatabaseImpl.OPEN_CREATE);check(db!=null,"native encrypted open");
    try{
      check("3.45.3".equals(scalar(db,"SELECT sqlite_version()")),"actual Core SQLite identity");
      check(scalar(db,"PRAGMA cipher_version").startsWith("4.5.7"),"actual SQLCipher identity");
      db.execute("CREATE TABLE proof(id INTEGER PRIMARY KEY,label TEXT,payload BLOB,n INTEGER)",null);
      StatementIface statement=db.compileStatement("INSERT INTO proof VALUES(?,?,?,?)");
      try{statement.bind(1,1);statement.bind(2,"native-encrypted-payload");statement.bind(3,new byte[]{0,1,42,(byte)255});statement.bind(4,9007199254740993L);statement.execute();}finally{statement.close();}
      verifyRow(db);
    }finally{db.close();}
    byte[] bytes=Files.readAllBytes(file);check(bytes.length>16,"persistent encrypted bytes");check(!Arrays.equals(Arrays.copyOf(bytes,16),"SQLite format 3\0".getBytes(StandardCharsets.US_ASCII)),"plaintext header forbidden");
    db=DatabaseImpl.open(file.toString(),correct,DatabaseImpl.OPEN_READONLY);check(db!=null,"correct-key reopen");try{verifyRow(db);}finally{db.close();}
    boolean rejected=false;DatabaseIface bad=null;
    try{bad=DatabaseImpl.open(file.toString(),wrong,DatabaseImpl.OPEN_READONLY);if(bad==null)rejected=true;else verifyRow(bad);}
    catch(android.database.SQLException expected){for(Throwable t=expected;t!=null;t=t.getCause())if(t instanceof Error)throw new AssertionError("wrong-key control had linkage/runtime Error",t);rejected=true;}
    finally{if(bad!=null)bad.close();}
    check(rejected,"wrong key must fail native data read");
    db=DatabaseImpl.open(file.toString(),correct,DatabaseImpl.OPEN_READONLY);check(db!=null,"correct key after failed key");try{verifyRow(db);}finally{db.close();}
    System.out.println("PASS_PREPARED_NATIVE_DATABASE2_ENCRYPTED_OPEN_REOPEN_WRONG_KEY_CONTROL");
  }
}
