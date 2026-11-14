// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import gov.tak.project.contour.ContourGrid;
import gov.tak.project.contour.ContourGrid.Line;
import gov.tak.project.contour.ContourGrid.Point;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CancellationException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BooleanSupplier;

public final class ContourGridControls {
    private static int checks;
    private static void check(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
        checks++;
    }
    private static List<Line> generate(double[] values, int width, int height, double interval) {
        return ContourGrid.generate(values, width, height, 10, 20, 12, 22, interval, 0, null, null);
    }
    private static void rejects(Runnable action, Class<? extends Throwable> type) {
        try { action.run(); } catch (Throwable error) { check(type.isInstance(error), "wrong failure: " + error); return; }
        throw new AssertionError("missing " + type);
    }
    public static void main(String[] args) {
        // Analytic planar surface z=longitude-10: every returned vertex must be
        // on the expected meridian, with one connected north/south path per level.
        int width = 17, height = 13;
        double[] plane = new double[width * height];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) plane[y * width + x] = 2.0 * x / (width - 1);
        List<Line> lines = generate(plane, width, height, .5);
        check(lines.size() == 4, "plane levels, minimum degeneracy excluded");
        double previous = -1;
        for (Line line : lines) {
            check(line.elevationMeters() > previous, "ascending levels"); previous = line.elevationMeters();
            check(line.points().size() >= height, "stitched across cells");
            for (Point p : line.points()) check(Math.abs(p.longitude() - 10 - line.elevationMeters()) < 1e-12, "analytic plane location");
            Point start = line.points().get(0), end = line.points().get(line.points().size() - 1);
            check(Math.abs(start.latitude() - end.latitude()) == 2, "full north/south coverage");
        }
        // A pyramid has one closed contour per interior level, contained in the grid.
        double[] hill = new double[25];
        for (int y = 0; y < 5; y++) for (int x = 0; x < 5; x++) hill[y * 5 + x] = 4 - Math.max(Math.abs(2 - x), Math.abs(2 - y));
        List<Line> rings = generate(hill, 5, 5, .5);
        check(rings.size() == 3, "pyramid interior rings");
        for (Line ring : rings) {
            check(ring.points().get(0).equals(ring.points().get(ring.points().size() - 1)), "closed ring");
            for (Point p : ring.points()) check(p.longitude() >= 10 && p.longitude() <= 12 && p.latitude() >= 20 && p.latitude() <= 22, "ring clipped to grid");
        }
        // Missing data removes whole cells and splits a formerly continuous path.
        double[] gap = plane.clone(); gap[6 * width + 8] = Double.NaN;
        List<Line> withGap = generate(gap, width, height, .5);
        check(withGap.stream().filter(line -> line.elevationMeters() == 1).count() == 2, "no-data splits path");
        check(generate(new double[]{Double.NaN, Double.NaN, Double.NaN, Double.NaN}, 2, 2, 1).isEmpty(), "all no-data");
        check(generate(new double[]{3, 3, 3, 3}, 2, 2, 1).isEmpty(), "flat surface");
        // Fixed NW/SE triangulation makes the saddle decision explicit and repeatable.
        double[] saddle = {1, -1, -1, 1};
        List<Line> saddleLines = generate(saddle, 2, 2, 2);
        check(saddleLines.size() == 2, "two saddle branches");
        check(saddleLines.equals(generate(saddle, 2, 2, 2)), "deterministic topology/order");
        for (Line line : saddleLines) check(line.points().size() == 2, "saddle branch endpoints");
        // A level-aligned ridge is emitted once, even when both sides touch it.
        List<Line> ridge = generate(new double[]{0, 1, 0, 0, 1, 0}, 3, 2, 1);
        check(ridge.size() == 1 && ridge.get(0).elevationMeters() == 1, "deduplicated ridge");
        // The result is deeply immutable and does not retain the caller's array.
        List<Line> stable = generate(plane, width, height, .5); plane[0] = 99;
        check(stable.equals(lines), "caller storage independent");
        rejects(() -> stable.add(stable.get(0)), UnsupportedOperationException.class);
        rejects(() -> stable.get(0).points().clear(), UnsupportedOperationException.class);
        // Invalid inputs and bounded work fail, with no partial result returned.
        rejects(() -> generate(new double[4], 1, 4, 1), IllegalArgumentException.class);
        rejects(() -> generate(new double[]{0, 1, 2, Double.POSITIVE_INFINITY}, 2, 2, 1), IllegalArgumentException.class);
        rejects(() -> generate(new double[]{0, 1, 2, 3}, 2, 2, 0), IllegalArgumentException.class);
        rejects(() -> generate(new double[]{0, 1, 2, 3}, 2, 2, .0001), IllegalArgumentException.class);
        rejects(() -> ContourGrid.generate(new double[4], 2, 2, 170, 0, -170, 1, 1, 0, null, null), IllegalArgumentException.class);
        rejects(() -> ContourGrid.generate(new double[]{-Double.MAX_VALUE, Double.MAX_VALUE, -Double.MAX_VALUE, Double.MAX_VALUE}, 2, 2, 0, 0, 1, 1, 1, 0, null, null), IllegalArgumentException.class);
        AtomicInteger calls = new AtomicInteger();
        BooleanSupplier cancel = () -> calls.incrementAndGet() > 3;
        rejects(() -> ContourGrid.generate(hill, 5, 5, 10, 20, 12, 22, .5, 0, cancel, null), CancellationException.class);
        RuntimeException primary = new RuntimeException("owned callback failure");
        boolean threwPrimary = false;
        try { ContourGrid.generate(hill, 5, 5, 10, 20, 12, 22, .5, 0, null, p -> { throw primary; }); }
        catch (RuntimeException error) { threwPrimary = true; check(error == primary, "primary callback identity"); }
        check(threwPrimary, "progress callback invoked");
        List<Integer> progress = new ArrayList<>();
        ContourGrid.generate(hill, 5, 5, 10, 20, 12, 22, .5, 0, null, progress::add);
        check(progress.get(0) == 0 && progress.get(progress.size() - 1) == 100, "progress endpoints");
        for (int i = 1; i < progress.size(); i++) check(progress.get(i) >= progress.get(i - 1), "monotonic progress");
        // Overflow-resistant interpolation across very large finite elevations.
        List<Line> huge = ContourGrid.generate(new double[]{-Double.MAX_VALUE, Double.MAX_VALUE, -Double.MAX_VALUE, Double.MAX_VALUE}, 2, 2, 0, 0, 1, 1, Double.MAX_VALUE, 0, null, null);
        Line zero = huge.stream().filter(line -> line.elevationMeters() == 0).findFirst().orElseThrow();
        for (Point p : zero.points()) check(p.longitude() == .5, "scaled interpolation midpoint");
        rejects(() -> ContourGrid.generate(new double[]{1e16-2, 1e16+2, 1e16-2, 1e16+2}, 2, 2, 0, 0, 1, 1, 1, 1e16, null, null), IllegalArgumentException.class);
        // Exhaust every ternary 2x2 grid, including exact-level vertices,
        // plateaus and saddles. Check against the explicit triangular surface.
        for (int pattern = 0; pattern < 81; pattern++) {
            int code = pattern;
            double[] samples = new double[4];
            for (int i = 0; i < 4; i++) { samples[i] = code % 3 - 1; code /= 3; }
            List<Line> contours = ContourGrid.generate(samples, 2, 2, 0, 0, 1, 1, 1, 0, null, null);
            for (Line line : contours) {
                check(line.points().size() >= 2, "non-degenerate path");
                Point prior = null;
                for (Point p : line.points()) {
                    check(Double.isFinite(p.longitude()) && Double.isFinite(p.latitude()) && p.longitude() >= 0 && p.longitude() <= 1 && p.latitude() >= 0 && p.latitude() <= 1, "finite bounded coordinates");
                    double x = p.longitude(), y = 1 - p.latitude();
                    double value = x >= y
                            ? samples[0] * (1 - x) + samples[1] * (x - y) + samples[3] * y
                            : samples[0] * (1 - y) + samples[2] * (y - x) + samples[3] * x;
                    check(Math.abs(value - line.elevationMeters()) < 1e-12, "analytic triangular isovalue");
                    check(!p.equals(prior), "no consecutive duplicate points"); prior = p;
                }
            }
        }
        System.out.println("contour-grid-controls passed checks=" + checks);
    }
}
