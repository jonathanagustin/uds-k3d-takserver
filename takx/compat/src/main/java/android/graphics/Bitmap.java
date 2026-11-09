// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.image.BufferedImage;
import java.awt.image.DataBufferInt;
import java.awt.image.DirectColorModel;
import java.awt.image.Raster;
import java.awt.image.WritableRaster;
import java.util.Objects;

/** ARGB pixel slice of uds-desktop-android-compat 0.1.0; not an Android SDK. */
public final class Bitmap {
    public enum Config { ARGB_8888 }
    public enum CompressFormat { PNG, JPEG }

    private BufferedImage image;
    private int width;
    private int height;
    private int[] allocation;
    private final boolean mutable;
    private boolean recycled;
    private boolean alpha = true;
    private final boolean owned;

    // Pinned Kernel BitmapMarshal reflects this exact constructor and method.
    // Retain the caller's backing image, including its actual color model.
    Bitmap(BufferedImage image) {
        this(image, true);
    }

    Bitmap(BufferedImage image, boolean mutable) {
        this.image = Objects.requireNonNull(image, "image");
        this.width = image.getWidth();
        this.height = image.getHeight();
        this.mutable = mutable;
        this.allocation = null;
        this.owned = false;
        this.alpha = image.getColorModel().hasAlpha();
    }

    private Bitmap(int width, int height, boolean mutable) {
        int count = pixelCount(width, height);
        this.allocation = new int[count];
        this.owned = true;
        this.mutable = mutable;
        reshape(width, height);
    }

    private static int pixelCount(int width, int height) {
        if (width <= 0 || height <= 0 || (long) width * height > Integer.MAX_VALUE / 4) {
            throw new IllegalArgumentException("invalid or unrepresentable ARGB allocation size");
        }
        return width * height;
    }

    private void reshape(int width, int height) {
        int[] masks = alpha ? new int[]{0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000}
                : new int[]{0x00ff0000, 0x0000ff00, 0x000000ff};
        DataBufferInt buffer = new DataBufferInt(allocation, allocation.length);
        WritableRaster raster = Raster.createPackedRaster(buffer, width, height, width, masks, null);
        image = new BufferedImage(new DirectColorModel(alpha ? 32 : 24, masks[0], masks[1], masks[2], alpha ? masks[3] : 0),
                raster, false, null);
        this.width = width;
        this.height = height;
    }

    static Bitmap decoded(int width, int height, int[] pixels, boolean mutable, boolean alpha) {
        Bitmap result = new Bitmap(width, height, mutable);
        result.alpha = alpha;
        result.reshape(width, height);
        System.arraycopy(pixels, 0, result.allocation, 0, pixels.length);
        return result;
    }

    void replaceDecoded(int width, int height, int[] pixels, boolean alpha) {
        checkWritable();
        int count = pixelCount(width, height);
        requireOwned();
        if (count > allocation.length) { throw new IllegalArgumentException("bitmap allocation is too small"); }
        this.alpha = alpha;
        reshape(width, height);
        System.arraycopy(pixels, 0, allocation, 0, count);
    }

    public Config getConfig() {
        checkLive();
        return owned ? Config.ARGB_8888 : null;
    }

    public boolean hasAlpha() { checkLive(); return alpha; }

    public static Bitmap createScaledBitmap(Bitmap source, int width, int height, boolean filter) {
        Objects.requireNonNull(source, "source");
        pixelCount(width, height);
        if (source.recycled) { throw new IllegalArgumentException("cannot scale a recycled bitmap"); }
        if (!source.mutable && source.width == width && source.height == height) { return source; }
        Bitmap result = new Bitmap(width, height, true);
        result.alpha = source.alpha;
        result.reshape(width, height);
        java.awt.Graphics2D graphics = result.image.createGraphics();
        try {
            graphics.setComposite(java.awt.AlphaComposite.Src);
            graphics.setRenderingHint(java.awt.RenderingHints.KEY_INTERPOLATION, filter
                    ? java.awt.RenderingHints.VALUE_INTERPOLATION_BILINEAR
                    : java.awt.RenderingHints.VALUE_INTERPOLATION_NEAREST_NEIGHBOR);
            graphics.drawImage(source.image, 0, 0, width, height, null);
        } finally { graphics.dispose(); }
        return result;
    }

    public static Bitmap createBitmap(Bitmap source, int x, int y, int width, int height,
            Matrix matrix, boolean filter) {
        Objects.requireNonNull(source, "source");
        if (x < 0 || y < 0 || width <= 0 || height <= 0
                || (long) x + width > source.width || (long) y + height > source.height) {
            throw new IllegalArgumentException("invalid source subset");
        }
        if (source.recycled) { throw new IllegalArgumentException("cannot transform a recycled source"); }
        boolean identity = matrix == null || matrix.isIdentity();
        if (!source.mutable && x == 0 && y == 0 && width == source.width && height == source.height && identity) {
            return source;
        }
        RectF bounds = new RectF(0, 0, width, height);
        java.awt.geom.AffineTransform transform = new java.awt.geom.AffineTransform();
        boolean rectilinear = true;
        if (!identity) {
            rectilinear = matrix.mapRect(bounds);
            transform = matrix.toAffineTransform();
        }
        if (!Float.isFinite(bounds.left) || !Float.isFinite(bounds.top)
                || !Float.isFinite(bounds.right) || !Float.isFinite(bounds.bottom)) {
            throw new IllegalArgumentException("transformed bounds are not finite");
        }
        int targetWidth = Math.round(bounds.width());
        int targetHeight = Math.round(bounds.height());
        pixelCount(targetWidth, targetHeight);
        Bitmap result = new Bitmap(targetWidth, targetHeight, true);
        // AOSP's source-derived createBitmap path restores the source alpha flag
        // after choosing the transformed allocation, including non-rectilinear cases.
        result.alpha = source.alpha;
        result.reshape(targetWidth, targetHeight);
        java.awt.Graphics2D graphics = result.image.createGraphics();
        try {
            graphics.setComposite(java.awt.AlphaComposite.Src);
            graphics.setRenderingHint(java.awt.RenderingHints.KEY_INTERPOLATION, filter
                    ? java.awt.RenderingHints.VALUE_INTERPOLATION_BILINEAR
                    : java.awt.RenderingHints.VALUE_INTERPOLATION_NEAREST_NEIGHBOR);
            graphics.setRenderingHint(java.awt.RenderingHints.KEY_ANTIALIASING, rectilinear
                    ? java.awt.RenderingHints.VALUE_ANTIALIAS_OFF : java.awt.RenderingHints.VALUE_ANTIALIAS_ON);
            graphics.translate(-bounds.left, -bounds.top);
            graphics.transform(transform);
            graphics.drawImage(source.image.getSubimage(x, y, width, height), 0, 0, null);
        } finally { graphics.dispose(); }
        return result;
    }

