// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.Font;
import java.util.Locale;

/** Desktop font selection backed by the JDK font resolver. */
public final class Typeface {
    public static final int NORMAL = 0;
    public static final int BOLD = 1;
    public static final int ITALIC = 2;
    public static final int BOLD_ITALIC = 3;
    public static final Typeface DEFAULT = create((String) null, NORMAL);
    public static final Typeface DEFAULT_BOLD = create((String) null, BOLD);
    public static final Typeface SANS_SERIF = create("sans-serif", NORMAL);
    public static final Typeface SERIF = create("serif", NORMAL);
    public static final Typeface MONOSPACE = create("monospace", NORMAL);

    private final Font font;

    private Typeface(Font font) {
        this.font = font;
    }

    public static Typeface create(String familyName, int style) {
        String family = familyName == null ? Font.SANS_SERIF : familyName;
        switch (family.toLowerCase(Locale.ROOT)) {
            case "sans-serif": family = Font.SANS_SERIF; break;
            case "serif": family = Font.SERIF; break;
            case "monospace": family = Font.MONOSPACED; break;
            default: break;
        }
        return new Typeface(new Font(family, validStyle(style), 1));
    }

    public static Typeface create(Typeface family, int style) {
        return new Typeface((family == null ? DEFAULT : family).font.deriveFont(validStyle(style)));
    }

    private static int validStyle(int style) {
        return style >= NORMAL && style <= BOLD_ITALIC ? style : NORMAL;
    }

    public int getStyle() { return font.getStyle(); }
    public boolean isBold() { return font.isBold(); }
    public boolean isItalic() { return font.isItalic(); }

    Font atSize(float size) { return font.deriveFont(size); }
}
