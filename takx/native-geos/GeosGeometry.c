/* Copyright 2026 uds-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only */
#include <geos_c.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int errors;
static void notice(const char *fmt, ...) { (void)fmt; }
static void error(const char *fmt, ...) { (void)fmt; errors++; }
static void require(int ok) { if (!ok) exit(2); }
int main(void) {
    GEOSContextHandle_t ctx = initGEOS_r(notice, error);
    require(ctx != NULL && strcmp(GEOSversion(), "3.4.3-CAPI-1.8.3 r4285") == 0);
    GEOSGeometry *a = GEOSGeomFromWKT_r(ctx, "POLYGON((0 0,4 0,4 4,0 4,0 0))");
    GEOSGeometry *b = GEOSGeomFromWKT_r(ctx, "POLYGON((2 2,6 2,6 6,2 6,2 2))");
    GEOSGeometry *p = GEOSGeomFromWKT_r(ctx, "POINT(7 4)");
    require(a && b && p);
    GEOSGeometry *intersection = GEOSIntersection_r(ctx, a, b);
    GEOSGeometry *buffer = GEOSBuffer_r(ctx, p, 2, 32);
    double area = 0, distance = 0, buffered = 0;
    require(intersection && buffer && GEOSArea_r(ctx, intersection, &area) && fabs(area-4) < 1e-12);
    require(GEOSDistance_r(ctx, a, p, &distance) && fabs(distance-3) < 1e-12);
    require(GEOSisValid_r(ctx, buffer) == 1 && GEOSArea_r(ctx, buffer, &buffered));
    require(fabs(buffered-4*acos(-1.0)) < 0.01 && errors == 0);
    GEOSGeometry *bad = GEOSGeomFromWKT_r(ctx, "POINT(broken)");
    require(!bad && errors > 0);
    GEOSGeom_destroy_r(ctx, intersection); GEOSGeom_destroy_r(ctx, buffer);
    GEOSGeom_destroy_r(ctx, a); GEOSGeom_destroy_r(ctx, b); GEOSGeom_destroy_r(ctx, p);
    finishGEOS_r(ctx);
    puts("actual_release=3.4.3-CAPI-1.8.3 r4285\ngeometry_and_error_controls=true");
    return 0;
}
