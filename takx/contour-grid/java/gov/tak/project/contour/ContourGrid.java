// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.project.contour;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.CancellationException;
import java.util.function.BooleanSupplier;
import java.util.function.IntConsumer;

/** Bounded piecewise-linear contours of a caller-owned WGS84 elevation grid. */
public final class ContourGrid {
    private ContourGrid() { }
    public record Point(double longitude, double latitude) { }
    public record Line(double elevationMeters, List<Point> points) {
        public Line { points = List.copyOf(points); }
    }
    private static final long MAX_WORK = 4_000_000;
    private static final int MAX_POINTS = 1_000_000;

    /**
     * Samples are row-major, north to south, including all four bounding edges.
     * A cell containing any NaN is omitted. Infinity is invalid. Each valid cell
     * is split northwest to southeast; this explicit project interpolation policy
     * does not claim to reproduce GDAL's bilinear saddle policy or a private SDK.
     * Equal vertices belong to the upper side of a level. No partial result is
     * returned on cancellation or on a callback failure.
     */
    public static List<Line> generate(double[] samples, int width, int height,
            double west, double south, double east, double north,
            double intervalMeters, double baseMeters,
            BooleanSupplier cancelled, IntConsumer progress) {
        Objects.requireNonNull(samples, "samples");
        if (width < 2 || height < 2 || width > 1025 || height > 1025 ||
                (long) width * height != samples.length ||
                (long) (width - 1) * (height - 1) > 262_144)
            throw new IllegalArgumentException("grid dimensions exceed the contract");
        if (!Double.isFinite(west) || !Double.isFinite(east) ||
                !Double.isFinite(south) || !Double.isFinite(north) ||
                west < -180 || east > 180 || south < -90 || north > 90 ||
                west >= east || south >= north)
            throw new IllegalArgumentException("finite non-wrapping WGS84 bounds required");
        if (!Double.isFinite(intervalMeters) || intervalMeters <= 0 ||
                !Double.isFinite(baseMeters))
            throw new IllegalArgumentException("finite positive interval and finite base required");
        double[] values = samples.clone();
        double min = Double.POSITIVE_INFINITY, max = Double.NEGATIVE_INFINITY;
        for (double value : values) {
            if (Double.isInfinite(value)) throw new IllegalArgumentException("infinite sample");
            if (Double.isFinite(value)) { min = Math.min(min, value); max = Math.max(max, value); }
        }
        check(cancelled);
        if (min == Double.POSITIVE_INFINITY || min == max) {
            report(progress, 100);
            return List.of();
        }
        double first = Math.ceil((min - baseMeters) / intervalMeters);
        double last = Math.floor((max - baseMeters) / intervalMeters);
        // Indices must have exact integral representation, and multiplication
        // below must remain finite. Refuse excessive work before publishing progress.
        if (!Double.isFinite(first) || !Double.isFinite(last) ||
                Math.abs(first) > 9_007_199_254_740_991d || Math.abs(last) > 9_007_199_254_740_991d ||
                last - first + 1 > 4096 ||
                Math.max(0, last - first + 1) * (width - 1L) * (height - 1L) > MAX_WORK)
            throw new IllegalArgumentException("contour level/work bound exceeded");
        List<Line> result = new ArrayList<>();
        long count = Math.max(0, (long) last - (long) first + 1);
        int emitted = 0;
        report(progress, 0);
        double previousLevel = Double.NEGATIVE_INFINITY;
        for (long offset = 0; offset < count; offset++) {
            check(cancelled);
            double level = baseMeters + ((long) first + offset) * intervalMeters;
            if (!Double.isFinite(level) || (offset > 0 && level <= previousLevel))
                throw new IllegalArgumentException("level overflow or interval below numeric resolution");
            previousLevel = level;
            Map<Long, Node> nodes = new LinkedHashMap<>();
            for (int row = 0; row < height - 1; row++) {
                check(cancelled);
                for (int column = 0; column < width - 1; column++) {
                    int a = row * width + column, b = a + 1, d = a + width, c = d + 1;
                    if (Double.isNaN(values[a]) || Double.isNaN(values[b]) ||
                            Double.isNaN(values[c]) || Double.isNaN(values[d])) continue;
                    triangle(nodes, a, b, c, values, width, height, west, south, east, north, level);
                    triangle(nodes, a, c, d, values, width, height, west, south, east, north, level);
                    if (nodes.size() > MAX_POINTS) throw new IllegalArgumentException("contour vertex bound exceeded");
                }
            }
            // Open paths first, then closed rings. Shared grid edges, rather
            // than floating point coordinate equality, establish connectivity.
            Set<List<Point>> unique = new HashSet<>();
            for (int pass = 0; pass < 2; pass++) {
                for (Node start : nodes.values()) {
                    if (start.visited || (pass == 0 && start.neighbors.size() != 1)) continue;
                    check(cancelled);
                    List<Point> points = walk(start, cancelled);
                    if (points.size() < 2) continue;
                    List<Point> reversed = new ArrayList<>(points);
                    java.util.Collections.reverse(reversed);
                    if (unique.contains(points) || unique.contains(reversed)) continue;
                    unique.add(points);
                    emitted += points.size();
                    if (emitted > MAX_POINTS) throw new IllegalArgumentException("result vertex bound exceeded");
                    result.add(new Line(level, points));
                }
            }
            report(progress, (int) ((offset + 1) * 100 / count));
        }
        check(cancelled);
        if (count == 0) report(progress, 100);
        return List.copyOf(result);
    }

