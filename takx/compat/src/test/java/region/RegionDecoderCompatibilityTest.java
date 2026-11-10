// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import javax.imageio.ImageIO;

public final class RegionDecoderCompatibilityTest {
    private static int checks;
    private static void check(boolean valid) { checks++; if (!valid) throw new AssertionError("check " + checks); }
    private static void fails(Class<? extends Throwable> kind, Throwing action) {
        try { action.run(); throw new AssertionError("expected " + kind.getName()); }
        catch (Throwable error) { if (!kind.isInstance(error)) throw new AssertionError(error); checks++; }
    }
    private static Object allocation(Bitmap bitmap) throws ReflectiveOperationException {
        java.lang.reflect.Field field = Bitmap.class.getDeclaredField("allocation");
        field.setAccessible(true);
        return field.get(bitmap);
    }
    private interface Throwing { void run() throws Exception; }
    private static final class Tracked extends ByteArrayInputStream {
        boolean closed;
        Tracked(byte[] bytes) { super(bytes); }
        @Override public void close() { closed = true; }
    }
    private static int color(int x, int y) { return 0xff000000 | x * 19 << 16 | y * 29 << 8 | (x + y); }
    private static byte[] encoded(BufferedImage image, String format) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        check(ImageIO.write(image, format, output));
        return output.toByteArray();
    }
    private static void pixels(Bitmap bitmap, BufferedImage source, int x, int y) {
        for (int row = 0; row < bitmap.getHeight(); row++) for (int column = 0; column < bitmap.getWidth(); column++) {
            check(bitmap.getPixel(column, row) == source.getRGB(x + column, y + row));
        }
    }
    public static void main(String[] args) throws Exception {
        BufferedImage source = new BufferedImage(9, 7, BufferedImage.TYPE_INT_ARGB);
        for (int y = 0; y < 7; y++) for (int x = 0; x < 9; x++) source.setRGB(x, y, color(x, y));
        source.setRGB(2, 2, 0x40112233);
        byte[] png = encoded(source, "PNG");
        Tracked stream = new Tracked(png);
        BitmapRegionDecoder decoder = BitmapRegionDecoder.newInstance(stream, true);
        check(!stream.closed && stream.available() == 0); stream.close();
        check(decoder.getWidth() == 9 && decoder.getHeight() == 7 && !decoder.isRecycled());
        Bitmap crop = decoder.decodeRegion(new Rect(2, 1, 6, 4), null);
        check(crop.getWidth() == 4 && crop.getHeight() == 3 && !crop.isMutable()); pixels(crop, source, 2, 1);
        pixels(decoder.decodeRegion(new Rect(7, 5, 9, 7), null), source, 7, 5);
        pixels(decoder.decodeRegion(new Rect(0, 0, 2, 2), null), source, 0, 0);
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = 3; options.inScaled = false;
        Bitmap sample = decoder.decodeRegion(new Rect(0, 0, 9, 7), options);
        check(sample.getWidth() == 3 && sample.getHeight() == 2 && options.outWidth == 3 && options.outHeight == 2);
        for (int y = 0; y < 2; y++) for (int x = 0; x < 3; x++) check(sample.getPixel(x, y) == source.getRGB(1 + x * 3, 1 + y * 3));
        options.inScaled = true;
        check(decoder.decodeRegion(new Rect(0, 0, 9, 7), options).getPixel(0, 0) == sample.getPixel(0, 0));
        options.inSampleSize = Integer.MAX_VALUE;
        sample = decoder.decodeRegion(new Rect(0, 0, 9, 7), options);
        check(sample.getWidth() == 1 && sample.getHeight() == 1 && sample.getPixel(0, 0) == source.getRGB(4, 3));
        options.inSampleSize = -3;
        check(decoder.decodeRegion(new Rect(0, 0, 9, 7), options).getWidth() == 9);
        options.inSampleSize = 1; options.inJustDecodeBounds = true; options.inMutable = true;
        Bitmap bounds = decoder.decodeRegion(new Rect(1, 1, 4, 3), options);
        check(bounds != null && !bounds.isMutable() && options.outWidth == 3 && options.outHeight == 2);
        options.inJustDecodeBounds = false;
        Bitmap padded = decoder.decodeRegion(new Rect(-2, -1, 3, 3), options);
        check(padded.getWidth() == 5 && padded.getHeight() == 4);
        check(padded.getPixel(0, 0) == 0 && padded.getPixel(1, 2) == 0);
        check(padded.getPixel(2, 1) == source.getRGB(0, 0));
        check(padded.getPixel(4, 3) == source.getRGB(2, 2));
        Bitmap rightPad = decoder.decodeRegion(new Rect(7, 5, 12, 9), null);
        check(rightPad.getWidth() == 5 && rightPad.getHeight() == 4 && rightPad.getPixel(2, 2) == 0);
        check(rightPad.getPixel(0, 0) == source.getRGB(7, 5));
        options.inSampleSize = 2;
        padded = decoder.decodeRegion(new Rect(-2, -2, 5, 5), options);
        check(padded.getWidth() == 3 && padded.getHeight() == 3 && padded.getPixel(0, 0) == 0);
        check(padded.getPixel(1, 1) == source.getRGB(1, 1));
        options.inSampleSize = 1;
        Bitmap target = Bitmap.createBitmap(5, 4, Bitmap.Config.ARGB_8888);
        for (int y = 0; y < 4; y++) for (int x = 0; x < 5; x++) target.setPixel(x, y, 0xff556677);
        Object allocation = allocation(target);
        int capacity = target.getAllocationByteCount(); options.inBitmap = target;
        options.inJustDecodeBounds = true;
        Bitmap reused = decoder.decodeRegion(new Rect(2, 1, 4, 3), options);
        options.inJustDecodeBounds = false;
        check(reused == target && reused.getWidth() == 5 && reused.getHeight() == 4 && reused.getAllocationByteCount() == capacity);
        check(allocation(target) == allocation);
        check(options.outWidth == 2 && options.outHeight == 2);
        check(target.getPixel(0, 0) == source.getRGB(2, 1) && target.getPixel(4, 3) == 0xff556677);
        Bitmap small = Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888); options.inBitmap = small;
        check(decoder.decodeRegion(new Rect(0, 0, 9, 7), options) == small);
        pixels(small, source, 0, 0); check(options.outWidth == 9 && options.outHeight == 7);
        options.inBitmap = bounds;
        fails(IllegalArgumentException.class, () -> decoder.decodeRegion(new Rect(0, 0, 2, 2), options));
        options.inBitmap = new Bitmap(new BufferedImage(2, 2, BufferedImage.TYPE_INT_ARGB));
        fails(IllegalArgumentException.class, () -> decoder.decodeRegion(new Rect(0, 0, 2, 2), options));
        options.inBitmap = small; small.recycle();
        fails(IllegalArgumentException.class, () -> decoder.decodeRegion(new Rect(0, 0, 2, 2), options));
        options.inBitmap = null;
        for (Rect outside : new Rect[] {new Rect(-3, 1, 0, 3), new Rect(9, 0, 11, 2), new Rect(0, 7, 2, 9)}) {
            fails(IllegalArgumentException.class, () -> decoder.decodeRegion(outside, options));
        }
        check(decoder.decodeRegion(new Rect(4, 3, 2, 1), options) == null && options.outWidth == -1);
        fails(NullPointerException.class, () -> decoder.decodeRegion(null, options));
        decoder.recycle(); decoder.recycle(); check(decoder.isRecycled());
        fails(IllegalStateException.class, decoder::getWidth); fails(IllegalStateException.class, decoder::getHeight);
        fails(IllegalStateException.class, () -> decoder.decodeRegion(new Rect(0, 0, 1, 1), null));
        check(BitmapRegionDecoder.newInstance((java.io.InputStream) null) == null);
        Tracked invalid = new Tracked(new byte[] {1, 2, 3});
        fails(IOException.class, () -> BitmapRegionDecoder.newInstance(invalid)); check(!invalid.closed);
        fails(IOException.class, () -> BitmapRegionDecoder.newInstance(new java.io.InputStream() {
            public int read() throws IOException { throw new IOException("injected input failure"); }
        }));
        fails(ArrayIndexOutOfBoundsException.class, () -> BitmapRegionDecoder.newInstance(png, -1, 2));
        fails(ArrayIndexOutOfBoundsException.class, () -> BitmapRegionDecoder.newInstance(png, 1, Integer.MAX_VALUE));
        byte[] surrounded = new byte[png.length + 8]; System.arraycopy(png, 0, surrounded, 4, png.length);
        BitmapRegionDecoder ranged = BitmapRegionDecoder.newInstance(surrounded, 4, png.length, false);
        java.util.Arrays.fill(surrounded, (byte) 0); check(ranged.decodeRegion(new Rect(0, 0, 1, 1), null).getPixel(0, 0) == source.getRGB(0, 0)); ranged.recycle();
        Tracked positioned = new Tracked(new byte[png.length + 4]);
        byte[] content = new byte[png.length + 4]; System.arraycopy(png, 0, content, 4, png.length);
        positioned = new Tracked(content); check(positioned.skip(4) == 4);
        BitmapRegionDecoder fromPosition = BitmapRegionDecoder.newInstance(positioned); check(!positioned.closed && fromPosition.getWidth() == 9); fromPosition.recycle();
        Path path = Files.createTempFile("region-", ".png");
        try { Files.write(path, png); BitmapRegionDecoder file = BitmapRegionDecoder.newInstance(path.toString(), false); Files.delete(path); check(file.getHeight() == 7); file.recycle(); }
        finally { Files.deleteIfExists(path); }
        BufferedImage rgb = new BufferedImage(9, 7, BufferedImage.TYPE_INT_RGB);
        for (int y = 0; y < 7; y++) for (int x = 0; x < 9; x++) rgb.setRGB(x, y, 0xff4488cc);
        byte[] jpeg = encoded(rgb, "JPEG");
        BitmapRegionDecoder jpegDecoder = BitmapRegionDecoder.newInstance(jpeg, 0, jpeg.length);
        options.inSampleSize = 2;
        Bitmap jpegFull = jpegDecoder.decodeRegion(new Rect(0, 0, 9, 7), options);
        check(jpegFull.getWidth() == 5 && jpegFull.getHeight() == 4 && !jpegFull.hasAlpha());
        Bitmap jpegCrop = jpegDecoder.decodeRegion(new Rect(1, 1, 8, 6), options);
        check(jpegCrop.getWidth() == 3 && jpegCrop.getHeight() == 2);
        int actualColor = jpegCrop.getPixel(0, 0); check(Math.abs((actualColor >> 16 & 255) - 0x44) < 4 && Math.abs((actualColor >> 8 & 255) - 0x88) < 4);
        options.inSampleSize = 1; options.inPreferredConfig = Bitmap.Config.RGB_565;
        Bitmap jpeg565 = jpegDecoder.decodeRegion(new Rect(0, 0, 9, 7), options);
        check(jpeg565.getConfig() == Bitmap.Config.RGB_565 && !jpeg565.hasAlpha() && jpeg565.getByteCount() == 126);
        BitmapFactory.Options factory565 = new BitmapFactory.Options(); factory565.inPreferredConfig = Bitmap.Config.RGB_565;
        check(BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, factory565).getConfig() == Bitmap.Config.RGB_565);
        Bitmap preserveAlpha = BitmapFactory.decodeByteArray(png, 0, png.length, factory565);
        check(preserveAlpha.getConfig() == Bitmap.Config.ARGB_8888 && preserveAlpha.getPixel(2, 2) == 0x40112233);
        Bitmap fixed565 = Bitmap.createBitmap(3, 3, Bitmap.Config.RGB_565);
        options.inBitmap = fixed565;
        Object allocation565 = allocation(fixed565);
        check(jpegDecoder.decodeRegion(new Rect(0, 0, 2, 2), options) == fixed565);
        check(fixed565.getConfig() == Bitmap.Config.RGB_565 && fixed565.getWidth() == 3 && allocation(fixed565) == allocation565);
        jpegDecoder.recycle(); options.inBitmap = null;
        BufferedImage gray = new BufferedImage(5, 3, BufferedImage.TYPE_BYTE_GRAY);
        for (int y = 0; y < 3; y++) for (int x = 0; x < 5; x++) gray.getRaster().setSample(x, y, 0, (x + y * 5) * 17);
        byte[] grayPng = encoded(gray, "PNG");
        BitmapFactory.Options maskOptions = new BitmapFactory.Options(); maskOptions.inPreferredConfig = Bitmap.Config.ALPHA_8;
        Bitmap mask = BitmapFactory.decodeByteArray(grayPng, 0, grayPng.length, maskOptions);
        check(mask.getConfig() == Bitmap.Config.ALPHA_8 && mask.hasAlpha() && mask.getByteCount() == 15);
        check(mask.getPixel(3, 1) == 0x88000000);
        Bitmap colorRequest = BitmapFactory.decodeByteArray(png, 0, png.length, maskOptions);
        check(colorRequest.getConfig() == Bitmap.Config.ARGB_8888 && colorRequest.getPixel(2, 2) == 0x40112233);
        BitmapRegionDecoder grayDecoder = BitmapRegionDecoder.newInstance(grayPng, 0, grayPng.length);
        maskOptions.inSampleSize = 2;
        Bitmap sampledMask = grayDecoder.decodeRegion(new Rect(0, 0, 5, 3), maskOptions);
        check(sampledMask.getConfig() == Bitmap.Config.ALPHA_8 && sampledMask.getWidth() == 2 && sampledMask.getHeight() == 1);
        check(sampledMask.getPixel(0, 0) == 0x66000000 && sampledMask.getPixel(1, 0) == 0x88000000);
        Bitmap fixedMask = Bitmap.createBitmap(3, 3, Bitmap.Config.ALPHA_8);
        fixedMask.setPixel(2, 2, 0x7f000000); maskOptions.inBitmap = fixedMask; maskOptions.inPreferredConfig = Bitmap.Config.ARGB_8888;
        check(grayDecoder.decodeRegion(new Rect(0, 0, 5, 3), maskOptions) == fixedMask);
        check(fixedMask.getPixel(0, 0) == 0x66000000 && fixedMask.getPixel(2, 2) == 0x7f000000);
        grayDecoder.recycle();
        BufferedImage gradient = new BufferedImage(9, 7, BufferedImage.TYPE_INT_RGB);
        for (int y = 0; y < 7; y++) for (int x = 0; x < 9; x++) gradient.setRGB(x, y, color(x, y));
        byte[] gradientJpeg = encoded(gradient, "JPEG");
        BufferedImage jpegReference = ImageIO.read(new ByteArrayInputStream(gradientJpeg));
        BitmapRegionDecoder gradientDecoder = BitmapRegionDecoder.newInstance(gradientJpeg, 0, gradientJpeg.length);
        BitmapFactory.Options gradientOptions = new BitmapFactory.Options(); gradientOptions.inSampleSize = 2;
        Bitmap gradientSample = gradientDecoder.decodeRegion(new Rect(0, 0, 9, 7), gradientOptions);
        check(gradientSample.getPixel(4, 3) == jpegReference.getRGB(8, 6));
        check(gradientSample.getPixel(0, 0) == jpegReference.getRGB(0, 0));
        Bitmap gradientFactory = BitmapFactory.decodeByteArray(gradientJpeg, 0, gradientJpeg.length, gradientOptions);
        check(gradientFactory.getPixel(4, 3) == jpegReference.getRGB(8, 6)); gradientDecoder.recycle();
        byte[] gif = encoded(rgb, "GIF"); fails(IOException.class, () -> BitmapRegionDecoder.newInstance(gif, 0, gif.length));
        byte[] badPixels = png.clone();
        for (int offset = 8; offset + 12 < badPixels.length;) {
            int length = java.nio.ByteBuffer.wrap(badPixels, offset, 4).getInt();
            if (new String(badPixels, offset + 4, 4, java.nio.charset.StandardCharsets.US_ASCII).equals("IDAT")) {
                badPixels[offset + 8 + length / 2] ^= 0x7f; break;
            }
            offset += length + 12;
        }
        BitmapRegionDecoder corrupt = BitmapRegionDecoder.newInstance(badPixels, 0, badPixels.length);
        BitmapFactory.Options corruptOptions = new BitmapFactory.Options();
        check(corrupt.decodeRegion(new Rect(0, 0, 9, 7), corruptOptions) == null && corruptOptions.outWidth == -1);
        corrupt.recycle();
        // Factory shares the same verified dimension/sampling rules, not ignored options.
        options.inSampleSize = 3; options.inBitmap = null;
        Bitmap fullFactory = BitmapFactory.decodeByteArray(png, 0, png.length, options);
        check(fullFactory.getWidth() == 3 && fullFactory.getHeight() == 2 && options.outWidth == 3 && options.outHeight == 2);
        check(fullFactory.getPixel(0, 0) == source.getRGB(1, 1));
        options.inJustDecodeBounds = true; check(BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, options) == null);
        check(options.outWidth == 3 && options.outHeight == 2);
        check(args.length == 1);
        for (String row : Files.readAllLines(Path.of(args[0]))) {
            String[] values = row.split(" ");
            int size = Integer.parseInt(values[0]), requested = Integer.parseInt(values[1]);
            int expected = Integer.parseInt(values[2]), first = Integer.parseInt(values[3]);
            check(BitmapFactory.sampledDimension(size, requested, false) == expected);
            BufferedImage line = new BufferedImage(size, 1, BufferedImage.TYPE_INT_ARGB);
            for (int x = 0; x < size; x++) line.setRGB(x, 0, 0xff000000 | x);
            check(BitmapFactory.sampledImage(line, expected, 1).getRGB(0, 0) == (0xff000000 | first));
        }
        System.out.println("PASS region decoder: " + checks + " checks");
    }
}
