// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.util.Map;
import java.util.Locale;

/** Packed integer sRGB slice; no ColorSpace, wide-gamut or native HSV contract. */
public final class Color {
    private Color() {}
    public static final int BLACK=0xff000000, DKGRAY=0xff444444, GRAY=0xff888888,
        LTGRAY=0xffcccccc, WHITE=0xffffffff, RED=0xffff0000, GREEN=0xff00ff00,
        BLUE=0xff0000ff, YELLOW=0xffffff00, CYAN=0xff00ffff, MAGENTA=0xffff00ff,
        TRANSPARENT=0;
    private static final Map<String, Integer> NAMES = Map.ofEntries(
        Map.entry("black", BLACK), Map.entry("darkgray", DKGRAY), Map.entry("gray", GRAY),
        Map.entry("lightgray", LTGRAY), Map.entry("white", WHITE), Map.entry("red", RED),
        Map.entry("green", GREEN), Map.entry("blue", BLUE), Map.entry("yellow", YELLOW),
        Map.entry("cyan", CYAN), Map.entry("magenta", MAGENTA), Map.entry("aqua", CYAN),
        Map.entry("fuchsia", MAGENTA), Map.entry("darkgrey", DKGRAY), Map.entry("grey", GRAY),
        Map.entry("lightgrey", LTGRAY), Map.entry("lime", GREEN), Map.entry("maroon", 0xff800000),
        Map.entry("navy", 0xff000080), Map.entry("olive", 0xff808000),
        Map.entry("purple", 0xff800080), Map.entry("silver", 0xffc0c0c0), Map.entry("teal", 0xff008080));
    public static int alpha(int color) { return color >>> 24; }
    public static int red(int color) { return (color >>> 16) & 255; }
    public static int green(int color) { return (color >>> 8) & 255; }
    public static int blue(int color) { return color & 255; }
    public static int argb(int alpha, int red, int green, int blue) {
        return (alpha << 24) | (red << 16) | (green << 8) | blue;
    }
    public static int rgb(int red, int green, int blue) { return argb(255, red, green, blue); }
    public static int parseColor(String value) {
        if (value.charAt(0) == '#') {
            long parsed = Long.parseLong(value.substring(1), 16);
            if (value.length() == 7) parsed |= 0xff000000L;
            else if (value.length() != 9) throw new IllegalArgumentException("Unknown color");
            return (int) parsed;
        }
        Integer named = NAMES.get(value.toLowerCase(Locale.ROOT));
        if (named == null) throw new IllegalArgumentException("Unknown color");
        return named;
    }
}