    private static final class Node {
        final Point point;
        final List<Node> neighbors = new ArrayList<>(2);
        boolean visited;
        Node(Point point) { this.point = point; }
    }

    private static void triangle(Map<Long, Node> nodes, int a, int b, int c,
            double[] values, int width, int height, double west, double south,
            double east, double north, double level) {
        int[] ids = { a, b, c, a };
        Node first = null, second = null;
        for (int i = 0; i < 3; i++) {
            int left = ids[i], right = ids[i + 1];
            if ((values[left] >= level) == (values[right] >= level)) continue;
            int low = Math.min(left, right), high = Math.max(left, right);
            long key = ((long) low << 32) | (high & 0xffffffffL);
            Node node = nodes.get(key);
            if (node == null) {
                double numerator = level - values[low], denominator = values[high] - values[low];
                double t = numerator / denominator;
                // Avoid overflow in value subtraction by using a scaled ratio.
                if (!Double.isFinite(numerator) || !Double.isFinite(denominator) || !Double.isFinite(t)) {
                    double scale = Math.max(Math.abs(values[low]), Math.max(Math.abs(values[high]), Math.abs(level)));
                    t = (level / scale - values[low] / scale) / (values[high] / scale - values[low] / scale);
                }
                if (!Double.isFinite(t) || t < 0 || t > 1) throw new IllegalArgumentException("interpolation overflow");
                double x = (low % width) + t * ((high % width) - (low % width));
                double y = (low / width) + t * ((high / width) - (low / width));
                node = new Node(new Point(west + (east - west) * x / (width - 1),
                        north - (north - south) * y / (height - 1)));
                nodes.put(key, node);
            }
            if (first == null) first = node; else second = node;
        }
        if (first == null) return;
        if (second == null || first == second) throw new IllegalStateException("invalid triangle crossing");
        first.neighbors.add(second); second.neighbors.add(first);
        if (first.neighbors.size() > 2 || second.neighbors.size() > 2)
            throw new IllegalStateException("non-manifold grid edge");
    }

    private static List<Point> walk(Node start, BooleanSupplier cancelled) {
        List<Point> points = new ArrayList<>();
        Node previous = null, current = start;
        while (!current.visited) {
            check(cancelled);
            current.visited = true;
            append(points, current.point);
            Node next = null;
            for (Node candidate : current.neighbors) if (candidate != previous) { next = candidate; break; }
            if (next == null) break;
            previous = current; current = next;
            if (current == start) { append(points, start.point); break; }
        }
        return List.copyOf(points);
    }
    private static void append(List<Point> points, Point point) {
        if (points.isEmpty() || !points.get(points.size() - 1).equals(point)) points.add(point);
    }
    private static void check(BooleanSupplier cancelled) {
        if (cancelled != null && cancelled.getAsBoolean()) throw new CancellationException("contour generation cancelled");
    }
    private static void report(IntConsumer progress, int value) { if (progress != null) progress.accept(value); }
}
