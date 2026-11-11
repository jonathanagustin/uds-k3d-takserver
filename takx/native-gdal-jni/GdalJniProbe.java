// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import org.gdal.gdal.*;
import org.gdal.osr.*;
import org.gdal.gdalconst.gdalconstConstants;
import java.nio.file.*;
import java.util.*;
public final class GdalJniProbe {
  static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
  public static void main(String[] args) throws Exception {
    check(gdalJNI.isAvailable(), "real JNI unavailable");
    check("2.4.4".equals(gdal.VersionInfo("RELEASE_NAME")), "GDAL version");
    gdal.AllRegister(); check(gdal.GetDriverCount()>0,"registered drivers");
    Dataset ds=gdal.GetDriverByName("MEM").Create("",3,2,1,gdalconstConstants.GDT_Byte);
    check(ds!=null,"MEM creation");
    byte[] values={0,1,42,127,(byte)128,(byte)255}, read=new byte[6];
    check(ds.GetRasterBand(1).WriteRaster(0,0,3,2,values)==0,"write");
    check(ds.GetRasterBand(1).ReadRaster(0,0,3,2,read)==0 && Arrays.equals(values,read),"exact read");
    check(ds.Interrupted()==0,"initial interrupt"); ds.Interrupt(); check(ds.Interrupted()!=0,"interrupt");
    ds.ClearInterrupt(); check(ds.Interrupted()==0,"clear interrupt");
    SpatialReference src=new SpatialReference(), dst=new SpatialReference();
    check(src.SetWellKnownGeogCS("WGS84")==0 && dst.ImportFromEPSG(3857)==0,"WGS84 references");
    CoordinateTransformation ct=new CoordinateTransformation(src,dst); double[] xy=ct.TransformPoint(1,1);
    check(Math.abs(xy[0]-111319.49079327357)<0.001 && Math.abs(xy[1]-111325.1428663851)<0.001,"WGS84 transform");
    ct.delete();src.delete();dst.delete();ds.delete();
    gdal.DontUseExceptions();gdal.PushErrorHandler("CPLQuietErrorHandler");gdal.ErrorReset();
    check(gdal.Open("/nonexistent-gdal-jni-proof-input-928374") == null,"missing file");
    check(gdal.GetLastErrorNo()!=0 && !gdal.GetLastErrorMsg().isEmpty(),"actual error");gdal.PopErrorHandler();
    for(String line:Files.readAllLines(Path.of("/proc/self/maps"))) {
      String[] fields=line.trim().split("\\s+",6);
      if(fields.length==6 && fields[5].startsWith("/")) {
        Path mapped=Path.of(fields[5]);
        try(java.io.InputStream input=Files.newInputStream(mapped)) {
          byte[] magic=input.readNBytes(4);
          if(Arrays.equals(magic,new byte[]{127,69,76,70})) System.out.println("ELF "+mapped.toRealPath());
        }
      }
    }
    System.out.println("GDAL_JNI_VERSION_REGISTER_MEM_EXACT_WGS84_INTERRUPT_MISSING_FILE=true");
  }
}
