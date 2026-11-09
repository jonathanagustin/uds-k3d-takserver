// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

/** Mutable desktop coordinate value; no Android parcel/runtime contract. */
public class PointF {
    public float x;
    public float y;
    public PointF() {}
    public PointF(float x, float y) { set(x, y); }
    public PointF(PointF source) { this(source.x, source.y); }
    public PointF(Point source) { this(source.x, source.y); }
    public final void set(float x, float y) { this.x = x; this.y = y; }
    public final void set(PointF source) { set(source.x, source.y); }
    public final void negate() { x = -x; y = -y; }
    public final void offset(float dx, float dy) { x += dx; y += dy; }
    public final boolean equals(float x, float y) { return this.x == x && this.y == y; }
    @Override public boolean equals(Object other) {
        return other instanceof PointF && equals(((PointF) other).x, ((PointF) other).y);
    }
    @Override public int hashCode() { return Float.hashCode(x == 0f ? 0f : x) * 31 + Float.hashCode(y == 0f ? 0f : y); }
    @Override public String toString() { return "PointF(" + x + ", " + y + ")"; }
    public final float length() { return length(x, y); }
    public static float length(float x, float y) { return (float) Math.hypot(x, y); }
}
