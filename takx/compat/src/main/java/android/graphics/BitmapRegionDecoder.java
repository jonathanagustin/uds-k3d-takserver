// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Iterator;
import java.util.Objects;
import javax.imageio.ImageIO;
import javax.imageio.ImageReadParam;
import javax.imageio.ImageReader;
import javax.imageio.stream.ImageInputStream;
import javax.imageio.stream.MemoryCacheImageInputStream;

/** Repeated PNG/JPEG source-region decoding; see REGION-DECODER.md for scope. */
public final class BitmapRegionDecoder {
    private ImageReader reader;
    private ImageInputStream input;
    private final int width;
    private final int height;
    private final boolean jpeg;
    private boolean recycled;

    private BitmapRegionDecoder(byte[] bytes) throws IOException {
        input = new MemoryCacheImageInputStream(new ByteArrayInputStream(bytes));
        try {
            Iterator<ImageReader> available = ImageIO.getImageReaders(input);
            if (!available.hasNext()) { throw new IOException("unsupported region image format"); }
            reader = available.next();
            String format = reader.getFormatName();
            jpeg = "JPEG".equalsIgnoreCase(format) || "JPG".equalsIgnoreCase(format);
            if (!jpeg && !"PNG".equalsIgnoreCase(format)) {
                throw new IOException("region decoding currently supports PNG and JPEG only");
            }
            reader.setInput(input, false, true);
            width = reader.getWidth(0);
            height = reader.getHeight(0);
            if (width <= 0 || height <= 0) { throw new IOException("invalid region image dimensions"); }
        } catch (IOException | RuntimeException failure) {
            if (reader != null) { reader.dispose(); }
            input.close();
            throw failure;
        }
    }

    public static BitmapRegionDecoder newInstance(InputStream stream, boolean isShareable) throws IOException {
        return newInstance(stream);
    }

    public static BitmapRegionDecoder newInstance(InputStream stream) throws IOException {
        if (stream == null) { return null; }
        // Copy encoded bytes, not decoded pixels; the caller owns its stream and
        // may close it as soon as construction returns, as with AOSP's stream copy.
        return new BitmapRegionDecoder(stream.readAllBytes());
    }

    public static BitmapRegionDecoder newInstance(String path, boolean isShareable) throws IOException {
        return newInstance(path);
    }

    public static BitmapRegionDecoder newInstance(String path) throws IOException {
        try (InputStream stream = new FileInputStream(path)) { return newInstance(stream); }
    }

    public static BitmapRegionDecoder newInstance(byte[] data, int offset, int length, boolean isShareable) throws IOException {
        return newInstance(data, offset, length);
    }

    public static BitmapRegionDecoder newInstance(byte[] data, int offset, int length) throws IOException {
        Objects.requireNonNull(data, "data");
        if (offset < 0 || length < 0 || offset > data.length - length) {
            throw new ArrayIndexOutOfBoundsException("invalid encoded data range");
        }
        return new BitmapRegionDecoder(java.util.Arrays.copyOfRange(data, offset, offset + length));
    }

    private void checkLive() {
        if (recycled) { throw new IllegalStateException("region decoder has been recycled"); }
    }

    public synchronized int getWidth() { checkLive(); return width; }
    public synchronized int getHeight() { checkLive(); return height; }
    public synchronized boolean isRecycled() { return recycled; }

    public synchronized void recycle() {
        if (recycled) { return; }
        recycled = true;
        try {
            reader.dispose();
        } finally {
            reader = null;
            try { input.close(); } catch (IOException ignored) { /* release-only, as in AOSP */ }
            input = null;
        }
    }

