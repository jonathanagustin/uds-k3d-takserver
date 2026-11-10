// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.Font;
import java.awt.font.FontRenderContext;
import java.awt.font.TextLayout;

/** AOSP range/rounding contracts with an independent Java2D advance oracle. */
public final class PaintRangeTest {
    private static int checks;
    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }
    private static void rejects(Class<? extends Throwable> kind, Runnable action) {
        try { action.run(); }
        catch (Throwable error) { check(kind.isInstance(error), "wrong exception: " + error); return; }
        throw new AssertionError("expected " + kind.getName());
    }
    public static void main(String[] args) {
        boolean fractional = false;
        for (int style = 0; style < 4; style++) {
            for (float size : new float[] {9.25f, 18.5f, 31.75f}) {
                Paint paint = new Paint();
                paint.setTypeface(Typeface.create("sans-serif", style));
                paint.setTextSize(size);
                paint.setAntiAlias(true);
                Font font = new Font(Font.SANS_SERIF, style, 1).deriveFont(size);
                FontRenderContext context = new FontRenderContext(null, true, true);
                for (String text : new String[] {"Map label", "Wi", "A\u0301", "\u03a9\ud83d\ude42", "\u0645\u0631\u062d\u0628\u0627"}) {
                    float advance = new TextLayout(text, font, context).getAdvance();
                    float expected = (float) Math.ceil(advance);
                    fractional |= advance != expected;
                    String wrapped = "prefix" + text + "suffix";
                    check(paint.measureText(wrapped, 6, 6 + text.length()) == expected, "range is start/end, not count");
                    check(paint.measureText(text) == expected, "String width rounds the independent advance");
                    check(paint.measureText(wrapped.toCharArray(), 6, text.length()) == expected, "char range retains index/count and rounds");
                }
            }
        }
        check(fractional, "oracle exercised a fractional advance");
        Paint paint = new Paint();
        check(paint.measureText("", 0, 0) == 0f, "empty string");
        check(paint.measureText("abc", 0, 0) == 0f, "empty beginning");
        check(paint.measureText("abc", 1, 1) == 0f, "empty middle");
        check(paint.measureText("abc", 3, 3) == 0f, "empty end");
        rejects(IllegalArgumentException.class, () -> paint.measureText((String)null, 0, 0));
        rejects(IllegalArgumentException.class, () -> paint.measureText((String)null, -1, Integer.MAX_VALUE));
        for (int[] range : new int[][] {{-1, 0}, {0, -1}, {2, 1}, {0, 4}, {4, 4}, {0, Integer.MAX_VALUE}, {Integer.MAX_VALUE, Integer.MIN_VALUE}}) {
            rejects(IndexOutOfBoundsException.class, () -> paint.measureText("abc", range[0], range[1]));
        }
        paint.setTextSize(0f);
        check(paint.measureText("abc", 1, 2) == 0f, "zero text size");
        rejects(IndexOutOfBoundsException.class, () -> paint.measureText("", 0, 1));
        rejects(IndexOutOfBoundsException.class, () -> paint.measureText("abc", 2, 1));
        System.out.println("Paint range/rounding checks: " + checks);
    }
}
