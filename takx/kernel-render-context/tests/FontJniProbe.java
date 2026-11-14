// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Standalone runtime diagnostic; loads no project/JOGL libraries.
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.font.TextLayout;
import java.awt.image.BufferedImage;
public final class FontJniProbe {
    public static void main(String[] args) {
        BufferedImage image = new BufferedImage(160, 80, BufferedImage.TYPE_INT_ARGB);
        Graphics2D graphics = image.createGraphics();
        try {
            Font font = new Font(Font.SANS_SERIF, Font.PLAIN, 16);
            graphics.setFont(font);
            new TextLayout("Kernel context", font, graphics.getFontRenderContext()).getOutline(null);
            graphics.drawString("Kernel context", 4, 24);
            System.out.println("FONT_PROBE_COMPLETED");
        } finally { graphics.dispose(); }
    }
}