    public synchronized Bitmap decodeRegion(Rect rect, BitmapFactory.Options options) {
        Bitmap target = options == null ? null : options.inBitmap;
        if (target != null && target.isRecycled()) { throw new IllegalArgumentException("cannot reuse a recycled bitmap"); }
        checkLive();
        Objects.requireNonNull(rect, "rect");
        if (rect.right <= 0 || rect.bottom <= 0 || rect.left >= width || rect.top >= height) {
            throw new IllegalArgumentException("rectangle is outside the image");
        }
        if (options != null) { options.outWidth = -1; options.outHeight = -1; }
        if (target != null && (!target.isMutable() || !target.hasOwnedAllocation())) {
            throw new IllegalArgumentException("region reuse requires mutable owned ARGB storage");
        }
        long requestedWidth = (long) rect.right - rect.left;
        long requestedHeight = (long) rect.bottom - rect.top;
        if (requestedWidth <= 0 || requestedHeight <= 0) { return null; }
        if (requestedWidth > Integer.MAX_VALUE || requestedHeight > Integer.MAX_VALUE) {
            throw new IllegalArgumentException("unrepresentable region dimensions");
        }
        int left = Math.max(0, rect.left), top = Math.max(0, rect.top);
        int right = Math.min(width, rect.right), bottom = Math.min(height, rect.bottom);
        if (left >= right || top >= bottom) { return null; }
        int sample = options == null ? 1 : Math.max(1, options.inSampleSize);
        boolean wholeImage = left == 0 && top == 0 && right == width && bottom == height;
        int decodeWidth = BitmapFactory.sampledDimension(right - left, sample, jpeg && wholeImage);
        int decodeHeight = BitmapFactory.sampledDimension(bottom - top, sample, jpeg && wholeImage);
        int padX = (left - rect.left) / sample, padY = (top - rect.top) / sample;
        int extraX = (int) (requestedWidth - (left - rect.left) - (right - left)) / sample;
        int extraY = (int) (requestedHeight - (top - rect.top) - (bottom - top)) / sample;
        long outputWidth = (long) decodeWidth + padX + extraX;
        long outputHeight = (long) decodeHeight + padY + extraY;
        if (outputWidth > Integer.MAX_VALUE || outputHeight > Integer.MAX_VALUE
                || outputWidth * outputHeight > Integer.MAX_VALUE / 4) {
            throw new IllegalArgumentException("unrepresentable ARGB region allocation");
        }
        try {
            ImageReadParam params = reader.getDefaultReadParam();
            params.setSourceRegion(new Rectangle(left, top, right - left, bottom - top));
            BufferedImage source = reader.read(0, params);
            BufferedImage sampled = BitmapFactory.sampledImage(source, decodeWidth, decodeHeight, jpeg && wholeImage && sample > 1 && sample % 2 == 0);
            int outWidth = (int) outputWidth, outHeight = (int) outputHeight;
            int[] pixels = new int[outWidth * outHeight];
            Bitmap.Config config = target == null ? BitmapFactory.outputConfig(sampled, options) : target.getConfig();
            int[] decoded = config == Bitmap.Config.ALPHA_8 && BitmapFactory.isGray8(sampled)
                    ? BitmapFactory.decodedPixels(sampled, config)
                    : sampled.getRGB(0, 0, decodeWidth, decodeHeight, null, 0, decodeWidth);
            for (int row = 0; row < decodeHeight; row++) {
                System.arraycopy(decoded, row * decodeWidth, pixels, (padY + row) * outWidth + padX, decodeWidth);
            }
            if (options != null) { options.outWidth = outWidth; options.outHeight = outHeight; }
            boolean alpha = source.getColorModel().hasAlpha();
            if (target == null) {
                // Region JNI does not read Options.inMutable/inJustDecodeBounds.
                return Bitmap.decoded(outWidth, outHeight, pixels, false, alpha, config);
            }
            int copiedWidth = Math.min(outWidth, target.getWidth());
            int copiedHeight = Math.min(outHeight, target.getHeight());
            target.replaceDecodedRegion(pixels, outWidth, copiedWidth, copiedHeight, alpha);
            return target;
        } catch (IOException failure) {
            return null;
        }
    }
}
