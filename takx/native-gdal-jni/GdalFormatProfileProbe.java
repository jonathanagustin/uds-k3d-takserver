// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import org.gdal.gdal.gdal;
import org.gdal.ogr.DataSource;
import org.gdal.ogr.Feature;
import org.gdal.ogr.Geometry;
import org.gdal.ogr.Layer;
import org.gdal.ogr.ogr;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;

/** Actual modified GDAL JNI, real KML reader and original-Throwable controls. */
public final class GdalFormatProfileProbe {
    public static void main(String[] args) throws Exception {
        GdalJniProbe.main(new String[0]);
        ogr.RegisterAll();
        if (ogr.GetDriverByName("KML") == null || ogr.GetDriverByName("LIBKML") == null)
            throw new AssertionError("both genuine compiled KML drivers must register");
        String path = "/vsimem/uds-gdal-format-profile.kml";
        String fixture = "<kml xmlns=\"http://www.opengis.net/kml/2.2\"><Document><Placemark>"
            + "<name>Owned point</name><Point><coordinates>-77,36,125</coordinates></Point>"
            + "</Placemark></Document></kml>";
        gdal.FileFromMemBuffer(path, fixture.getBytes(StandardCharsets.UTF_8));
        try {
            DataSource data = ogr.Open(path, 0);
            if (data == null) throw new AssertionError("genuine KML file must open");
            try {
                Layer layer = data.GetLayer(0);
                if (layer == null) throw new AssertionError("actual KML layer required");
                Feature feature = layer.GetNextFeature();
                if (feature == null) throw new AssertionError("actual KML feature required");
                try {
                    Geometry geometry = feature.GetGeometryRef();
                    if (geometry == null || geometry.GetX() != -77 || geometry.GetY() != 36 || geometry.GetZ() != 125)
                        throw new AssertionError("KML coordinates must preserve independent authored oracle");
                } finally { feature.delete(); }
                Feature extra = layer.GetNextFeature();
                if (extra != null) { extra.delete(); throw new AssertionError("unexpected KML feature"); }
            } finally { data.delete(); }
        } finally { gdal.Unlink(path); }
        GdalExceptionControls.run();
        for (String line : Files.readAllLines(Path.of("/proc/self/maps"))) {
            String[] fields = line.trim().split("\\s+", 6);
            if (fields.length != 6 || !fields[5].startsWith("/")) continue;
            Path mapped = Path.of(fields[5]).toRealPath();
            try (java.io.InputStream stream = Files.newInputStream(mapped)) {
                if (Arrays.equals(stream.readNBytes(4), new byte[]{127,69,76,70}))
                    System.out.println("ELF " + mapped);
            }
        }
        System.out.println("PASS_GDAL_KML_DRIVERS_COORDINATES_ORIGINAL_THROWABLES");
    }
}
