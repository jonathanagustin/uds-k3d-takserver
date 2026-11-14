// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.project.contour;

import com.atakmap.map.layer.feature.AttributeSet;
import com.atakmap.map.layer.feature.Feature;
import com.atakmap.map.layer.feature.geometry.LineString;
import com.atakmap.map.layer.feature.style.BasicStrokeStyle;
import gov.tak.api.util.Disposable;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.CancellationException;
import java.util.function.BooleanSupplier;

/** Native public-Kernel contour features; no map renderer or client API shim. */
public final class ContourFeatures implements AutoCloseable {
    private final List<Feature> features;
    private boolean closed;
    private ContourFeatures(List<Feature> values) { features = List.copyOf(values); }

    /** Borrowed features remain owned by this batch and must not be disposed by callers. */
    public List<Feature> features() {
        if (closed) throw new IllegalStateException("contour feature batch is closed");
        return features;
    }

    /** Every Nth level relative to base is major, including zero and negative indices. */
    public static ContourFeatures create(List<ContourGrid.Line> lines, double intervalMeters,
            double baseMeters, int majorEvery, int minorColor, int majorColor,
            float minorWidth, float majorWidth, BooleanSupplier cancelled) {
        Objects.requireNonNull(lines, "lines");
        if (lines.size() > 4096 || !Double.isFinite(intervalMeters) || intervalMeters <= 0 ||
                !Double.isFinite(baseMeters) || majorEvery < 1 || majorEvery > 4096 ||
                !Float.isFinite(minorWidth) || !Float.isFinite(majorWidth) ||
                minorWidth <= 0 || majorWidth <= 0 || minorWidth > 64 || majorWidth > 64)
            throw new IllegalArgumentException("bounded levels and stroke configuration required");
        List<ContourGrid.Line> snapshot = List.copyOf(lines);
        long count = 0;
        for (var line : snapshot) {
            check(cancelled);
            levelIndex(line.elevationMeters(), intervalMeters, baseMeters);
            if (line.points().size() < 2 || (count += line.points().size()) > 1_000_000)
                throw new IllegalArgumentException("contour vertex bound differs");
            int index = 0;
            for (var point : line.points()) {
                if ((index++ & 1023) == 0) check(cancelled);
                if (!Double.isFinite(point.longitude()) || !Double.isFinite(point.latitude()) ||
                        point.longitude() < -180 || point.longitude() > 180 ||
                        point.latitude() < -90 || point.latitude() > 90)
                    throw new IllegalArgumentException("finite WGS84 contour vertices required");
            }
        }
        List<Feature> result = new ArrayList<>();
        try {
            for (var line : snapshot) {
                check(cancelled);
                long index = levelIndex(line.elevationMeters(), intervalMeters, baseMeters);
                boolean major = Math.floorMod(index, majorEvery) == 0;
                try (Owned temporary = new Owned()) {
                    LineString geometry = temporary.add(new LineString(2));
                    int vertex = 0;
                    for (var point : line.points()) {
                        if ((vertex++ & 1023) == 0) check(cancelled);
                        geometry.addPoint(point.longitude(), point.latitude());
                    }
                    BasicStrokeStyle style = temporary.add(new BasicStrokeStyle(major ? majorColor : minorColor,
                            major ? majorWidth : minorWidth, BasicStrokeStyle.EXTRUDE_NONE));
                    AttributeSet attributes = temporary.add(new AttributeSet());
                    attributes.setAttribute("elevation_hae_m", line.elevationMeters());
                    attributes.setAttribute("contour_class", major ? "major" : "minor");
                    attributes.setAttribute("level_index", index);
                    result.add(new Feature(Double.toString(line.elevationMeters()) + " m HAE", geometry, style, attributes));
                }
            }
            check(cancelled);
            return new ContourFeatures(result);
        } catch (RuntimeException | Error primary) {
            try { dispose(result); } catch (RuntimeException | Error cleanup) { if (primary != cleanup) primary.addSuppressed(cleanup); }
            throw primary;
        }
    }
    private static long levelIndex(double elevation, double interval, double base) {
        double raw = (elevation - base) / interval;
        double rounded = Math.rint(raw);
        if (!Double.isFinite(elevation) || !Double.isFinite(raw) || Math.abs(rounded) > 9_007_199_254_740_991d ||
                base + rounded * interval != elevation)
            throw new IllegalArgumentException("contour elevation is not on a representable configured level");
        return (long) rounded;
    }
    private static void check(BooleanSupplier cancelled) {
        if (Thread.currentThread().isInterrupted() || cancelled != null && cancelled.getAsBoolean())
            throw new CancellationException("contour feature conversion cancelled");
    }
    private static void dispose(List<? extends Disposable> values) {
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
    private static final class Owned implements AutoCloseable {
        final List<Disposable> values = new ArrayList<>();
        <T extends Disposable> T add(T value) { values.add(value); return value; }
        public void close() { dispose(values); }
    }
    @Override public void close() {
        if (closed) return;
        closed = true;
        dispose(features);
    }
}
