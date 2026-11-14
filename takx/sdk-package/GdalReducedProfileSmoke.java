// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import java.nio.file.*;
import java.util.Objects;
import org.gdal.gdal.gdal;
import com.atakmap.map.gdal.GdalLibrary;
/** Real provider registry and public initializer; no warning handler/filter. */
public final class GdalReducedProfileSmoke {
  public static void main(String[] args) throws Exception {
    StockLoaderSmoke.main(args);
    Path component=Path.of(args[0]).toRealPath();
    KernelRuntimeSmoke.check(Path.of(GdalLibrary.class.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath().equals(component),"genuine rebuilt family must be in single component");
    gdal.AllRegister();
    KernelRuntimeSmoke.check(gdal.GetDriverByName("MBTiles")==null&&gdal.GetDriverByName("GPKG")==null,"both drivers actually compiled out in locked native profile");
    String before=gdal.GetConfigOption("GDAL_SKIP",null);
    KernelRuntimeSmoke.check(before==null||before.isEmpty(),"fresh owned consumer has no caller skip override");
    KernelRuntimeSmoke.check(GdalLibrary.init(),"real Kernel GDAL initializer succeeds");
    KernelRuntimeSmoke.check(Objects.equals(before,gdal.GetConfigOption("GDAL_SKIP",null)),"reduced profile does not inject skip names or alter caller configuration");
    KernelRuntimeSmoke.check(gdal.GetDriverByName("MBTiles")==null&&gdal.GetDriverByName("GPKG")==null,"real initializer does not invent native drivers");
    KernelRuntimeSmoke.check(gdal.GetDriverByName("GTiff")!=null&&gdal.GetDriverByName("MEM")!=null,"genuine remaining raster drivers retained");
    java.util.Set<Path> mapped=new java.util.TreeSet<>();
    for(String line:Files.readAllLines(Path.of("/proc/self/maps"))) {
      String[] fields=line.trim().split("\\s+",6);
      if(fields.length==6&&fields[5].startsWith("/")) {
        Path path=Path.of(fields[5]).toRealPath();
        try(java.io.InputStream stream=Files.newInputStream(path)) {
          if(java.util.Arrays.equals(stream.readNBytes(4),new byte[]{127,69,76,70}))mapped.add(path);
        }
      }
    }
    KernelRuntimeSmoke.check(mapped.stream().anyMatch(path -> path.getFileName().toString().equals("libgdal.so")) && mapped.stream().anyMatch(path -> path.getFileName().toString().equals("libgdalalljni.so")),"actual post-init GDAL/JNI ELF maps present");
    for(Path path:mapped)System.out.println("ELF "+KernelRuntimeSmoke.hash(path)+" "+path);
    System.out.println("PASS_REAL_REDUCED_PROFILE_GDAL_SKIP_INIT_REGISTRY_NO_SUPPRESSION");
  }
}
