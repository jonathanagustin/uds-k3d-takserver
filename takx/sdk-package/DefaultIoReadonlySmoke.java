// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import android.database.sqlite.SQLiteException;
import com.atakmap.coremap.io.DatabaseInformation;
import com.atakmap.coremap.io.DefaultIOProvider;
import com.atakmap.coremap.io.IOProviderFactory;
import com.atakmap.database.CursorIface;
import com.atakmap.database.DatabaseIface;
import com.atakmap.database.Databases;
import com.atakmap.map.layer.raster.mbtiles.MBTilesContainer;
import com.atakmap.map.layer.raster.tilematrix.TileContainer;
import java.io.File;
import java.nio.file.*;
import java.util.*;

/** Actual native database/provider/MBTiles contracts; runs after stock initialization. */
public final class DefaultIoReadonlySmoke {
  private static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
  private static void rejectSqlWrite(DatabaseIface db,Runnable action) {
    check(db.isReadOnly(),"native connection reports readonly");verifyRow(db);
    boolean rejected=false;try{action.run();}catch(SQLiteException expected){rejected=true;}
    check(rejected,"actual SQLiteException from validated readonly write");verifyRow(db);
  }
  private static void rejectTileWrite(Runnable action) {
    boolean rejected=false;
    try{action.run();}catch(UnsupportedOperationException failure){
      String message=String.valueOf(failure.getMessage()).toLowerCase(Locale.ROOT);
      rejected=message.contains("readonly")||message.contains("read-only")||message.contains("read only");
      if(!rejected)throw failure;
    }
    check(rejected,"actual read-only write rejection");
  }
  private static void verifyRow(DatabaseIface db) {
    CursorIface cursor=db.query("SELECT value FROM test_readonly ORDER BY value",null);
    try{check(cursor.moveToNext()&&cursor.getString(0).equals("original")&&!cursor.moveToNext(),"unchanged genuine row");}finally{cursor.close();}
  }
  public static void run(Path jar,Path data)throws Exception {
    check(Path.of(DefaultIOProvider.class.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath().equals(jar),"actual patched provider must originate in rebuilt SDK JAR");
    Path root=Files.createDirectory(data.resolve("default-io-readonly"));File file=root.resolve("contract.sqlite").toFile();
    DatabaseIface db=IOProviderFactory.createDatabase(file,0);check(db!=null&&!db.isReadOnly(),"zero-option actual writable create");
    try{db.execute("CREATE TABLE test_readonly (value TEXT NOT NULL)",null);db.execute("INSERT INTO test_readonly VALUES ('original')",null);
      db.execute("INSERT INTO test_readonly VALUES ('forbidden')",null);db.execute("DELETE FROM test_readonly WHERE value='forbidden'",null);verifyRow(db);}finally{db.close();}
    db=Databases.openDatabase(file.getAbsolutePath(),true);check(db!=null&&db.isReadOnly(),"direct native readonly");
    try{verifyRow(db);DatabaseIface current=db;rejectSqlWrite(current,()->current.execute("INSERT INTO test_readonly VALUES ('forbidden')",null));}finally{db.close();}
    db=IOProviderFactory.createDatabase(file,DatabaseInformation.OPTION_READONLY);check(db!=null&&db.isReadOnly(),"provider preserves readonly option");
    try{verifyRow(db);DatabaseIface current=db;rejectSqlWrite(current,()->current.execute("INSERT INTO test_readonly VALUES ('forbidden')",null));}finally{db.close();}
    db=IOProviderFactory.createDatabase(file,0);try{check(db!=null&&!db.isReadOnly(),"writable reopen retained");verifyRow(db);db.execute("INSERT INTO test_readonly VALUES ('writable')",null);db.execute("DELETE FROM test_readonly WHERE value='writable'",null);verifyRow(db);}finally{if(db!=null)db.close();}
    File missing=root.resolve("must-not-create.sqlite").toFile();DatabaseIface absent=null;boolean failed=false;
    try{absent=IOProviderFactory.createDatabase(missing,DatabaseInformation.OPTION_READONLY);failed=absent==null;}catch(RuntimeException expected){failed=true;}finally{if(absent!=null)absent.close();}
    check(failed&&!missing.exists(),"readonly missing path fails without file creation");
    File tilesFile=root.resolve("contract.mbtiles").toFile();byte[] original={1,3,7,11};
    TileContainer tiles=MBTilesContainer.SPI.create("readonly-contract",tilesFile.getAbsolutePath(),null);check(tiles!=null&&!tiles.isReadOnly(),"genuine writable MBTiles create");
    try{tiles.setTile(0,0,0,original,0);check(Arrays.equals(tiles.getTileData(0,0,0,null),original),"initial actual MBTiles bytes");}finally{tiles.dispose();}
    tiles=MBTilesContainer.SPI.open(tilesFile.getAbsolutePath(),null,true);check(tiles!=null&&tiles.isReadOnly(),"MBTiles SPI readonly propagated");
    try{check(Arrays.equals(tiles.getTileData(0,0,0,null),original),"readonly tile read");TileContainer current=tiles;rejectTileWrite(()->current.setTile(0,0,0,new byte[]{9},0));}finally{tiles.dispose();}
    tiles=MBTilesContainer.SPI.open(tilesFile.getAbsolutePath(),null,false);check(tiles!=null&&!tiles.isReadOnly(),"MBTiles writable reopen");
    try{check(Arrays.equals(tiles.getTileData(0,0,0,null),original),"rejected MBTiles write left bytes unchanged");byte[] changed={2,4,8};tiles.setTile(0,0,0,changed,0);check(Arrays.equals(tiles.getTileData(0,0,0,null),changed),"writable MBTiles update retained");}finally{tiles.dispose();}
    System.out.println("PASS_REAL_DEFAULT_IO_READONLY_WRITE_REJECTION_NO_CREATE_MBTILES");
  }
}
