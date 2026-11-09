// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

/** Mutable desktop coordinate value; no Android parcel/runtime contract. */
public class Point {
    public int x;
    public int y;
    public Point() {}
    public Point(int x, int y) { set(x, y); }
    public Point(Point source) { this(source.x, source.y); }
    public final void set(int x, int y) { this.x = x; this.y = y; }
    public final void set(Point source) { set(source.x, source.y); }
    public final void negate() { x = -x; y = -y; }
    public final void offset(int dx, int dy) { x += dx; y += dy; }
    public final boolean equals(int x, int y) { return this.x == x && this.y == y; }
    @Override public boolean equals(Object other) {
        return other instanceof Point && equals(((Point) other).x, ((Point) other).y);
    }
    @Override public int hashCode() { return Integer.hashCode(x) * 31 + Integer.hashCode(y); }
    @Override public String toString() { return "Point(" + x + ", " + y + ")"; }
}
