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
        public int inSampleSize;
        public boolean inScaled = true;
        public Bitmap inBitmap;
        public boolean inJustDecodeBounds;
        public int inDensity;
        public int inTargetDensity;
        public int inScreenDensity;
        // Only these deprecated requests are ignored by the pinned Android 14 API.
        public boolean inDither;
        public boolean inInputShareable;
        public boolean inPreferQualityOverSpeed;
        public boolean inPurgeable;
        // Still active in AOSP: rejected explicitly by this ImageIO slice.
        public byte[] inTempStorage;
        public boolean mCancel;
        public void requestCancelDecode() { mCancel = true; }
        public int outWidth;
        public int outHeight;
    }

    private static Bitmap decoded(BufferedImage image, Options options) {
        if (image == null) { return failed(options); }
        // Decode into a real straight-alpha ARGB buffer, including RGB inputs.
        int width = image.getWidth();
        int height = image.getHeight();
        Bitmap.Config config = outputConfig(image, options);
        int[] pixels = decodedPixels(image, config);
        Bitmap reused = options == null ? null : options.inBitmap;
        if (reused == null) {
            return Bitmap.decoded(width, height, pixels, options != null && options.inMutable, image.getColorModel().hasAlpha(), config);
        }
        if (!reused.isMutable() || !reused.hasOwnedAllocation()) {
            throw new ReuseException("reuse requires a mutable owned ARGB allocation");
        }
        try {
            reused.replaceDecoded(width, height, pixels, image.getColorModel().hasAlpha(), config);
        } catch (IllegalArgumentException exception) {
            throw new ReuseException("bitmap allocation is too small");
        }
        return reused;
    }

    static Bitmap.Config outputConfig(BufferedImage image, Options options) {
        Bitmap.Config preferred = options == null ? null : options.inPreferredConfig;
        if (preferred == Bitmap.Config.RGB_565 && !image.getColorModel().hasAlpha()) {
            return Bitmap.Config.RGB_565;
        }
        if (preferred == Bitmap.Config.ALPHA_8 && isGray8(image)) { return Bitmap.Config.ALPHA_8; }
        return Bitmap.Config.ARGB_8888;
    }

    static boolean isGray8(BufferedImage image) {
        return !image.getColorModel().hasAlpha() && image.getColorModel().getNumColorComponents() == 1
                && image.getColorModel().getColorSpace().getType() == java.awt.color.ColorSpace.TYPE_GRAY
                && image.getSampleModel().getSampleSize(0) == 8;
    }

    static int[] decodedPixels(BufferedImage image, Bitmap.Config config) {
        int width = image.getWidth(), height = image.getHeight();
        if (config != Bitmap.Config.ALPHA_8) { return image.getRGB(0, 0, width, height, null, 0, width); }
        int[] pixels = new int[width * height];
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                pixels[y * width + x] = image.getRaster().getSample(x, y, 0) << 24;
            }
        }
        return pixels;
    }

    // Android 14 SkSampledCodec: JPEG first uses a supported native 1/2, 1/4,
    // or 1/8 scale when divisible; the remaining sample is integer division.
    static int sampledDimension(int dimension, int sample, boolean jpeg) {
        sample = Math.max(1, sample);
        int nativeSample = 1;
        if (jpeg) {
            for (int candidate : new int[] {8, 4, 2}) {
                if (sample % candidate == 0) { nativeSample = candidate; break; }
            }
        }
        int nativeSize = (int) (((long) dimension + nativeSample - 1) / nativeSample);
        return Math.max(1, nativeSize / (sample / nativeSample));
    }

    static BufferedImage sampledImage(BufferedImage image, int width, int height) {
        return sampledImage(image, width, height, false);
    }

    static BufferedImage sampledImage(BufferedImage image, int width, int height, boolean proportional) {
        if (image.getWidth() == width && image.getHeight() == height) { return image; }
        boolean gray = isGray8(image);
        BufferedImage sampled = new BufferedImage(width, height, gray ? BufferedImage.TYPE_BYTE_GRAY
                : image.getColorModel().hasAlpha() ? BufferedImage.TYPE_INT_ARGB : BufferedImage.TYPE_INT_RGB);
        // Real pixel sampling at cell centers. JPEG color/native DCT rounding
        // remains ImageIO's, not a claim of bit-identical Skia decoding.
        int stepX = image.getWidth() / width;
        int stepY = image.getHeight() / height;
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                int sourceX = proportional ? (int) (((2L * x + 1) * image.getWidth()) / (2L * width)) : stepX / 2 + x * stepX;
                int sourceY = proportional ? (int) (((2L * y + 1) * image.getHeight()) / (2L * height)) : stepY / 2 + y * stepY;
                if (gray) {
                    sampled.getRaster().setSample(x, y, 0, image.getRaster().getSample(sourceX, sourceY, 0));
                } else {
                    sampled.setRGB(x, y, image.getRGB(sourceX, sourceY));
                }
            }
        }
        return sampled;
    }

    private static final class ReuseException extends IllegalArgumentException {
        ReuseException(String message) { super(message); }
    }

    private static void validate(Options options) {
        if (options != null && options.inTempStorage != null) {
            throw new UnsupportedOperationException("caller-supplied decoder scratch storage is not supported");
        }
        // AOSP bounds-only returns before density scaling/metadata. Actual
        // images require density metadata even when inScaled is false or the
        // source/target densities match; do not silently discard that request.
        if (options != null && !options.inJustDecodeBounds && options.inDensity != 0) {
            throw new UnsupportedOperationException("bitmap density metadata/scaling is outside this slice");
        }
        if (options != null && options.inBitmap != null && options.inBitmap.isRecycled()) {
            throw new ReuseException("cannot reuse a recycled bitmap");
        }
    }

    private static Bitmap failed(Options options) {
        if (options != null && options.inBitmap != null) {
            throw new ReuseException("cannot decode into the supplied bitmap");
        }
        return null;
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
        validate(options);
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

    public static Bitmap decodeStream(InputStream stream) {
        return decodeStream(stream, null, null);
    }

    public static Bitmap decodeStream(InputStream stream, Object padding, Options options) {
        if (padding != null) {
            throw new IllegalArgumentException("padding is outside this desktop decoding slice");
        }
        reset(options);
        if (stream == null) { return null; }
        validate(options);
        // No global ImageIO cache setting and no ownership of the caller's stream.
        InputStream borrowed = new FilterInputStream(stream) {
            @Override public void close() { /* The caller owns this stream. */ }
        };
        try (ImageInputStream input = new MemoryCacheImageInputStream(borrowed)) {
            Iterator<ImageReader> readers = ImageIO.getImageReaders(input);
            if (!readers.hasNext()) { return failed(options); }
            ImageReader reader = readers.next();
            try {
                reader.setInput(input, true, true);
                int width = reader.getWidth(0);
                int height = reader.getHeight(0);
                int sample = options == null ? 1 : Math.max(1, options.inSampleSize);
                boolean jpeg = "JPEG".equalsIgnoreCase(reader.getFormatName()) || "JPG".equalsIgnoreCase(reader.getFormatName());
                int sampledWidth = sampledDimension(width, sample, jpeg);
                int sampledHeight = sampledDimension(height, sample, jpeg);
                if (options != null) {
                    options.outWidth = sampledWidth;
                    options.outHeight = sampledHeight;
                    if (options.inJustDecodeBounds) { return failed(options); }
                }
                return decoded(sampledImage(reader.read(0), sampledWidth, sampledHeight, jpeg && sample > 1 && sample % 2 == 0), options);
            } finally {
                reader.dispose();
            }
        } catch (ReuseException exception) {
            throw exception;
        } catch (IOException | IllegalArgumentException exception) {
            reset(options);
            return failed(options);
        }
    }
}
