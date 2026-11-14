// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.project.contour;

import com.atakmap.coremap.maps.coords.GeoPoint;
import com.atakmap.map.elevation.ElevationManager;
import com.atakmap.map.elevation.ElevationSource;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CancellationException;
import java.util.function.BooleanSupplier;
import java.util.function.IntConsumer;

/** Project contour adapter using the actual public Kernel elevation registry. */
public final class ElevationContours {
    private ElevationContours() { }
    public record Result(List<ContourGrid.Line> lines, int sampledPoints, int totalPoints) {
        public Result { lines = List.copyOf(lines); }
        public boolean fullySampled() { return sampledPoints == totalPoints; }
        /** Clips geometry while retaining coverage counts from the original sampled grid. */
        public Result clipped(double west, double south, double east, double north,
                BooleanSupplier cancelled, IntConsumer progress) {
            return new Result(ContourClip.clip(lines, west, south, east, north, cancelled, progress), sampledPoints, totalPoints);
        }
    }

    /**
     * Samples a north-to-south, row-major WGS84 grid through an exact source type.
     * NaN means unavailable data; cells touching it are omitted by ContourGrid.
     * Cancellation or any callback/provider failure returns no partial result.
     * No source is attached, detached, disposed or changed by this adapter.
     */
    public static Result generate(String sourceType, int flags, int width, int height,
            double west, double south, double east, double north,
            double intervalMeters, double baseMeters,
            BooleanSupplier cancelled, IntConsumer progress) {
        if (sourceType == null || sourceType.isBlank() || sourceType.length() > 128 ||
                sourceType.indexOf('*') >= 0 || sourceType.indexOf('?') >= 0 || flags <= 0)
            throw new IllegalArgumentException("exact source type and positive flags required");
        if (width < 2 || height < 2 || width > 1025 || height > 1025 ||
                (long) (width - 1) * (height - 1) > 262_144)
            throw new IllegalArgumentException("grid dimensions exceed the contract");
        if (!Double.isFinite(west) || !Double.isFinite(east) || !Double.isFinite(south) ||
                !Double.isFinite(north) || west < -180 || east > 180 || south < -90 || north > 90 ||
                west >= east || south >= north || !Double.isFinite(intervalMeters) ||
                intervalMeters <= 0 || !Double.isFinite(baseMeters))
            throw new IllegalArgumentException("finite non-wrapping WGS84 bounds and interval required");
        check(cancelled);
        report(progress, 0);
        check(cancelled);
        double[] samples = new double[width * height];
        Arrays.fill(samples, Double.NaN);
        ElevationSource.QueryParameters query = new ElevationSource.QueryParameters();
        query.types = Set.of(sourceType);
        query.flags = flags;
        int sampled = 0;
        for (int row = 0; row < height; row++) {
            check(cancelled);
            List<GeoPoint> points = new ArrayList<>(width);
            double latitude = north - (north - south) * row / (height - 1);
            for (int column = 0; column < width; column++)
                points.add(new GeoPoint(latitude, west + (east - west) * column / (width - 1)));
            double[] values = new double[width];
            Arrays.fill(values, Double.NaN);
            ElevationManager.getElevation(points.iterator(), values, query);
            check(cancelled);
            for (int column = 0; column < width; column++) {
                if (Double.isInfinite(values[column])) throw new IllegalArgumentException("infinite elevation sample");
                samples[row * width + column] = values[column];
                if (Double.isFinite(values[column])) sampled++;
            }
            report(progress, (row + 1) * 50 / height);
        }
        check(cancelled);
        List<ContourGrid.Line> lines = ContourGrid.generate(samples, width, height,
                west, south, east, north, intervalMeters, baseMeters, cancelled,
                value -> report(progress, 50 + value / 2));
        check(cancelled);
        return new Result(lines, sampled, samples.length);
    }
    private static void check(BooleanSupplier cancelled) {
        if (Thread.currentThread().isInterrupted() || cancelled != null && cancelled.getAsBoolean())
            throw new CancellationException("contour elevation sampling cancelled");
    }
    private static void report(IntConsumer progress, int percent) {
        if (progress != null) progress.accept(percent);
    }
}
