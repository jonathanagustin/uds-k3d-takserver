// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.Font;
import java.awt.font.FontRenderContext;
import java.awt.font.GlyphVector;
import java.awt.font.LineMetrics;
import java.awt.font.TextLayout;
import java.awt.geom.Rectangle2D;
import java.util.Objects;

/** Java2D text measurement surface consumed by the public Kernel port module. */
public class Paint {
    public enum Style { FILL, STROKE, FILL_AND_STROKE }
    public enum Align { LEFT, CENTER, RIGHT }

    public static class FontMetricsInt {
        public int top;
        public int ascent;
        public int descent;
        public int bottom;
        public int leading;
    }

    private Typeface typeface = Typeface.DEFAULT;
    private float textSize = 16f;
    private boolean antiAlias;
    private Style style = Style.FILL;
    private Align align = Align.LEFT;
    private int color = 0xff000000;

    public void setStyle(Style value) { style = Objects.requireNonNull(value); }
    public Style getStyle() { return style; }
    public void setTextAlign(Align value) { align = Objects.requireNonNull(value); }
    public Align getTextAlign() { return align; }
    public Typeface setTypeface(Typeface value) {
        Typeface previous = typeface;
        typeface = value == null ? Typeface.DEFAULT : value;
        return previous;
    }
    public Typeface getTypeface() { return typeface; }
    public void setTextSize(float value) {
        if (!Float.isFinite(value) || value < 0f)
            throw new IllegalArgumentException("Text size must be finite and nonnegative");
        textSize = value;
    }
    public float getTextSize() { return textSize; }
    public void setAntiAlias(boolean value) { antiAlias = value; }
    public boolean isAntiAlias() { return antiAlias; }
    public void setARGB(int a, int r, int g, int b) {
        color = ((a & 255) << 24) | ((r & 255) << 16) | ((g & 255) << 8) | (b & 255);
    }
    public int getColor() { return color; }

    private Font font() { return typeface.atSize(textSize); }
    private FontRenderContext context() { return new FontRenderContext(null, antiAlias, true); }

    public FontMetricsInt getFontMetricsInt() {
        FontMetricsInt result = new FontMetricsInt();
        if (textSize == 0f) return result;
        Font font = font();
        FontRenderContext frc = context();
        LineMetrics lines = font.getLineMetrics("Hg", frc);
        Rectangle2D bounds = font.getMaxCharBounds(frc);
        result.ascent = -(int) Math.ceil(lines.getAscent());
        result.descent = (int) Math.ceil(lines.getDescent());
        result.top = Math.min(result.ascent, (int) Math.floor(bounds.getMinY()));
        result.bottom = Math.max(result.descent, (int) Math.ceil(bounds.getMaxY()));
        result.leading = (int) Math.ceil(lines.getLeading());
        return result;
    }

    public float measureText(char[] text, int index, int count) {
        checkRange(text, index, count);
        return measureText(new String(text, index, count));
    }

    public float measureText(String text) {
        if (text == null) throw new IllegalArgumentException("Text must not be null");
        if (text.isEmpty() || textSize == 0f) return 0f;
        return new TextLayout(text, font(), context()).getAdvance();
    }

    public int getTextWidths(char[] text, int index, int count, float[] widths) {
        checkRange(text, index, count);
        Objects.requireNonNull(widths, "widths");
        if (widths.length < count) throw new ArrayIndexOutOfBoundsException("Insufficient width slots");
        java.util.Arrays.fill(widths, 0, count, 0f);
        if (count == 0 || textSize == 0f) return count;
        GlyphVector glyphs = font().layoutGlyphVector(context(), text, index, index + count,
                Font.LAYOUT_LEFT_TO_RIGHT);
        for (int g = 0; g < glyphs.getNumGlyphs(); g++) {
            int ch = glyphs.getGlyphCharIndex(g);
            widths[ch] += (float) (glyphs.getGlyphPosition(g + 1).getX()
                    - glyphs.getGlyphPosition(g).getX());
        }
        return count;
    }

    private static void checkRange(char[] text, int index, int count) {
        if (text == null) throw new IllegalArgumentException("Text must not be null");
        if (index < 0 || count < 0 || index > text.length - count)
            throw new IndexOutOfBoundsException("Invalid text range");
    }
}
