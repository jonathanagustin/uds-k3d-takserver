// SPDX-License-Identifier: GPL-3.0-only
import android.graphics.PorterDuff;
import gov.tak.api.commons.graphics.ColorBlendMode;
import gov.tak.platform.lang.Strings;
import gov.tak.platform.marshal.MarshalManager;

/** Exercises real upstream port utilities without loading native graphics. */
public final class PortRuntimeTest {
    public static void main(String[] args) {
        int checks = 0;
        for (ColorBlendMode mode : ColorBlendMode.values()) {
            PorterDuff.Mode platform = MarshalManager.marshal(mode, ColorBlendMode.class, PorterDuff.Mode.class);
            if (platform == null || MarshalManager.marshal(platform, PorterDuff.Mode.class,
                    ColorBlendMode.class) != mode)
                throw new AssertionError("Blend-mode marshal round trip: " + mode);
            checks++;
        }
        if (!"<Map & \"label\">".equals(Strings.unescapeHtml("&lt;Map &amp; &quot;label&quot;&gt;")))
            throw new AssertionError("Real Commons Text and transitive runtime resolution");
        checks++;
        System.out.println("Public port runtime: " + checks + " checks passed");
    }
}
