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

    private BufferedImage image;
    private int width;
    private int height;
    private int[] allocation;
    private final boolean mutable;
    private boolean recycled;

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
    }

    private Bitmap(int width, int height, boolean mutable) {
        int count = pixelCount(width, height);
        this.allocation = new int[count];
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
        int[] masks = {0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000};
        DataBufferInt buffer = new DataBufferInt(allocation, allocation.length);
        WritableRaster raster = Raster.createPackedRaster(buffer, width, height, width, masks, null);
        image = new BufferedImage(new DirectColorModel(32, masks[0], masks[1], masks[2], masks[3]),
                raster, false, null);
        this.width = width;
        this.height = height;
    }

    static Bitmap decoded(int width, int height, int[] pixels, boolean mutable) {
        Bitmap result = new Bitmap(width, height, mutable);
        System.arraycopy(pixels, 0, result.allocation, 0, pixels.length);
        return result;
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
