// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.api.cot.detail;

import android.content.Context;
import android.graphics.Bitmap;
import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.font.FontRenderContext;
import java.awt.font.TextLayout;
import java.awt.geom.AffineTransform;
import java.awt.image.BufferedImage;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import javax.imageio.ImageIO;

/** Execute unchanged upstream RolesManager against real file assets and desktop drawing. */
public final class RolesManagerIconTest {
    private static int checks;
    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }
    private static BufferedImage white(int width, int height) {
        BufferedImage image = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);
        Graphics2D graphics = image.createGraphics();
        graphics.setColor(Color.WHITE);
        graphics.fillRect(0, 0, width, height);
        graphics.dispose();
        return image;
    }
    public static void main(String[] args) throws Exception {
        Path root = Path.of(args[0]);
        Path assets = Files.createDirectories(root.resolve("assets"));
        int width = 64, height = 48;
        Path source = assets.resolve("role.png");
        ImageIO.write(white(width, height), "png", source.toFile());
        byte[] original = Files.readAllBytes(source);
        try (URLClassLoader loader = new URLClassLoader(new URL[] {root.toUri().toURL()}, RolesManagerIconTest.class.getClassLoader())) {
            Context context = new Context(root.resolve("app"), "gov.tak.test.roles", loader);
            RolesManager manager = new RolesManager();
            String abbreviation = "Mi";
            Bitmap icon = manager.getIcon(abbreviation, "role.png", context);
            check(icon != null && icon.getWidth() == width && icon.getHeight() == height && icon.isMutable(), "real decoded and copied icon");
            check(manager.getIcon(abbreviation, "role.png", context) == icon, "upstream cache identity");
            check(manager.getIcon("missing", "missing.png", context) == null, "missing asset remains an upstream failure");
            Font font = new Font(Font.SANS_SERIF, Font.BOLD, 12);
            TextLayout layout = new TextLayout(abbreviation, font, new FontRenderContext(null, false, true));
            int measured = (int)Math.ceil(layout.getAdvance());
            int centerX = (width - measured) / 2;
            int baseline = (height + 12 / 2) / 2;
            BufferedImage expected = white(width, height);
            Graphics2D graphics = expected.createGraphics();
            graphics.setColor(Color.BLACK);
            graphics.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_OFF);
            graphics.setRenderingHint(RenderingHints.KEY_FRACTIONALMETRICS, RenderingHints.VALUE_FRACTIONALMETRICS_ON);
            // Both draw operations belong to the unchanged upstream consumer.
            graphics.fill(layout.getOutline(AffineTransform.getTranslateInstance(0, 0)));
            graphics.fill(layout.getOutline(AffineTransform.getTranslateInstance(centerX, baseline)));
            graphics.dispose();
            int ink = 0;
            for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
                int actual = icon.getPixel(x, y);
                check(actual == expected.getRGB(x, y), "role text placement at " + x + "," + y);
                if (actual != Color.WHITE.getRGB()) ink++;
            }
            check(ink > 0, "consumer rendered actual glyphs");
            check(java.util.Arrays.equals(original, Files.readAllBytes(source)), "source asset remains unchanged");
            check(manager.getIcon("WW", "role.png", context) != icon, "distinct abbreviations have separate icons");
        }
        System.out.println("Unchanged RolesManager icon checks: " + checks);
    }
}
