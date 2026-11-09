// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.image.BufferedImage;
import java.util.Objects;

/** ARGB pixel slice of uds-desktop-android-compat 0.1.0; not an Android SDK. */
public final class Bitmap {
    public enum Config { ARGB_8888 }

    private BufferedImage image;
    private final int width;
    private final int height;
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
        return new Bitmap(new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB));
    }

    public int getWidth() { return width; }
    public int getHeight() { return height; }
    public boolean isMutable() { return mutable; }
    public boolean isRecycled() { return recycled; }

    /** Releases only this wrapper's reference; other owners keep their pixels. */
    public void recycle() {
        recycled = true;
        image = null;
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
