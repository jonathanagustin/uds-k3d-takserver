// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.platform.symbology.milstd2525;

import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import gov.tak.api.engine.map.coords.IGeoPoint;

/** Explicit project policy public-viewport-fit-v1; not a recovered private SDK algorithm. */
public final class PublicViewportFit {
    private PublicViewportFit() {}
    public static final String POLICY = "public-viewport-fit-v1";
    private static final double A = 6378137.0;
    private static final double F = 1.0 / 298.257223563;
    private static final double E2 = F * (2.0 - F);

    /** Metres per pixel. An unrealized axis uses 256px independently; degenerate extent uses 1m/px. */
    public static double resolution(int width, int height, Collection<? extends IGeoPoint> points) {
        if (width < 0 || height < 0) throw new IllegalArgumentException("negative viewport dimension");
        if (points == null) throw new IllegalArgumentException("null points");
        ArrayList<Double> longitude = new ArrayList<>();
        double south = 90, north = -90;
        for (IGeoPoint point : points) {
            if (point == null) throw new IllegalArgumentException("null point");
            double lat = point.getLatitude(), lon = point.getLongitude();
            if (!Double.isFinite(lat) || !Double.isFinite(lon) || lat < -90 || lat > 90)
                throw new IllegalArgumentException("invalid geographic coordinate");
            double normalized = Math.IEEEremainder(lon, 360.0);
            longitude.add(normalized);
            south = Math.min(south, lat); north = Math.max(north, lat);
        }
        if (longitude.size() < 2) return 1.0;
        Collections.sort(longitude);
        double arc = longitude.get(longitude.size() - 1) - longitude.get(0);
        double gap = 360.0 - arc;
        for (int i = 1; i < longitude.size(); i++) {
            double candidate = longitude.get(i) - longitude.get(i - 1);
            if (candidate > gap) {
                gap = candidate;
                arc = (180.0 - longitude.get(i)) + (longitude.get(i - 1) + 180.0);
            }
        }
        double mid = Math.toRadians((south + north) / 2.0), sin = Math.sin(mid);
        // WGS84 parallel circumference at midpoint latitude: an explicit width approximation.
        double parallel = Math.abs((south + north) / 2.0) == 90.0 ? 0.0 : A * Math.cos(mid) / Math.sqrt(1.0 - E2 * sin * sin);
        double widthMetres = parallel * Math.toRadians(arc);
        double heightMetres = meridianDistance(south, north);
        double result = Math.max(widthMetres / (width == 0 ? 256.0 : width), heightMetres / (height == 0 ? 256.0 : height));
        return result > 0.0 ? result : 1.0;
    }

    /** Actual ellipsoid meridian geodesic length: Simpson integration of WGS84 meridional radius. */
    static double meridianDistance(double south, double north) {
        if (south == north) return 0;
        double first = Math.toRadians(south), step = (Math.toRadians(north) - first) / 1024.0;
        double sum = meridianRadius(first) + meridianRadius(Math.toRadians(north));
        for (int i = 1; i < 1024; i++) sum += (i % 2 == 0 ? 2.0 : 4.0) * meridianRadius(first + i * step);
        return sum * step / 3.0;
    }
    private static double meridianRadius(double latitude) {
        double sin = Math.sin(latitude), denominator = 1.0 - E2 * sin * sin;
        return A * (1.0 - E2) / (denominator * Math.sqrt(denominator));
    }
}
