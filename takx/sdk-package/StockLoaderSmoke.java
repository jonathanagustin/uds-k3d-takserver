// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.map.EngineLibrary;
import java.io.*;
import java.lang.reflect.Method;
import java.nio.file.*;
import java.util.*;

/** Real EngineLibrary resource-loader control; no native preloads. */
public final class StockLoaderSmoke {
  public static void main(String[] args) throws Exception {
    Path jar=Path.of(args[0]).toRealPath();
    KernelRuntimeSmoke.check(Path.of(EngineLibrary.class.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath().equals(jar),"EngineLibrary must originate in assembled JAR");
    if(args[1].equals("missing")) {
      PrintStream old=System.err;ByteArrayOutputStream errors=new ByteArrayOutputStream();
      try {System.setErr(new PrintStream(errors,true,"UTF-8"));EngineLibrary.initialize();} finally {System.setErr(old);}
      String text=errors.toString("UTF-8");
      KernelRuntimeSmoke.check(text.contains("EngineLibrary: Failed to load native libraries")&&text.contains("Required public-source native resource: libGLdispatch.so"),"required missing resource must be reported");
      System.out.println("PASS_REAL_STOCK_LOADER_MISSING_REQUIRED_RESOURCE");
      // Intentional failed initialization has no JNI shutdown target. End this negative-only JVM.
      Runtime.getRuntime().halt(0);
    }
    KernelRuntimeSmoke.initializeStrict();KernelRuntimeSmoke.basic();
    RuntimeResourcesSmoke.run(jar,Path.of(args[3]));
    if(args[1].equals("database")) {
      DefaultIoReadonlySmoke.run(jar,Path.of(System.getProperty("TAK_APP_DATA_PATH")));
      NativeDatabaseCandidate.run(Path.of(System.getProperty("TAK_APP_DATA_PATH")));
      org.gdal.gdal.gdal.AllRegister();
      org.gdal.gdal.Dataset mem=org.gdal.gdal.gdal.GetDriverByName("MEM").Create("",3,2,1,org.gdal.gdalconst.gdalconstConstants.GDT_Byte);
      KernelRuntimeSmoke.check(mem!=null,"real GDAL MEM dataset");
      try {
        byte[] expected={0,1,42,127,(byte)128,(byte)255},actual=new byte[6];
        KernelRuntimeSmoke.check(mem.GetRasterBand(1).WriteRaster(0,0,3,2,expected)==0,"real GDAL write");
        KernelRuntimeSmoke.check(mem.GetRasterBand(1).ReadRaster(0,0,3,2,actual)==0&&Arrays.equals(actual,expected),"real GDAL read");
      } finally {mem.delete();}
      System.out.println("PASS_REAL_GDAL_MEM_EXACT_WRITE_READ");
    }
    if(args[1].equals("logger"))KernelThrowingLoggerCandidate.run(Path.of(System.getProperty("TAK_APP_DATA_PATH")));
    Method method=EngineLibrary.class.getDeclaredMethod("getRuntimeDirectory");method.setAccessible(true);
    Path extraction=((File)method.invoke(null)).toPath().resolve("lib/linux64").toRealPath();
    System.out.println("EXTRACTION_DIRECTORY "+extraction);
    for(String entry:Files.readAllLines(Path.of(args[2]))) {
      String[] fields=entry.split(" ",2);Path file=extraction.resolve(fields[1]);
      KernelRuntimeSmoke.check(Files.isRegularFile(file)&&!Files.isSymbolicLink(file)&&KernelRuntimeSmoke.hash(file).equals(fields[0]),"extracted real native bytes differ");
      System.out.println("PACKAGED_NATIVE "+fields[0]+" "+file.toRealPath());
    }
    Set<Path> maps=new TreeSet<>();
    for(String line:Files.readAllLines(Path.of("/proc/self/maps"))) {
      String[] fields=line.trim().split("\\s+",6);
      if(fields.length==6&&fields[5].startsWith("/")) {
        Path file=Path.of(fields[5]);try(InputStream in=Files.newInputStream(file)) {if(Arrays.equals(in.readNBytes(4),new byte[]{127,69,76,70}))maps.add(file.toRealPath());}
      }
    }
    for(Path file:maps)System.out.println("ELF "+KernelRuntimeSmoke.hash(file)+" "+file);
    System.out.println("PASS_STOCK_ENGINE_RESOURCE_LOADER_SCOPED_COMPONENT");
  }
}
