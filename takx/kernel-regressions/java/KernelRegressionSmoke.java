// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.map.EngineLibrary;
import java.io.InputStream;
import java.nio.file.*;
import java.util.*;

/** Uses the real packaged EngineLibrary resource loader, not native preloads. */
public final class KernelRegressionSmoke {
    public static void main(String[] args) throws Exception {
        KernelRuntimeSmoke.check(args.length == 3, "usage: genuine-component.jar fixture-root category");
        Path component = Path.of(args[0]).toRealPath();
        for (Class<?> type : List.of(EngineLibrary.class,
                com.atakmap.map.formats.dted.DtedElevationSource.class,
                com.atakmap.map.gpkg.GeoPackage.class,
                com.atakmap.map.layer.raster.gpkg.GeoPackageTileContainer.class,
                com.atakmap.map.layer.raster.mbtiles.MBTilesContainer.class,
                com.atakmap.map.gdal.GdalElevationChunk.class,
                com.atakmap.map.layer.model.obj.ObjModelSpi.class,
                com.atakmap.map.layer.feature.ogr.OgrFeatureDataSource.class))
            KernelRuntimeSmoke.check(Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath().equals(component),
                "regression consumer must originate in the genuine SDK component: " + type.getName());
        KernelRuntimeSmoke.initializeStrict();
        KernelRuntimeSmoke.basic();
        KernelFormatRegressions.run(Path.of(args[1]), args[2]);
        Set<Path> mapped = new TreeSet<>();
        for (String line : Files.readAllLines(Path.of("/proc/self/maps"))) {
            String[] fields = line.trim().split("\\s+", 6);
            if (fields.length != 6 || !fields[5].startsWith("/")) continue;
            Path path = Path.of(fields[5]).toRealPath();
            try (InputStream input = Files.newInputStream(path)) {
                if (Arrays.equals(input.readNBytes(4), new byte[]{127, 69, 76, 70})) mapped.add(path);
            }
        }
        for (Path path : mapped) System.out.println("ELF " + KernelRuntimeSmoke.hash(path) + " " + path);
        System.out.println("PASS_REAL_KERNEL_FORMAT_REGRESSIONS_NO_RENDERER_OR_FULL_CLIENT_CLAIM");
    }
}
