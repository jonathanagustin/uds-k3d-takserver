// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.math.Matrix;
import com.atakmap.math.PointD;
import com.atakmap.map.EngineLibrary;
import com.atakmap.map.layer.feature.geometry.Geometry;
import com.atakmap.map.layer.feature.geometry.GeometryFactory;
import com.atakmap.map.layer.feature.geometry.Point;
import com.atakmap.map.projection.Projection;
import com.atakmap.map.projection.ProjectionFactory;
import com.atakmap.coremap.maps.coords.GeoPoint;
import com.atakmap.util.ConfigOptions;
import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;

/** Owned real JNI controls; no substitute SDK APIs, loaders or libraries. */
public final class KernelRuntimeSmoke {
  static void check(boolean condition,String message) { if(!condition)throw new AssertionError(message); }
  static String hash(Path path) throws Exception {
    MessageDigest md=MessageDigest.getInstance("SHA-256");
    try(InputStream input=Files.newInputStream(path)) { byte[] b=new byte[65536];for(int n;(n=input.read(b))!=-1;)md.update(b,0,n); }
    StringBuilder s=new StringBuilder();for(byte b:md.digest())s.append(String.format("%02x",b));return s.toString();
  }
  static Map<Path,String> load(Path manifest) throws Exception {
    Map<Path,String> bound=new LinkedHashMap<>();
    for(String line:Files.readAllLines(manifest)) {
      if(line.isBlank()||line.startsWith("#"))continue;
      String[] fields=line.split(" ",2);check(fields.length==2&&fields[0].matches("[0-9a-f]{64}"),"invalid native manifest");
      Path path=Path.of(fields[1]);check(path.isAbsolute()&&!Files.isSymbolicLink(path)&&Files.isRegularFile(path),"regular absolute native path required");
      path=path.toRealPath();check(hash(path).equals(fields[0]),"native input hash mismatch: "+path);
      check(bound.put(path,fields[0])==null,"duplicate native input");
    }
    check(!bound.isEmpty(),"empty native input manifest");
    for(Path path:bound.keySet())System.load(path.toString());
    return bound;
  }
  static void basic() {
    Matrix transform=Matrix.getTranslateInstance(10,20,30), inverse=null;
    try {
      PointD result=transform.transform(new PointD(1,2,3),null);
      check(result.x==11&&result.y==22&&result.z==33,"real native Matrix transform");
      inverse=transform.createInverse();result=inverse.transform(result,null);
      check(Math.abs(result.x-1)<1e-12&&Math.abs(result.y-2)<1e-12&&Math.abs(result.z-3)<1e-12,"real native Matrix inverse");
    } catch(Exception error) {throw new AssertionError(error);} finally {if(inverse!=null)inverse.dispose();transform.dispose();}
    Point point=new Point(12.5,-4.25);Geometry parsed=null;
    try {
      check(point.getX()==12.5&&point.getY()==-4.25,"real native Point");
      ByteBuffer wkb=ByteBuffer.allocate(21).order(ByteOrder.LITTLE_ENDIAN);GeometryFactory.toWkb(point,wkb);
      check(wkb.position()==21,"native WKB byte count");wkb.flip();parsed=GeometryFactory.parseWkb(wkb);
      check(parsed instanceof Point&&((Point)parsed).getX()==12.5&&((Point)parsed).getY()==-4.25,"native WKB roundtrip");
    } finally {if(parsed!=null)parsed.dispose();point.dispose();}
    ProjectionFactory.setPreferLibrarySpi(true);
    Projection projection=ProjectionFactory.getProjection(4326);
    check(projection!=null&&projection.getClass().getName().equals("com.atakmap.map.projection.NativeProjection"),"native projection required, no Java fallback");
    PointD xy=projection.forward(new GeoPoint(-4.25,12.5),null);
    check(xy.x==12.5&&xy.y==-4.25,"native EPSG4326 forward");
    GeoPoint ll=projection.inverse(xy,null);check(ll.getLatitude()==-4.25&&ll.getLongitude()==12.5,"native EPSG4326 inverse");
    System.out.println("PASS_KERNEL_JNI_MATRIX_POINT_WKB_NATIVE_PROJECTION");
  }
  static void initializeStrict() throws Exception {
    PrintStream original=System.err;ByteArrayOutputStream errors=new ByteArrayOutputStream();
    PrintStream capture=new PrintStream(new OutputStream(){public void write(int b){original.write(b);errors.write(b);}},true,"UTF-8");
    try {System.setErr(capture);EngineLibrary.initialize();} finally {System.setErr(original);capture.flush();}
    String diagnostics=errors.toString("UTF-8");
    check(!diagnostics.contains("EngineLibrary: Failed to load native libraries"),"stock initializer swallowed failure");
    check(!diagnostics.contains("UnsatisfiedLinkError")&&!diagnostics.contains("NoClassDefFoundError"),"initializer linkage failure");
    check("1".equals(ConfigOptions.getOption("terrain.constrain-query-res",(String)null)),"initializer did not reach native default options");
    ConfigOptions.setOption("private-runtime-native-proof","exact-value");
    check("exact-value".equals(ConfigOptions.getOption("private-runtime-native-proof",(String)null)),"genuine JNI ConfigOptions roundtrip");
    check("fallback".equals(ConfigOptions.getOption("private-runtime-absent-option","fallback")),"ConfigOptions missing key");
    check(org.gdal.gdal.gdalJNI.isAvailable(),"real GDAL JNI unavailable");
    check("2.4.4".equals(org.gdal.gdal.gdal.VersionInfo("RELEASE_NAME")),"actual GDAL identity");
    System.out.println("PASS_ENGINE_INITIALIZER_AND_NATIVE_CONFIG_GDAL");
  }
  public static void main(String[] args) throws Exception {
    check(args.length==2&&(args[1].equals("basic")||args[1].equals("initialize")||args[1].equals("database")||args[1].equals("logger")),"usage: native-manifest basic|initialize|database|logger");
    Map<Path,String> nativeInputs=load(Path.of(args[0]));
    System.out.println("NATIVE_LOAD_COMPLETE");
    basic();if(args[1].equals("initialize"))initializeStrict();
    if(args[1].equals("database")) {
      NativeDatabaseCandidate.run(Path.of(System.getProperty("TAK_APP_DATA_PATH")));
      org.gdal.gdal.gdal.AllRegister();
      org.gdal.gdal.Dataset mem=org.gdal.gdal.gdal.GetDriverByName("MEM").Create("",3,2,1,org.gdal.gdalconst.gdalconstConstants.GDT_Byte);
      check(mem!=null,"actual GDAL MEM dataset");
      try {
        byte[] values={0,1,42,127,(byte)128,(byte)255},actual=new byte[6];
        check(mem.GetRasterBand(1).WriteRaster(0,0,3,2,values)==0,"GDAL native write");
        check(mem.GetRasterBand(1).ReadRaster(0,0,3,2,actual)==0&&Arrays.equals(values,actual),"GDAL exact native read");
      } finally {mem.delete();}
      System.out.println("PASS_REAL_GDAL_MEM_EXACT_WRITE_READ");
    }
    if(args[1].equals("logger"))KernelThrowingLoggerCandidate.run(Path.of(System.getProperty("TAK_APP_DATA_PATH")));
    Set<Path> mapped=new TreeSet<>();
    for(String line:Files.readAllLines(Path.of("/proc/self/maps"))) {
      String[] fields=line.trim().split("\\s+",6);
      if(fields.length==6&&fields[5].startsWith("/")) {
        Path path=Path.of(fields[5]);try(InputStream input=Files.newInputStream(path)) {
          if(Arrays.equals(input.readNBytes(4),new byte[]{127,69,76,70}))mapped.add(path.toRealPath());
        }
      }
    }
    for(Path path:mapped)System.out.println("ELF "+hash(path)+" "+path);
    for(Map.Entry<Path,String> entry:nativeInputs.entrySet()) {
      check(mapped.contains(entry.getKey()),"requested native provider absent from maps");check(hash(entry.getKey()).equals(entry.getValue()),"native provider changed");
    }
    System.out.println("PASS_SCOPED_KERNEL_NATIVE_CALLS_NO_RENDERER_OR_CLIENT_CLAIM");
  }
}