    public boolean compress(CompressFormat format, int quality, java.io.OutputStream stream) {
        checkLive();
        Objects.requireNonNull(stream, "stream");
        if (quality < 0 || quality > 100) { throw new IllegalArgumentException("quality must be 0..100"); }
        Objects.requireNonNull(format, "format");
        return BitmapEncoder.write(image, format, quality, stream);
    }

    boolean hasOwnedAllocation() { return allocation != null; }

    public int getByteCount() {
        if (recycled) { return 0; }
        requireOwned();
        return width * height * 4;
    }

    public int getAllocationByteCount() {
        if (recycled) { return 0; }
        requireOwned();
        return allocation.length * 4;
    }

    private void requireOwned() {
        if (allocation == null) {
            throw new UnsupportedOperationException("borrowed Java2D raster allocation is not an owned ARGB buffer");
        }
    }

    public void reconfigure(int width, int height, Config config) {
        checkLive();
        int count = pixelCount(width, height);
        if (!mutable) { throw new IllegalStateException("bitmap is immutable"); }
        Objects.requireNonNull(config, "config");
        requireOwned();
        if (count > allocation.length) {
            throw new IllegalArgumentException("bitmap allocation is too small");
        }
        reshape(width, height);
    }

    BufferedImage getDrawingImage() {
        checkWritable();
        return image;
    }

    BufferedImage getAwtBufferedImageImplementation() {
        checkLive();
        return image;
    }

    public static Bitmap createBitmap(int width, int height, Config config) {
        Objects.requireNonNull(config, "config");
        if (width <= 0 || height <= 0) {
            throw new IllegalArgumentException("bitmap dimensions must be positive");
        }
        return new Bitmap(width, height, true);
    }

    public int getWidth() { return width; }
    public int getHeight() { return height; }
    public boolean isMutable() { return mutable; }
    public boolean isRecycled() { return recycled; }

    /** Releases only this wrapper's reference; other owners keep their pixels. */
    public void recycle() {
        recycled = true;
        image = null;
        allocation = null;
    }

    private void checkLive() {
        if (recycled) { throw new IllegalStateException("bitmap has been recycled"); }
    }

    private void checkWritable() {
        checkLive();
        if (!mutable) { throw new IllegalStateException("bitmap is immutable"); }
    }

    private void checkPixel(int x, int y) {
        if (x < 0 || y < 0 || x >= getWidth() || y >= getHeight()) {
            throw new IllegalArgumentException("pixel outside bitmap");
        }
    }

    public int getPixel(int x, int y) {
        checkLive();
        checkPixel(x, y);
        return image.getRGB(x, y);
    }

    public void setPixel(int x, int y, int color) {
        checkWritable();
        checkPixel(x, y);
        image.setRGB(x, y, color);
    }

    private void checkRegion(int[] pixels, int offset, int stride, int x, int y, int width, int height) {
        if (x < 0 || y < 0 || width < 0 || height < 0
                || (long) x + width > getWidth() || (long) y + height > getHeight()
                || Math.abs((long) stride) < width) {
            throw new IllegalArgumentException("invalid bitmap region or stride");
        }
        Objects.requireNonNull(pixels, "pixels");
        long last = (long) offset + (long) (height - 1) * stride;
        long first = Math.min(offset, last);
        long end = Math.max(offset, last) + width;
        if (first < 0 || end > pixels.length) {
            throw new ArrayIndexOutOfBoundsException("pixel array does not contain every row");
        }
    }

    public void getPixels(int[] pixels, int offset, int stride, int x, int y, int width, int height) {
        checkLive();
        // Android's zero-area transfers do not access or validate the array.
        if (width == 0 || height == 0) { return; }
        checkRegion(pixels, offset, stride, x, y, width, height);
        for (int row = 0; row < height; row++) {
            image.getRGB(x, y + row, width, 1, pixels, (int) ((long) offset + (long) row * stride), width);
        }
    }

    public void setPixels(int[] pixels, int offset, int stride, int x, int y, int width, int height) {
        checkWritable();
        if (width == 0 || height == 0) { return; }
        checkRegion(pixels, offset, stride, x, y, width, height);
        for (int row = 0; row < height; row++) {
            image.setRGB(x, y + row, width, 1, pixels, (int) ((long) offset + (long) row * stride), width);
        }
    }
}
