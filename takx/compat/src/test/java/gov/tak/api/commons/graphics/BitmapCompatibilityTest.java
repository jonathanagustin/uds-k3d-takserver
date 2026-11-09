// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.api.commons.graphics;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import javax.imageio.ImageIO;
import gov.tak.platform.marshal.MarshalManager;

/** Executable contracts, including the actual pinned Kernel marshal registry. */
public final class BitmapCompatibilityTest {
    private static int checks;
    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) { throw new AssertionError(message); }
    }
    private static void raises(Class<? extends Throwable> type, Runnable operation) {
        try { operation.run(); } catch (Throwable error) {
            check(type.isInstance(error), "expected " + type + ", got " + error);
            return;
        }
        throw new AssertionError("expected " + type);
    }
    private static android.graphics.Bitmap bitmap(int w, int h) {
        return android.graphics.Bitmap.createBitmap(w, h, android.graphics.Bitmap.Config.ARGB_8888);
    }

    private static void pixels() {
        android.graphics.Bitmap image = bitmap(3, 2);
        check(image.getWidth() == 3 && image.getHeight() == 2, "dimensions");
        check(image.getPixel(0, 0) == 0, "initial transparent pixels");
        int[] colors = {0x00123456, 0x80123456, 0xffabcdef, 0x01020304, 0x00ffffff, 0xffffffff};
        image.setPixels(colors, 0, 3, 0, 0, 3, 2);
        int[] out = new int[6];
        image.getPixels(out, 0, 3, 0, 0, 3, 2);
        check(Arrays.equals(colors, out), "straight-alpha ARGB bits, including transparent RGB");
        image.setPixel(2, 1, 0x7faabbcc);
        check(image.getPixel(2, 1) == 0x7faabbcc, "single pixel alpha");
        int[] flipped = {91, 0xff001122, 0xff334455, 92, 0xff667788, 0xff99aabb, 93};
        image.setPixels(flipped, 4, -3, 1, 0, 2, 2);
        check(image.getPixel(1, 0) == flipped[4] && image.getPixel(2, 1) == flipped[2], "negative input stride and offset");
        int[] target = new int[8]; Arrays.fill(target, 17);
        image.getPixels(target, 5, -3, 1, 0, 2, 2);
        check(target[5] == flipped[4] && target[2] == flipped[1], "negative output stride");
        check(target[0] == 17 && target[1] == 17 && target[4] == 17 && target[7] == 17, "padding untouched");
        raises(IllegalArgumentException.class, () -> bitmap(0, 1));
        raises(IllegalArgumentException.class, () -> bitmap(1, -1));
        raises(NullPointerException.class, () -> android.graphics.Bitmap.createBitmap(1, 1, null));
        raises(IllegalArgumentException.class, () -> image.getPixel(-1, 0));
        raises(IllegalArgumentException.class, () -> image.setPixel(3, 0, 0));
        raises(IllegalArgumentException.class, () -> image.getPixels(out, 0, 1, 0, 0, 2, 1));
        raises(IllegalArgumentException.class, () -> image.setPixels(out, 0, 3, Integer.MAX_VALUE, 0, 2, 1));
        raises(IllegalArgumentException.class, () -> image.getPixels(out, 0, 3, 0, 0, 3, -1));
        raises(ArrayIndexOutOfBoundsException.class, () -> image.setPixels(out, -1, 3, 0, 0, 3, 1));
        raises(ArrayIndexOutOfBoundsException.class, () -> image.getPixels(out, 4, 3, 0, 0, 3, 2));
        raises(ArrayIndexOutOfBoundsException.class, () -> image.setPixels(out, 0, Integer.MIN_VALUE, 0, 0, 1, 2));
        raises(NullPointerException.class, () -> image.setPixels(null, 0, 3, 0, 0, 1, 1));
        raises(IllegalArgumentException.class, () -> image.setPixels(out, 0, 3, 0, -1, 1, 1));
        raises(IllegalArgumentException.class, () -> image.getPixels(out, 0, 3, 0, 1, 1, 2));
        raises(IllegalArgumentException.class, () -> image.setPixels(out, 0, 3, 0, 0, -1, 1));
        raises(ArrayIndexOutOfBoundsException.class, () -> image.getPixels(out, Integer.MAX_VALUE, 3, 0, 0, 1, 1));
        int before = image.getPixel(0, 0);
        raises(ArrayIndexOutOfBoundsException.class, () -> image.setPixels(new int[]{9, 8, 7}, 0, 3, 0, 0, 2, 2));
        check(image.getPixel(0, 0) == before, "invalid later row cannot partially mutate the image");
        int[] padded = {99, 1, 2, 88, 3, 4, 77};
        image.setPixels(padded, 1, 3, 0, 0, 2, 2);
        int[] copied = new int[7]; Arrays.fill(copied, 42);
        image.getPixels(copied, 1, 3, 0, 0, 2, 2);
        check(copied[1] == 1 && copied[2] == 2 && copied[4] == 3 && copied[5] == 4,
                "positive padded stride and nonzero offset");
        check(copied[0] == 42 && copied[3] == 42 && copied[6] == 42, "positive padding untouched");
        image.setPixels(null, -4, 0, -1, -1, 0, 1);
        image.getPixels(null, -4, 0, -1, -1, 1, 0);
        image.setPixels(new int[]{0x12345678}, 0, Integer.MIN_VALUE, 0, 0, 1, 1);
        check(image.getPixel(0, 0) == 0x12345678, "single-row stride arithmetic does not overflow");
    }

    private static final class OwnedStream extends ByteArrayInputStream {
        boolean closed;
        OwnedStream(byte[] bytes) { super(bytes); }
        @Override public void close() throws IOException { closed = true; super.close(); }
    }

    private static void decode() throws Exception {
        BufferedImage backing = new BufferedImage(2, 1, BufferedImage.TYPE_INT_ARGB);
        backing.setRGB(0, 0, 0x40336699); backing.setRGB(1, 0, 0xffabcdef);
        ByteArrayOutputStream encoded = new ByteArrayOutputStream();
        check(ImageIO.write(backing, "png", encoded), "PNG writer exists");
        OwnedStream stream = new OwnedStream(encoded.toByteArray());
        android.graphics.Bitmap image = android.graphics.BitmapFactory.decodeStream(stream, null, null);
        check(image != null && image.getPixel(0, 0) == 0x40336699 && image.getPixel(1, 0) == 0xffabcdef, "PNG colors and alpha");
        check(!stream.closed && stream.available() < encoded.size(), "stream consumed but remains caller-owned");
        byte[] prefixed = new byte[encoded.size() + 3];
        System.arraycopy(encoded.toByteArray(), 0, prefixed, 3, encoded.size());
        OwnedStream positioned = new OwnedStream(prefixed);
        check(positioned.skip(3) == 3, "fixture initial stream position");
        check(android.graphics.BitmapFactory.decodeStream(positioned, null, null).getPixel(1, 0) == 0xffabcdef,
                "decode starts at caller's current position");
        check(!positioned.closed, "positioned stream remains caller-owned");
        check(android.graphics.BitmapFactory.decodeStream(null, null, null) == null, "null stream");
        OwnedStream malformed = new OwnedStream(new byte[]{1, 2, 3});
        check(android.graphics.BitmapFactory.decodeStream(malformed, null, null) == null && !malformed.closed, "malformed stream remains open");
        OwnedStream truncated = new OwnedStream(Arrays.copyOf(encoded.toByteArray(), 16));
        check(android.graphics.BitmapFactory.decodeStream(truncated, null, null) == null && !truncated.closed, "truncated PNG");
        check(android.graphics.BitmapFactory.decodeStream(new java.io.InputStream() {
            @Override public int read() throws IOException { throw new IOException("fixture read failure"); }
        }, null, null) == null, "read IOException");
        raises(IllegalArgumentException.class, () -> android.graphics.BitmapFactory.decodeStream(stream, new Object(), null));
        check(android.graphics.BitmapFactory.decodeFile(null, null) == null, "null path");
        Path file = Files.createTempFile("bitmap-contract-", ".png");
        try {
            Files.write(file, encoded.toByteArray());
            android.graphics.BitmapFactory.Options options = new android.graphics.BitmapFactory.Options();
            options.inPreferredConfig = android.graphics.Bitmap.Config.ARGB_8888;
            image = android.graphics.BitmapFactory.decodeFile(file.toString(), options);
            check(image != null && image.getPixel(0, 0) == backing.getRGB(0, 0), "file decode");
            check(BitmapFactory.decodeFile(file.toFile()).getPixel(1, 0) == 0xffabcdef, "real portable factory valid decode");
            Files.write(file, new byte[]{5, 6});
            check(android.graphics.BitmapFactory.decodeFile(file.toString(), options) == null, "malformed file");
            check(android.graphics.BitmapFactory.decodeFile(file + ".missing", options) == null, "missing file");
        } finally { Files.deleteIfExists(file); }
    }

    private static void marshal() {
        // Bootstrap the actual upstream registration path, not a stand-in registry.
        Bitmap portable = new Bitmap(2, 2);
        portable.setPixel(1, 1, 0x55aabbcc);
        BufferedImage backing = MarshalManager.marshal(portable, Bitmap.class, BufferedImage.class);
        check(backing != null && backing.getRGB(1, 1) == 0x55aabbcc, "portable to actual BufferedImage backing");
        backing.setRGB(0, 0, 0x81020304);
        check(portable.getPixel(0, 0) == 0x81020304, "backing updates portable pixels");
        Bitmap roundtrip = MarshalManager.marshal(backing, BufferedImage.class, Bitmap.class);
        check(roundtrip != null, "actual reflective BufferedImage constructor");
        roundtrip.setPixel(1, 0, 0x00776655);
        check(backing.getRGB(1, 0) == 0x00776655, "roundtrip retains exact backing and transparent RGB");
        check(MarshalManager.marshal(roundtrip, Bitmap.class, BufferedImage.class) == backing, "no backing copy");
        android.graphics.Bitmap nativeBitmap = MarshalManager.marshal(roundtrip, Bitmap.class, android.graphics.Bitmap.class);
        check(nativeBitmap != null && nativeBitmap.getPixel(0, 0) == 0x81020304, "portable to real compatibility bitmap");
        check(MarshalManager.marshal((BufferedImage) null, BufferedImage.class, Bitmap.class) == null, "null marshal");
    }

    private static void lifecycleAndBounds() throws Exception {
        android.graphics.Bitmap created = bitmap(2, 1);
        check(created.isMutable() && !created.isRecycled(), "created image is live and mutable");
        Bitmap portable = new Bitmap(created);
        BufferedImage borrowed = MarshalManager.marshal(portable, Bitmap.class, BufferedImage.class);
        created.setPixel(0, 0, 0xff112233);
        created.recycle();
        created.recycle();
        check(created.isRecycled(), "recycle is idempotent");
        check(created.getWidth() == 2 && created.getHeight() == 1, "dimensions retained after release");
        check(borrowed.getRGB(0, 0) == 0xff112233, "borrowed backing is not destroyed");
        check(MarshalManager.marshal(portable, Bitmap.class, BufferedImage.class) == null,
                "recycled wrapper cannot expose released backing");
        raises(IllegalStateException.class, () -> created.getPixel(0, 0));
        raises(IllegalStateException.class, () -> created.setPixel(0, 0, 1));
        raises(IllegalStateException.class, () -> created.getPixels(null, 0, 0, 0, 0, 0, 0));
        raises(IllegalStateException.class, () -> created.setPixels(null, 0, 0, 0, 0, 0, 0));

        BufferedImage source = new BufferedImage(3, 2, BufferedImage.TYPE_INT_ARGB);
        source.setRGB(1, 1, 0x80123456);
        ByteArrayOutputStream encoded = new ByteArrayOutputStream();
        ImageIO.write(source, "png", encoded);
        byte[] png = encoded.toByteArray();
        byte[] padded = new byte[png.length + 9];
        System.arraycopy(png, 0, padded, 4, png.length);
        android.graphics.BitmapFactory.Options options = new android.graphics.BitmapFactory.Options();
        options.inJustDecodeBounds = true;
        check(android.graphics.BitmapFactory.decodeByteArray(padded, 4, png.length, options) == null,
                "bounds request returns no bitmap");
        check(options.outWidth == 3 && options.outHeight == 2, "bounds from encoded metadata");
        byte[] headerOnly = Arrays.copyOf(png, 33);
        check(android.graphics.BitmapFactory.decodeByteArray(headerOnly, 0, headerOnly.length, options) == null
                && options.outWidth == 3 && options.outHeight == 2,
                "bounds inspection reads PNG header without requiring encoded pixels");
        options.inJustDecodeBounds = false;
        android.graphics.Bitmap decoded = android.graphics.BitmapFactory.decodeByteArray(padded, 4, png.length, options);
        check(decoded != null && !decoded.isMutable(), "default decoding is immutable");
        check(decoded.getPixel(1, 1) == 0x80123456, "byte range decoding preserves alpha and colors");
        raises(IllegalStateException.class, () -> decoded.setPixel(0, 0, 1));
        raises(IllegalStateException.class, () -> decoded.setPixels(null, 0, 0, 0, 0, 0, 0));
        options.inMutable = true;
        android.graphics.Bitmap writable = android.graphics.BitmapFactory.decodeByteArray(png, 0, png.length, options);
        writable.setPixel(1, 1, 0xff987654);
        check(writable.isMutable() && writable.getPixel(1, 1) == 0xff987654, "requested mutable decoding has writable pixels");
        check(decoded.getPixel(1, 1) == 0x80123456, "independent decodes own independent pixels");
        check(android.graphics.BitmapFactory.decodeByteArray(new byte[0], 0, 0, options) == null,
                "empty decode fails");
        check(options.outWidth == -1 && options.outHeight == -1, "failed decode clears stale bounds");
        options.outWidth = 8;
        android.graphics.BitmapFactory.decodeFile(null, options);
        check(options.outWidth == -1 && options.outHeight == -1, "null file clears stale bounds");
        raises(NullPointerException.class, () -> android.graphics.BitmapFactory.decodeByteArray(null, 0, 0));
        raises(ArrayIndexOutOfBoundsException.class, () -> android.graphics.BitmapFactory.decodeByteArray(png, -1, 0));
        raises(ArrayIndexOutOfBoundsException.class, () -> android.graphics.BitmapFactory.decodeByteArray(png, 0, -1));
        raises(ArrayIndexOutOfBoundsException.class, () -> android.graphics.BitmapFactory.decodeByteArray(png, png.length, 1));
        raises(ArrayIndexOutOfBoundsException.class, () -> android.graphics.BitmapFactory.decodeByteArray(png, Integer.MAX_VALUE, 2));
    }

    private static BufferedImage view(android.graphics.Bitmap image) {
        return MarshalManager.marshal(new Bitmap(image), Bitmap.class, BufferedImage.class);
    }

    private static byte[] png(int width, int height, int color) throws IOException {
        BufferedImage image = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) { image.setRGB(x, y, color + x + y); }
        }
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        ImageIO.write(image, "png", output);
        return output.toByteArray();
    }

    private static void ownedReuse() throws Exception {
        android.graphics.Bitmap image = bitmap(4, 3);
        image.setPixel(3, 2, 0xff123456);
        BufferedImage oldView = view(image);
        Object allocation = ((java.awt.image.DataBufferInt) oldView.getRaster().getDataBuffer()).getData();
        check(image.getByteCount() == 48 && image.getAllocationByteCount() == 48, "initial byte counts");
        image.reconfigure(2, 2, android.graphics.Bitmap.Config.ARGB_8888);
        check(image.getWidth() == 2 && image.getHeight() == 2 && image.getByteCount() == 16,
                "reconfigure changes logical shape and byte count");
        check(image.getAllocationByteCount() == 48, "shrink retains allocation capacity");
        image.reconfigure(6, 2, android.graphics.Bitmap.Config.ARGB_8888);
        BufferedImage reshaped = view(image);
        check(reshaped.getWidth() == 6 && reshaped.getHeight() == 2, "new marshal view reflects shape");
        check(((java.awt.image.DataBufferInt) reshaped.getRaster().getDataBuffer()).getData() == allocation,
                "aspect-ratio change retains the exact pixel allocation");
        check(oldView.getWidth() == 4 && oldView.getHeight() == 3, "previous view retains its Java2D dimensions");
        check(image.getPixel(5, 1) == 0xff123456, "reconfiguration does not clear retained pixel storage");
        image.setPixel(0, 0, 0xffabcdef);
        check(oldView.getRGB(0, 0) == 0xffabcdef, "old view continues sharing allocation");
        raises(IllegalArgumentException.class, () -> image.reconfigure(7, 2, android.graphics.Bitmap.Config.ARGB_8888));
        raises(IllegalArgumentException.class, () -> image.reconfigure(Integer.MAX_VALUE, 2, android.graphics.Bitmap.Config.ARGB_8888));
        raises(IllegalArgumentException.class, () -> image.reconfigure(0, 1, android.graphics.Bitmap.Config.ARGB_8888));
        raises(NullPointerException.class, () -> image.reconfigure(1, 1, null));
        check(image.getWidth() == 6 && image.getHeight() == 2 && view(image) == reshaped
                && image.getPixel(0, 0) == 0xffabcdef, "failed reconfiguration leaves shape, view and pixels unchanged");

        byte[] encoded = png(3, 2, 0x80123456);
        android.graphics.BitmapFactory.Options opts = new android.graphics.BitmapFactory.Options();
        com.atakmap.util.ResourcePool<android.graphics.Bitmap> pool = new com.atakmap.util.ResourcePool<>(1);
        check(pool.put(image), "official ResourcePool accepts owned bitmap");
        opts.inBitmap = pool.get();
        android.graphics.Bitmap reused = android.graphics.BitmapFactory.decodeByteArray(encoded, 0, encoded.length, opts);
        check(pool.put(reused) && pool.get() == image, "official ResourcePool retains reused object identity");
        check(reused == image && reused.isMutable(), "reuse returns the same mutable object even without inMutable");
        check(reused.getWidth() == 3 && reused.getHeight() == 2 && reused.getPixel(2, 1) == 0x80123459,
                "reuse decodes real alpha and color pixels into the new shape");
        check(reused.getByteCount() == 24 && reused.getAllocationByteCount() == 48,
                "decode reuse preserves original capacity");
        check(((java.awt.image.DataBufferInt) view(reused).getRaster().getDataBuffer()).getData() == allocation,
                "decode reuse keeps exact destination allocation");
        byte[] wider = png(6, 2, 0xff332211);
        check(android.graphics.BitmapFactory.decodeByteArray(wider, 0, wider.length, opts) == image
                && image.getPixel(5, 1) == 0xff332217, "repeated decode reuses recovered capacity");
        byte[] oversized = png(7, 2, 0xff001122);
        raises(IllegalArgumentException.class, () -> android.graphics.BitmapFactory.decodeByteArray(oversized, 0, oversized.length, opts));
        check(image.getWidth() == 6 && image.getHeight() == 2 && image.getPixel(5, 1) == 0xff332217,
                "failed oversized reuse does not modify destination");
        raises(IllegalArgumentException.class, () -> android.graphics.BitmapFactory.decodeByteArray(new byte[0], 0, 0, opts));
        check(image.getPixel(5, 1) == 0xff332217, "malformed reuse leaves destination pixels unchanged");
        opts.inJustDecodeBounds = true;
        raises(IllegalArgumentException.class, () -> android.graphics.BitmapFactory.decodeByteArray(encoded, 0, encoded.length, opts));
        check(opts.outWidth == 3 && opts.outHeight == 2 && image.getWidth() == 6,
                "AOSP bounds plus inBitmap reports bounds but raises instead of mutating destination");
        opts.inJustDecodeBounds = false;
        Path path = Files.createTempFile("bitmap-reuse", ".png");
        try {
            Files.write(path, oversized);
            check(android.graphics.BitmapFactory.decodeFile(path.toString(), opts) == null,
                    "AOSP file decoder converts incompatible reuse failure to null");
        } finally { Files.delete(path); }
        android.graphics.Bitmap immutable = android.graphics.BitmapFactory.decodeByteArray(encoded, 0, encoded.length);
        opts.inBitmap = immutable;
        raises(IllegalStateException.class, () -> immutable.reconfigure(1, 1, android.graphics.Bitmap.Config.ARGB_8888));
        raises(IllegalArgumentException.class, () -> android.graphics.BitmapFactory.decodeByteArray(encoded, 0, encoded.length, opts));
        check(!immutable.isMutable() && immutable.getWidth() == 3, "immutable reuse input stays unchanged");
        opts.inBitmap = image;
        image.recycle();
        check(image.getByteCount() == 0 && image.getAllocationByteCount() == 0, "AOSP recycled byte counts are zero");
        raises(IllegalStateException.class, () -> image.reconfigure(1, 1, android.graphics.Bitmap.Config.ARGB_8888));
        raises(IllegalArgumentException.class, () -> android.graphics.BitmapFactory.decodeByteArray(encoded, 0, encoded.length, opts));
        check(oldView.getRGB(0, 0) == 0xff332211, "recycling retains separately borrowed shared storage");
        check(android.graphics.BitmapFactory.decodeStream(null, null, opts) == null,
                "AOSP null stream returns before recycled reuse validation");
    }

    private static void borrowedReuse() throws Exception {
        byte[] encoded = png(1, 1, 0xff123456);
        BufferedImage[] sources = {
            new BufferedImage(3, 2, BufferedImage.TYPE_INT_RGB),
            new BufferedImage(3, 2, BufferedImage.TYPE_BYTE_INDEXED),
            new BufferedImage(3, 2, BufferedImage.TYPE_INT_ARGB_PRE),
            new BufferedImage(5, 4, BufferedImage.TYPE_INT_ARGB).getSubimage(1, 1, 3, 2)
        };
        for (BufferedImage source : sources) {
            Bitmap portable = MarshalManager.marshal(source, BufferedImage.class, Bitmap.class);
            android.graphics.Bitmap borrowed = MarshalManager.marshal(portable, Bitmap.class, android.graphics.Bitmap.class);
            check(view(borrowed) == source, "borrowed raster keeps exact backing identity");
            borrowed.setPixel(0, 0, 0xff000000);
            check(source.getRGB(0, 0) == borrowed.getPixel(0, 0), "borrowed writes retain actual color model");
            source.setRGB(1, 0, 0xffffffff);
            check(borrowed.getPixel(1, 0) == source.getRGB(1, 0), "external writes stay visible");
            raises(UnsupportedOperationException.class, () -> borrowed.reconfigure(1, 1, android.graphics.Bitmap.Config.ARGB_8888));
            raises(UnsupportedOperationException.class, borrowed::getAllocationByteCount);
            raises(UnsupportedOperationException.class, borrowed::getByteCount);
            android.graphics.BitmapFactory.Options opts = new android.graphics.BitmapFactory.Options();
            opts.inBitmap = borrowed;
            raises(IllegalArgumentException.class, () -> android.graphics.BitmapFactory.decodeByteArray(encoded, 0, encoded.length, opts));
            check(view(borrowed) == source && borrowed.getWidth() == 3 && borrowed.getHeight() == 2
                    && source.getRGB(1, 0) == 0xffffffff, "unsupported borrowed reuse neither detaches nor mutates");
            borrowed.recycle();
            check(source.getRGB(1, 0) == 0xffffffff, "borrowed storage survives recycle");
        }
    }

    public static void main(String[] args) throws Exception {
        pixels(); decode(); marshal(); lifecycleAndBounds(); ownedReuse(); borrowedReuse();
        System.out.println("PASS " + checks + " bitmap/decoder/upstream-marshal checks");
    }
}
