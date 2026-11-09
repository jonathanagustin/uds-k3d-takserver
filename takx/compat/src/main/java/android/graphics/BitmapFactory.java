// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.image.BufferedImage;
import java.io.File;
import java.io.FileInputStream;
import java.io.ByteArrayInputStream;
import java.util.Objects;
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
        public boolean inMutable;
        public boolean inJustDecodeBounds;
        public int outWidth;
        public int outHeight;
    }

    private static Bitmap decoded(BufferedImage image, Options options) {
        if (image == null) { return null; }
        // Decode into a real straight-alpha ARGB buffer, including RGB inputs.
        BufferedImage result = new BufferedImage(image.getWidth(), image.getHeight(), BufferedImage.TYPE_INT_ARGB);
        int[] pixels = image.getRGB(0, 0, image.getWidth(), image.getHeight(), null, 0, image.getWidth());
        result.setRGB(0, 0, image.getWidth(), image.getHeight(), pixels, 0, image.getWidth());
        return new Bitmap(result, options != null && options.inMutable);
    }

    private static void reset(Options options) {
        if (options != null) { options.outWidth = -1; options.outHeight = -1; }
    }

    public static Bitmap decodeByteArray(byte[] data, int offset, int length) {
        return decodeByteArray(data, offset, length, null);
    }

    public static Bitmap decodeByteArray(byte[] data, int offset, int length, Options options) {
        Objects.requireNonNull(data, "data");
        if (offset < 0 || length < 0 || offset > data.length - length) {
            throw new ArrayIndexOutOfBoundsException("invalid encoded data range");
        }
        return decodeStream(new ByteArrayInputStream(data, offset, length), null, options);
    }

    public static Bitmap decodeFile(String path, Options options) {
        reset(options);
        if (path == null) { return null; }
        try {
            try (InputStream input = new FileInputStream(new File(path))) {
                return decodeStream(input, null, options);
            }
        } catch (IOException | IllegalArgumentException exception) {
            reset(options);
            return null;
        }
    }

    public static Bitmap decodeStream(InputStream stream, Object padding, Options options) {
        if (padding != null) {
            throw new IllegalArgumentException("padding is outside this desktop decoding slice");
        }
        reset(options);
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
                int width = reader.getWidth(0);
                int height = reader.getHeight(0);
                if (options != null) {
                    options.outWidth = width;
                    options.outHeight = height;
                    if (options.inJustDecodeBounds) { return null; }
                }
                return decoded(reader.read(0), options);
            } finally {
                reader.dispose();
            }
        } catch (IOException | IllegalArgumentException exception) {
            reset(options);
            return null;
        }
    }
}
