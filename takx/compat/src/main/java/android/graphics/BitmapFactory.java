// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.image.BufferedImage;
import java.io.File;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import javax.imageio.ImageIO;
import javax.imageio.ImageReader;
import java.util.Iterator;
import javax.imageio.stream.ImageInputStream;
import javax.imageio.stream.MemoryCacheImageInputStream;

/** JDK ImageIO decoding for the supported ARGB bitmap slice. */
public final class BitmapFactory {
    private BitmapFactory() {}

    public static final class Options {
        public Bitmap.Config inPreferredConfig = Bitmap.Config.ARGB_8888;
    }

    private static Bitmap decoded(BufferedImage image) {
        if (image == null) { return null; }
        // Decode into a real straight-alpha ARGB buffer, including RGB inputs.
        Bitmap result = Bitmap.createBitmap(image.getWidth(), image.getHeight(), Bitmap.Config.ARGB_8888);
        int[] pixels = image.getRGB(0, 0, image.getWidth(), image.getHeight(), null, 0, image.getWidth());
        result.setPixels(pixels, 0, image.getWidth(), 0, 0, image.getWidth(), image.getHeight());
        return result;
    }

    public static Bitmap decodeFile(String path, Options options) {
        if (path == null) { return null; }
        try {
            return decoded(ImageIO.read(new File(path)));
        } catch (IOException | IllegalArgumentException exception) {
            return null;
        }
    }

    public static Bitmap decodeStream(InputStream stream, Object padding, Options options) {
        if (padding != null) {
            throw new IllegalArgumentException("padding is outside this desktop decoding slice");
        }
        if (stream == null) { return null; }
        // No global ImageIO cache setting and no ownership of the caller's stream.
        InputStream borrowed = new FilterInputStream(stream) {
            @Override public void close() { /* The caller owns this stream. */ }
        };
        try (ImageInputStream input = new MemoryCacheImageInputStream(borrowed)) {
            Iterator<ImageReader> readers = ImageIO.getImageReaders(input);
            if (!readers.hasNext()) { return null; }
            ImageReader reader = readers.next();
            try {
                reader.setInput(input, true, true);
                return decoded(reader.read(0));
            } finally {
                reader.dispose();
            }
        } catch (IOException | IllegalArgumentException exception) {
            return null;
        }
    }
}
