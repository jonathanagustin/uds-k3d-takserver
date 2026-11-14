// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.project.contour;

import com.atakmap.map.layer.feature.*;
import com.atakmap.map.layer.feature.datastore.FeatureSetDatabase2;
import gov.tak.api.util.Disposable;
import java.io.IOException;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/** Owns a fresh contour datastore and its actual public Kernel feature layer. */
public final class ContourLayer implements AutoCloseable {
    private final FeatureSetDatabase2 store;
    private final FeatureLayer3 layer;
    private final long featureSetId;
    private boolean closed;
    private ContourLayer(FeatureSetDatabase2 store, FeatureLayer3 layer, long id) {
        this.store = store; this.layer = layer; featureSetId = id;
    }

    /**
     * Copies the borrowed batch into a new private POSIX database file. Existing
     * files and symlink ancestors refuse. Failure retains the new file for diagnosis.
     * The batch stays caller-owned. Use this wrapper only on its owning thread.
     */
    public static ContourLayer create(String name, Path database, ContourFeatures batch)
            throws IOException, DataStoreException {
        if (name == null || name.isBlank() || name.length() > 128)
            throw new IllegalArgumentException("bounded layer name required");
        Objects.requireNonNull(database, "database");
        List<Feature> features = Objects.requireNonNull(batch, "batch").features();
        Path file = database.toAbsolutePath().normalize();
        for (Path path = file; path != null; path = path.getParent())
            if (Files.isSymbolicLink(path)) throw new IllegalArgumentException("symlink database path refused");
        if (file.getParent() == null || !Files.isDirectory(file.getParent()))
            throw new IllegalArgumentException("existing database parent required");
        Files.createFile(file, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        FeatureSetDatabase2 store = null;
        try {
            store = new FeatureSetDatabase2(file.toFile());
            long id = store.insertFeatureSet(new FeatureSet("project-contours", "contours", name, Double.MAX_VALUE, 0));
            for (Feature original : features) {
                try (Owned temporary = new Owned()) {
                    var geometry = temporary.add(original.getGeometry());
                    var style = temporary.add(original.getStyle());
                    var attributes = temporary.add(original.getAttributes());
                    Feature copy = temporary.add(new Feature(id, original.getName(), geometry, style, attributes));
                    store.insertFeature(copy);
                }
            }
            return new ContourLayer(store, new FeatureLayer3(name, store), id);
        } catch (DataStoreException | RuntimeException | Error primary) {
            if (store != null) {
                try { store.dispose(); }
                catch (RuntimeException | Error cleanup) { if (cleanup != primary) primary.addSuppressed(cleanup); }
            }
            throw primary;
        }
    }
    /** Borrowed layer/store references must not be used after this owner closes. */
    public FeatureLayer3 layer() {
        if (closed) throw new IllegalStateException("contour layer is closed");
        return layer;
    }
    public long featureSetId() {
        if (closed) throw new IllegalStateException("contour layer is closed");
        return featureSetId;
    }
    @Override public void close() {
        if (closed) return;
        closed = true;
        store.dispose();
    }
    private static final class Owned implements AutoCloseable {
        final List<Disposable> values = new ArrayList<>();
        <T extends Disposable> T add(T value) { values.add(value); return value; }
        public void close() {
            Throwable first = null;
            for (int i = values.size() - 1; i >= 0; i--) {
                try { values.get(i).dispose(); }
                catch (RuntimeException | Error error) {
                    if (first == null) first = error; else if (first != error) first.addSuppressed(error);
                }
            }
            if (first instanceof RuntimeException error) throw error;
            if (first instanceof Error error) throw error;
        }
    }
}
