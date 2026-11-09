// SPDX-License-Identifier: GPL-3.0-only
import android.graphics.Paint;
import android.graphics.Typeface;
import gov.tak.api.commons.graphics.DisplaySettings;
import gov.tak.api.commons.graphics.Font;
import gov.tak.api.commons.graphics.FontMetrics;

/** Runs against the real public Kernel FontMetrics, not a replacement. */
public final class FontCompatibilityTest {
    private static int checks;
    private static void check(boolean ok, String message) {
        checks++;
        if (!ok) throw new AssertionError(message);
    }
    private static void rejects(Class<? extends Throwable> type, Runnable action) {
        try { action.run(); } catch (Throwable ex) {
            check(type.isInstance(ex), "Wrong exception: " + ex);
            return;
        }
        throw new AssertionError("Expected " + type.getName());
    }
    public static void main(String[] args) {
        for (int style = 0; style <= 3; style++) {
            Typeface face = Typeface.create("sans-serif", style);
            check(face.getStyle() == style, "Style selection");
            check(face.isBold() == ((style & 1) != 0), "Bold selection");
            check(face.isItalic() == ((style & 2) != 0), "Italic selection");
            Paint p = new Paint();
            p.setTypeface(face);
            p.setTextSize(18.5f);
            p.setAntiAlias(true);
            p.setStyle(Paint.Style.FILL_AND_STROKE);
            p.setTextAlign(Paint.Align.LEFT);
            p.setARGB(127, 32, 64, 128);
            check(p.getColor() == 0x7f204080, "ARGB state");
            check(p.getStyle() == Paint.Style.FILL_AND_STROKE, "Style state");
            check(p.getTextAlign() == Paint.Align.LEFT && p.isAntiAlias(), "Text state");
            check(p.measureText("WW") > p.measureText("ii"), "Real proportional font advances");
            check(p.measureText("\u03a9\ud83d\ude42") > 0, "Unicode measurement");
            char[] chars = "xABz".toCharArray();
            float[] widths = new float[3];
            widths[2] = 123f;
            check(p.getTextWidths(chars, 1, 2, widths) == 2, "Character count");
            check(widths[0] > 0f && widths[1] > 0f && widths[2] == 123f, "Offsets and destination boundary");
            check(Math.abs(p.measureText(chars, 1, 2) - widths[0] - widths[1]) < 0.01f,
                    "Glyph advances agree for unshaped Latin pair");
            Paint.FontMetricsInt fm = p.getFontMetricsInt();
            check(fm.top <= fm.ascent && fm.ascent < 0 && fm.descent > 0
                    && fm.bottom >= fm.descent && fm.leading >= 0, "Signed font bounds");
            float original = p.measureText("Measurements");
            p.setTextSize(37f);
            check(Math.abs(p.measureText("Measurements") / original - 2f) < 0.01f,
                    "Fractional font size scales");
        }
        Paint p = new Paint();
        check(p.measureText("") == 0f, "Empty text");
        rejects(IllegalArgumentException.class, () -> p.measureText((String) null));
        rejects(IllegalArgumentException.class, () -> p.setTextSize(Float.NaN));
        rejects(IllegalArgumentException.class, () -> p.setTextSize(-1));
        rejects(IndexOutOfBoundsException.class, () -> p.measureText(new char[2], 1, 2));
        rejects(IndexOutOfBoundsException.class, () -> p.measureText(new char[2], Integer.MAX_VALUE, 2));
        rejects(ArrayIndexOutOfBoundsException.class,
                () -> p.getTextWidths(new char[2], 0, 2, new float[1]));
        p.setTextSize(0f);
        check(p.measureText("A") == 0f && p.getFontMetricsInt().bottom == 0, "Zero size");
        float[] zeroWidths = {9f};
        p.getTextWidths(new char[] {'A'}, 0, 1, zeroWidths);
        check(zeroWidths[0] == 0f, "Zero size character widths");

        DisplaySettings.setRelativeScaling(1f);
        for (Font.Style style : Font.Style.values()) {
            FontMetrics fm = new FontMetrics(new Font("sans-serif", style, 18.5f));
            float width = fm.measureTextWidth("Map label");
            check(width > 0, "Upstream font width");
            check(fm.measureTextWidth("Map label\ni") == width, "Upstream multiline maximum width");
            check(fm.measureTextHeight("Map\nlabel") - fm.measureTextHeight("Map")
                    == fm.getBaselineSpacing(), "Upstream multiline baseline spacing");
            check(fm.measureTextHeight("") == 0f, "Upstream empty height");
            check(fm.measureTextWidth("\u03a9") > 0, "Upstream non-ASCII measurement");
            DisplaySettings.setRelativeScaling(2f);
            check(Math.abs(fm.measureTextWidth("Map label") - width * 2f) <= 2f,
                    "Upstream live relative scaling invalidation");
            DisplaySettings.setRelativeScaling(1f);
            check(fm.measureTextWidth("Map label") == width, "Upstream scaling returns to original");
        }
        System.out.println("Font compatibility: " + checks + " checks passed");
    }
}
