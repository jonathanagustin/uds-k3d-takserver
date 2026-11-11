// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Adapted from the public ATAK tests identified in upstream.lock.json.
import com.atakmap.database.DatabaseIface;
import com.atakmap.database.Databases;
import com.atakmap.map.elevation.ElevationSource;
import com.atakmap.map.formats.dted.DtedElevationSource;
import com.atakmap.map.gpkg.GeoPackage;
import com.atakmap.map.gpkg.TileTable;
import com.atakmap.map.gpkg.extensions.GriddedCoverage;
import com.atakmap.map.layer.control.Controls;
import com.atakmap.map.layer.raster.controls.TileMetadataControl;
import com.atakmap.map.layer.raster.controls.TilesMetadataControl;
import com.atakmap.map.layer.raster.gpkg.GeoPackageTileContainer;
import com.atakmap.map.layer.raster.mbtiles.MBTilesContainer;
import com.atakmap.map.layer.raster.tilematrix.TileContainer;
import gov.tak.api.util.Disposable;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Real SDK/JNI format regressions. No fake SDK types, parser or native loader. */
public final class KernelFormatRegressions {
    private static int assertions;
    private static void check(boolean condition, String message) {
        assertions++;
        if (!condition) throw new AssertionError(message);
    }
    public static void run(Path root) throws Exception {
        check(root.isAbsolute() && !Files.isSymbolicLink(root), "owned absolute fixture root");
        Files.createDirectory(root);
        dted(root.resolve("dted"), ElevationSource.QueryParameters.Order.ResolutionAsc);
        dted(root.resolve("dted-reverse"), ElevationSource.QueryParameters.Order.ResolutionDesc);
        mbtiles(root.resolve("roundtrip.mbtiles"));
        griddedCoverage(root.resolve("terrain.gpkg"));
        System.out.println("PASS_UPSTREAM_DTED_DISCOVERY_MBTILES_ROUNDTRIP_GPKG_FLOAT_COVERAGE assertions=" + assertions);
    }
    private static void dted(Path directory, ElevationSource.QueryParameters.Order order) throws Exception {
        Files.createDirectories(directory.resolve("w077"));
        Set<String> remaining = new HashSet<>(Arrays.asList(".dt0", ".dt1", ".dt2", ".dt3"));
        for (String suffix : remaining) Files.createFile(directory.resolve("w077/n35" + suffix));
        // These intentionally empty files test upstream discovery only, not DTED decoding.
        ElevationSource source = DtedElevationSource.create(directory.toString());
        check(source != null, "real native DTED source");
        try {
            ElevationSource.QueryParameters parameters = new ElevationSource.QueryParameters();
            parameters.order = Collections.singletonList(order);
            Set<String> observed = new HashSet<>();
            try (ElevationSource.Cursor cursor = source.query(parameters)) {
                while (cursor.moveToNext()) {
                    String uri = cursor.getUri();
                    check(observed.add(uri), "DTED discovery returns each URI once");
                    for (String suffix : new ArrayList<>(remaining)) {
                        if (uri.endsWith(suffix)) { remaining.remove(suffix); break; }
                    }
                }
            }
            check(remaining.isEmpty() && observed.size() == 4, "all four DTED levels discovered in " + order);
        } finally {
            // The public factory returns a native implementation of the actual Disposable API.
            if (source instanceof Disposable) ((Disposable)source).dispose();
        }
    }
    private static void mbtiles(Path path) {
        TileContainer container = MBTilesContainer.SPI.create("upstream-regression", path.toString(), null);
        check(container != null, "default MBTiles SPI creates a genuine database");
        int[][] coordinates = {{0,0,0}, {1,0,0}, {2,1,0}, {3,2,0}, {3,2,1}, {3,3,0}, {3,3,1}};
        Map<String,byte[]> expected = new LinkedHashMap<>();
        try {
            check(!container.isReadOnly(), "created MBTiles writable");
            for (int[] coordinate : coordinates) {
                byte[] bytes = ("insert " + Arrays.toString(coordinate)).getBytes(StandardCharsets.UTF_8);
                container.setTile(coordinate[0], coordinate[1], coordinate[2], bytes, -1L);
                expected.put(Arrays.toString(coordinate), bytes);
            }
            verifyTiles(container, coordinates, expected);
        } finally { container.dispose(); }
        check(Files.isRegularFile(path), "MBTiles file exists after close");
        DatabaseIface database = Databases.openDatabase(path.toString(), true);
        try { check(MBTilesContainer.isCompatibleSchema(database), "real native SQLite MBTiles schema"); }
        finally { database.close(); }
        container = MBTilesContainer.SPI.open(path.toString(), null, false);
        check(container != null, "MBTiles reopens through real SPI");
        try {
            verifyTiles(container, coordinates, expected);
            for (int[] coordinate : new int[][] {coordinates[2], coordinates[3]}) {
                byte[] bytes = ("update " + Arrays.toString(coordinate)).getBytes(StandardCharsets.UTF_8);
                container.setTile(coordinate[0], coordinate[1], coordinate[2], bytes, -1L);
                expected.put(Arrays.toString(coordinate), bytes);
            }
        } finally { container.dispose(); }
        container = MBTilesContainer.SPI.open(path.toString(), null, true);
        check(container != null && container.isReadOnly(), "updated MBTiles read-only reopen");
        try { verifyTiles(container, coordinates, expected); }
        finally { container.dispose(); }
    }
    private static void verifyTiles(TileContainer container, int[][] coordinates, Map<String,byte[]> expected) {
        for (int[] coordinate : coordinates) {
            byte[] actual = container.getTileData(coordinate[0], coordinate[1], coordinate[2], null);
            check(Arrays.equals(expected.get(Arrays.toString(coordinate)), actual), "native MBTiles byte roundtrip");
        }
    }
    private static void griddedCoverage(Path path) throws Exception {
        final int width = 256, height = 256;
        double[] expected = new double[width * height];
        Arrays.fill(expected, 128d);
        GeoPackage database = GeoPackage.createNewGeoPackage(path.toFile());
        try {
            GriddedCoverage coverage = new GriddedCoverage();
            coverage.tile_matrix_set_name = "open_existing_griddedcoverage";
            coverage.datatype = "float";
            coverage.data_null_value = -999999.0;
            GriddedCoverage.insertGriddedCoverage(database, coverage, 4979, 0, 0, null);
            coverage = GriddedCoverage.getPackageExtension(database, coverage.tile_matrix_set_name);
            TileTable.ZoomLevelRow zoom = database.getTileTable(coverage.tile_matrix_set_name).getInfoForZoomLevel(0);
            check(zoom.tile_width == width && zoom.tile_height == height, "GeoPackage actual tile dimensions");
            coverage.insertTile(0, 0, 0, expected, -100d, 2d);
        } finally { database.close(); }
        TileContainer container = GeoPackageTileContainer.SPI.open(path.toString(), null, true);
        check(container != null && container instanceof Controls, "real GeoPackage tile container controls");
        try {
            Controls controls = (Controls)container;
            GriddedCoverage coverage = controls.getControl(GriddedCoverage.class);
            TilesMetadataControl metadata = controls.getControl(TilesMetadataControl.class);
            TileMetadataControl tileMetadata = controls.getControl(TileMetadataControl.class);
            check(coverage != null && metadata != null && tileMetadata != null, "actual coverage metadata controls");
            check("terrain".equals(metadata.getMetadata().get("content")), "GeoPackage terrain metadata");
            GriddedCoverage.TileData encoded = new GriddedCoverage.TileData();
            encoded.data = container.getTileData(0, 0, 0, null);
            check(encoded.data != null, "native encoded float coverage tile");
            Map<String,Object> values = tileMetadata.getTileMetadata(0, 0, 0);
            check(values != null, "GeoPackage tile offset/scale metadata");
            encoded.offset = (Double)values.get("offset");
            encoded.scale = (Double)values.get("scale");
            check(encoded.offset == -100d && encoded.scale == 2d, "persisted nondefault offset and scale");
            double[] actual = coverage.decodeTile(0, 0, 0, encoded);
            check(actual != null && actual.length == expected.length, "actual decoded float coverage size");
            for (int index = 0; index < expected.length; index++)
                check(Math.abs(actual[index] - expected[index]) <= 0.001d, "GeoPackage gridded elevation sample " + index);
        } finally { container.dispose(); }
    }
}
