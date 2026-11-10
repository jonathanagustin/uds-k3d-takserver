// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.api.commons.graphics;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import javax.imageio.ImageIO;

/** Real software-pixel contracts; no native renderer or complete Android claim. */
public final class CanvasCompatibilityTest {
    private static int checks;
    private static void check(boolean value, String message) {
        checks++;
        if (!value) { throw new AssertionError(message); }
    }
    private static void raises(Class<? extends Throwable> type, Runnable operation) {
        try { operation.run(); } catch (Throwable error) {
            check(type.isInstance(error), "unexpected exception " + error);
            return;
        }
        throw new AssertionError("missing " + type);
    }
    private static Bitmap bitmap(int width, int height) {
        return Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
    }
    private static void bitmapDrawing() {
        Bitmap source = bitmap(2, 2);
        source.setPixels(new int[]{0xffff0000, 0xff00ff00, 0xff0000ff, 0xffffffff}, 0, 2, 0, 0, 2, 2);
        Bitmap target = bitmap(6, 5);
        Canvas canvas = new Canvas(target);
        canvas.drawBitmap(source, 1, 2, null);
        check(target.getPixel(1, 2) == 0xffff0000 && target.getPixel(2, 3) == 0xffffffff, "translated real pixels");
        check(target.getPixel(0, 2) == 0 && target.getPixel(3, 3) == 0, "translation bounds");
        canvas.drawBitmap(source, new Rect(1, 0, 2, 2), new Rect(2, 0, 6, 4), null);
        for (int y = 0; y < 4; y++) {
            for (int x = 2; x < 6; x++) {
                check(target.getPixel(x, y) == (y < 2 ? 0xff00ff00 : 0xffffffff), "cropped nearest-neighbor scaling");
            }
        }
        Bitmap clipped = bitmap(2, 2);
        new Canvas(clipped).drawBitmap(source, null, new RectF(-2, -2, 2, 2), null);
        for (int y = 0; y < 2; y++) {
            for (int x = 0; x < 2; x++) { check(clipped.getPixel(x, y) == 0xffffffff, "target bounds clip scaled content"); }
        }
        Bitmap fractional = bitmap(5, 5);
        new Canvas(fractional).drawBitmap(source, new Rect(1, 0, 2, 1), new RectF(1.25f, 1.25f, 3.25f, 3.25f), null);
        check(fractional.getPixel(2, 2) == 0xff00ff00 && fractional.getPixel(0, 0) == 0
                && fractional.getPixel(4, 4) == 0, "fractional RectF placement retains interior and outer clipping");
        Paint alpha = new Paint(); alpha.setAlpha(128);
        Bitmap one = bitmap(1, 1); one.setPixel(0, 0, 0xffff0000);
        Bitmap destination = bitmap(1, 1); destination.setPixel(0, 0, 0xff0000ff);
        new Canvas(destination).drawBitmap(one, 0, 0, alpha);
        check(destination.getPixel(0, 0) == 0xff80007f, "paint alpha source-over composition");
        one.setPixel(0, 0, 0x80ff0000);
        destination.setPixel(0, 0, 0xff0000ff);
        new Canvas(destination).drawBitmap(one, 0, 0, alpha);
        check(destination.getPixel(0, 0) == 0xff4000bf, "source alpha multiplies paint alpha");
        canvas.drawBitmap(source, null, new Rect(0, 0, 0, 0), null);
        raises(IllegalArgumentException.class, () -> canvas.drawBitmap(source, new Rect(-1, 0, 1, 1), new Rect(0, 0, 2, 2), null));
        raises(IllegalArgumentException.class, () -> canvas.drawBitmap(source, Float.NaN, 0, null));
        source.recycle();
        raises(IllegalStateException.class, () -> canvas.drawBitmap(source, 0, 0, null));
    }
    private static void shapesAndText() {
        Bitmap target = bitmap(120, 60);
        Canvas canvas = new Canvas(target);
        Paint paint = new Paint(); paint.setColor(0xff00ff00);
        canvas.drawRect(new Rect(2, 3, 7, 8), paint);
        check(target.getPixel(2, 3) == 0xff00ff00 && target.getPixel(6, 7) == 0xff00ff00, "filled rectangle coverage");
        check(target.getPixel(7, 7) == 0 && target.getPixel(1, 3) == 0, "rectangle right edge excludes next pixel");
        paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(2); paint.setColor(0xffff0000);
        canvas.drawRect(10, 10, 20, 20, paint);
        check(target.getPixel(10, 10) == 0xffff0000 && target.getPixel(15, 15) == 0, "stroke perimeter without filled center");
        paint.setStyle(Paint.Style.FILL_AND_STROKE); paint.setColor(0x800000ff);
        canvas.drawRect(30, 10, 40, 20, paint);
        check((target.getPixel(30, 15) >>> 24) == 128 && (target.getPixel(35, 15) >>> 24) == 128,
                "fill-and-stroke blends union once");
        paint.setColor(0xffffffff); paint.setStyle(Paint.Style.FILL); paint.setTextSize(20); paint.setAntiAlias(true);
        canvas.drawText("xHELLOy", 1, 6, 4, 48, paint);
        int ink = 0;
        for (int y = 25; y < 49; y++) {
            for (int x = 0; x < 100; x++) { if (target.getPixel(x, y) != 0) { ink++; } }
        }
        check(ink > 50, "substring text produces real glyph pixels above baseline");
        Bitmap left = bitmap(120, 40); Bitmap right = bitmap(120, 40);
        paint.setAntiAlias(false); paint.setTextAlign(Paint.Align.LEFT);
        new Canvas(left).drawText("Hi", 10, 30, paint);
        paint.setTextAlign(Paint.Align.RIGHT);
        float advance = paint.measureText("Hi");
        new Canvas(right).drawText("Hi", 10 + advance, 30, paint);
        int[] a = new int[4800], b = new int[4800];
        left.getPixels(a, 0, 120, 0, 0, 120, 40); right.getPixels(b, 0, 120, 0, 0, 120, 40);
        check(java.util.Arrays.equals(a, b), "text alignment uses the existing Paint advance");
        Bitmap outlined = bitmap(120, 40);
        paint.setTextAlign(Paint.Align.LEFT); paint.setStyle(Paint.Style.FILL_AND_STROKE); paint.setStrokeWidth(2);
        new Canvas(outlined).drawText("Hi", 10, 30, paint);
        int fillInk = 0, outlineInk = 0;
        for (int y = 0; y < 40; y++) {
            for (int x = 0; x < 120; x++) {
                if (left.getPixel(x, y) != 0) { fillInk++; }
                if (outlined.getPixel(x, y) != 0) { outlineInk++; }
            }
        }
        check(outlineInk > fillInk && fillInk > 0, "text stroke expands actual glyph coverage");
        raises(IndexOutOfBoundsException.class, () -> canvas.drawText("Hi", 0, 3, 0, 0, paint));
        raises(IllegalArgumentException.class, () -> paint.setAlpha(256));
        raises(IllegalArgumentException.class, () -> paint.setStrokeWidth(-1));
        raises(IllegalArgumentException.class, () -> canvas.drawRect(0, 0, Float.POSITIVE_INFINITY, 2, paint));
    }
    private static void lifecycle() throws Exception {
        Bitmap target = bitmap(4, 4); Canvas canvas = new Canvas(target);
        target.reconfigure(8, 2, Bitmap.Config.ARGB_8888);
        Paint paint = new Paint(); paint.setColor(0xff123456);
        canvas.drawRect(6, 0, 8, 2, paint);
        check(target.getPixel(7, 1) == 0xff123456, "canvas draws to current reconfigured target view");
        target.recycle();
        raises(IllegalStateException.class, () -> canvas.drawRect(0, 0, 1, 1, paint));
        BufferedImage encoded = new BufferedImage(1, 1, BufferedImage.TYPE_INT_ARGB);
        ByteArrayOutputStream png = new ByteArrayOutputStream(); ImageIO.write(encoded, "png", png);
        byte[] bytes = png.toByteArray();
        Bitmap immutable = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.length);
        raises(IllegalStateException.class, () -> new Canvas(immutable));
        raises(NullPointerException.class, () -> new Canvas(null));
    }
    public static void main(String[] args) throws Exception {
        bitmapDrawing(); shapesAndText(); lifecycle();
        System.out.println("Canvas software pixels: " + checks + " checks passed");
    }
}
