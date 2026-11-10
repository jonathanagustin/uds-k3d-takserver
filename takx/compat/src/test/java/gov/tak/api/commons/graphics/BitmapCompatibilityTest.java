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
        Object allocation = ((java.awt.image.DataBufferByte) oldView.getRaster().getDataBuffer()).getData();
        check(image.getByteCount() == 48 && image.getAllocationByteCount() == 48, "initial byte counts");
        image.reconfigure(2, 2, android.graphics.Bitmap.Config.ARGB_8888);
        check(image.getWidth() == 2 && image.getHeight() == 2 && image.getByteCount() == 16,
                "reconfigure changes logical shape and byte count");
        check(image.getAllocationByteCount() == 48, "shrink retains allocation capacity");
        image.reconfigure(6, 2, android.graphics.Bitmap.Config.ARGB_8888);
        BufferedImage reshaped = view(image);
        check(reshaped.getWidth() == 6 && reshaped.getHeight() == 2, "new marshal view reflects shape");
        check(((java.awt.image.DataBufferByte) reshaped.getRaster().getDataBuffer()).getData() == allocation,
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
        check(((java.awt.image.DataBufferByte) view(reused).getRaster().getDataBuffer()).getData() == allocation,
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
            android.graphics.Paint drawing = new android.graphics.Paint();
            drawing.setColor(0xffffffff);
            new android.graphics.Canvas(borrowed).drawRect(0, 1, 1, 2, drawing);
            check(source.getRGB(0, 1) == 0xffffffff, "canvas updates the actual borrowed color model storage");
            borrowed.recycle();
            check(source.getRGB(1, 0) == 0xffffffff, "borrowed storage survives recycle");
        }
    }

    private static void metadataScalingAndCodecs() throws Exception {
        android.graphics.Bitmap image = bitmap(2, 1);
        image.setPixel(0, 0, 0xffff0000); image.setPixel(1, 0, 0xff0000ff);
        check(image.getConfig() == android.graphics.Bitmap.Config.ARGB_8888 && image.hasAlpha(),
                "owned ARGB configuration includes alpha even when current pixels are opaque");
        android.graphics.Bitmap nearest = android.graphics.Bitmap.createScaledBitmap(image, 3, 1, false);
        check(nearest.isMutable() && nearest.getWidth() == 3 && nearest.getHeight() == 1,
                "scaled destination is a real mutable owned image");
        for (int x = 0; x < 3; x++) {
            int color = nearest.getPixel(x, 0);
            check(color == 0xffff0000 || color == 0xff0000ff, "nearest scaling retains source colors");
        }
        android.graphics.Bitmap smooth = android.graphics.Bitmap.createScaledBitmap(image, 3, 1, true);
        int middle = smooth.getPixel(1, 0);
        check(((middle >> 16) & 255) >= 120 && ((middle >> 16) & 255) <= 135
                && (middle & 255) >= 120 && (middle & 255) <= 135, "bilinear scaling interpolates color");
        android.graphics.Bitmap copy = android.graphics.Bitmap.createScaledBitmap(image, 2, 1, false);
        check(copy != image && copy.isMutable() && copy.getPixel(0, 0) == image.getPixel(0, 0),
                "same-size mutable scaling makes an independent mutable copy");
        copy.setPixel(0, 0, 0xff00ff00);
        check(image.getPixel(0, 0) == 0xffff0000, "scaled destination does not replace source allocation");
        raises(IllegalArgumentException.class, () -> android.graphics.Bitmap.createScaledBitmap(image, 0, 1, false));
        raises(NullPointerException.class, () -> android.graphics.Bitmap.createScaledBitmap(null, 1, 1, false));

        image.setPixel(0, 0, 0x00123456); image.setPixel(1, 0, 0x80123456);
        class Output extends ByteArrayOutputStream {
            boolean closed;
            @Override public void close() { closed = true; }
        }
        Output png0 = new Output(), png100 = new Output();
        check(image.compress(android.graphics.Bitmap.CompressFormat.PNG, 0, png0)
                && image.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, png100), "real PNG encoding succeeds");
        check(!png0.closed && !png100.closed, "encoder does not close caller stream");
        check(Arrays.equals(png0.toByteArray(), png100.toByteArray()), "PNG quality hint is ignored by lossless encoder");
        byte[] png = png0.toByteArray();
        android.graphics.Bitmap decoded = android.graphics.BitmapFactory.decodeByteArray(png, 0, png.length);
        check(decoded.hasAlpha() && decoded.getPixel(0, 0) == 0x00123456 && decoded.getPixel(1, 0) == 0x80123456,
                "PNG round trip preserves transparent RGB and partial alpha");
        check(android.graphics.Bitmap.createScaledBitmap(decoded, 2, 1, true) == decoded,
                "same-size immutable scaling returns original per AOSP identity fast path");
        raises(IllegalArgumentException.class, () -> image.compress(android.graphics.Bitmap.CompressFormat.PNG, -1, png0));
        raises(IllegalArgumentException.class, () -> image.compress(android.graphics.Bitmap.CompressFormat.PNG, 101, png0));
        raises(NullPointerException.class, () -> image.compress(null, 80, png0));
        raises(NullPointerException.class, () -> image.compress(android.graphics.Bitmap.CompressFormat.PNG, 80, null));
        check(!image.compress(android.graphics.Bitmap.CompressFormat.PNG, 80, new java.io.OutputStream() {
            @Override public void write(int value) throws IOException { throw new IOException("failed output"); }
        }), "real output failure returns false");

        android.graphics.Bitmap photograph = bitmap(16, 16);
        for (int y = 0; y < 16; y++) {
            for (int x = 0; x < 16; x++) { photograph.setPixel(x, y, 0xff000000 | (x * 17 << 16) | (y * 17 << 8) | ((x + y) % 16 * 17)); }
        }
        Output low = new Output(), high = new Output();
        check(photograph.compress(android.graphics.Bitmap.CompressFormat.JPEG, 0, low)
                && photograph.compress(android.graphics.Bitmap.CompressFormat.JPEG, 100, high), "JPEG encodes both quality extremes");
        check(!Arrays.equals(low.toByteArray(), high.toByteArray()), "JPEG quality affects actual encoded output");
        byte[] jpeg = high.toByteArray();
        BufferedImage independentlyDecoded = ImageIO.read(new ByteArrayInputStream(jpeg));
        check(independentlyDecoded != null && independentlyDecoded.getWidth() == 16
                && !independentlyDecoded.getColorModel().hasAlpha(), "independent JDK JPEG reader accepts opaque output");
        check(!high.closed, "JPEG writer retains caller stream ownership");
        android.graphics.BitmapFactory.Options options = new android.graphics.BitmapFactory.Options();
        options.inMutable = true;
        android.graphics.Bitmap opaque = android.graphics.BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, options);
        check(!opaque.hasAlpha() && opaque.getConfig() == android.graphics.Bitmap.Config.ARGB_8888,
                "JPEG decoded ARGB configuration retains opaque metadata");
        opaque.setPixel(0, 0, 0x00123456);
        check(opaque.getPixel(0, 0) == 0xff123456, "opaque destination treats pixel writes as opaque");
        android.graphics.Bitmap scaledOpaque = android.graphics.Bitmap.createScaledBitmap(opaque, 4, 4, true);
        check(!scaledOpaque.hasAlpha() && scaledOpaque.getAllocationByteCount() == 64,
                "scaling preserves opaque metadata and creates bounded owned storage");
        Object allocation = ((java.awt.image.DataBufferByte) view(opaque).getRaster().getDataBuffer()).getData();
        options.inBitmap = opaque;
        check(android.graphics.BitmapFactory.decodeByteArray(png, 0, png.length, options) == opaque
                && opaque.hasAlpha() && opaque.getPixel(1, 0) == 0x80123456,
                "pooled opaque-to-alpha decode updates actual destination color model");
        check(((java.awt.image.DataBufferByte) view(opaque).getRaster().getDataBuffer()).getData() == allocation
                && opaque.getAllocationByteCount() == 1024, "alpha metadata transition retains exact owned allocation");
        check(android.graphics.BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, options) == opaque && !opaque.hasAlpha(),
                "pooled alpha-to-opaque decode restores opaque metadata");

        android.graphics.Bitmap transparentRed = bitmap(8, 8);
        for (int y = 0; y < 8; y++) {
            for (int x = 0; x < 8; x++) { transparentRed.setPixel(x, y, 0x00ff0000); }
        }
        Output rgbOnly = new Output();
        check(transparentRed.compress(android.graphics.Bitmap.CompressFormat.JPEG, 100, rgbOnly), "JPEG accepts alpha source");
        BufferedImage rgbDecoded = ImageIO.read(new ByteArrayInputStream(rgbOnly.toByteArray()));
        int red = rgbDecoded.getRGB(4, 4);
        check(((red >> 16) & 255) > 250 && (red & 255) < 5 && ((red >> 8) & 255) < 5,
                "desktop JPEG codec discards alpha rather than compositing transparent pixels over black");
        transparentRed.recycle();
        raises(IllegalStateException.class, () -> transparentRed.compress(android.graphics.Bitmap.CompressFormat.PNG, 80, rgbOnly));
        raises(IllegalArgumentException.class, () -> android.graphics.Bitmap.createScaledBitmap(transparentRed, 1, 1, false));

        for (int type : new int[]{BufferedImage.TYPE_INT_RGB, BufferedImage.TYPE_BYTE_INDEXED, BufferedImage.TYPE_INT_ARGB_PRE}) {
            BufferedImage backing = new BufferedImage(2, 2, type);
            backing.setRGB(0, 0, 0xffabcdef);
            Bitmap portable = MarshalManager.marshal(backing, BufferedImage.class, Bitmap.class);
            android.graphics.Bitmap borrowed = MarshalManager.marshal(portable, Bitmap.class, android.graphics.Bitmap.class);
            check(borrowed.getConfig() == null && borrowed.hasAlpha() == backing.getColorModel().hasAlpha(),
                    "borrowed metadata reports actual alpha model without inventing Android config");
            android.graphics.Bitmap scaled = android.graphics.Bitmap.createScaledBitmap(borrowed, 4, 4, false);
            check(scaled.getConfig() == android.graphics.Bitmap.Config.ARGB_8888
                    && scaled.getPixel(0, 0) == borrowed.getPixel(0, 0), "borrowed scaling converts real source colors into owned ARGB");
            check(view(borrowed) == backing, "borrowed scaling preserves original backing identity");
            Output encoded = new Output();
            check(borrowed.compress(android.graphics.Bitmap.CompressFormat.PNG, 80, encoded)
                    && ImageIO.read(new ByteArrayInputStream(encoded.toByteArray())) != null, "borrowed storage can encode without detaching");
        }
    }

    private static void cropAndTransform() throws Exception {
        android.graphics.Bitmap source = bitmap(3, 2);
        int[] colors = {0xffff0000, 0xff00ff00, 0xff0000ff, 0xffffff00, 0xff00ffff, 0xffff00ff};
        source.setPixels(colors, 0, 3, 0, 0, 3, 2);
        android.graphics.Bitmap crop = android.graphics.Bitmap.createBitmap(source, 1, 0, 2, 2, null, false);
        check(crop.isMutable() && crop.getWidth() == 2 && crop.getHeight() == 2
                && crop.getPixel(0, 0) == colors[1] && crop.getPixel(1, 1) == colors[5], "untransformed subset copies real pixels");
        crop.setPixel(0, 0, 0);
        check(source.getPixel(1, 0) == colors[1], "cropped image has independent owned storage");
        android.graphics.Matrix flip = new android.graphics.Matrix(); flip.setScale(1f, -1f);
        // Exact operation used by the pinned GLImageCache before recycling its input.
        android.graphics.Bitmap flipped = android.graphics.Bitmap.createBitmap(source, 0, 0, 3, 2, flip, false);
        for (int y = 0; y < 2; y++) {
            for (int x = 0; x < 3; x++) { check(flipped.getPixel(x, y) == colors[(1 - y) * 3 + x], "GLImageCache vertical-flip pixel pattern"); }
        }
        android.graphics.Bitmap restored = android.graphics.Bitmap.createBitmap(flipped, 0, 0, 3, 2, flip, false);
        int[] pixels = new int[6]; restored.getPixels(pixels, 0, 3, 0, 0, 3, 2);
        check(Arrays.equals(colors, pixels), "two negative-scale flips restore all pixels");
        android.graphics.Matrix move = new android.graphics.Matrix(); move.setTranslate(17, -9);
        android.graphics.Bitmap translated = android.graphics.Bitmap.createBitmap(source, 1, 0, 2, 2, move, false);
        check(translated.getWidth() == 2 && translated.getHeight() == 2 && translated.getPixel(0, 0) == colors[1]
                && translated.getPixel(1, 1) == colors[5], "mapped-bounds origin is removed without translation padding");
        android.graphics.Matrix turn = new android.graphics.Matrix();
        turn.setValues(new float[]{0,-1,0, 1,0,0, 0,0,1});
        android.graphics.Bitmap rotated = android.graphics.Bitmap.createBitmap(source, 0, 0, 3, 2, turn, false);
        check(rotated.getWidth() == 2 && rotated.getHeight() == 3, "quarter-turn swaps transformed bounds");
        int[] expected = {colors[3], colors[0], colors[4], colors[1], colors[5], colors[2]};
        pixels = new int[6]; rotated.getPixels(pixels, 0, 2, 0, 0, 2, 3);
        check(Arrays.equals(expected, pixels), "quarter-turn pixel orientation");
        android.graphics.Matrix stretch = new android.graphics.Matrix(); stretch.setScale(1.5f, 1);
        android.graphics.Bitmap interpolated = android.graphics.Bitmap.createBitmap(source, 0, 0, 2, 1, stretch, true);
        int center = interpolated.getPixel(1, 0);
        check(interpolated.getWidth() == 3 && ((center >> 16) & 255) > 100 && ((center >> 8) & 255) > 100,
                "filtered transformed subset bilinearly combines source colors");
        android.graphics.Bitmap unfiltered = android.graphics.Bitmap.createBitmap(source, 0, 0, 2, 1, stretch, false);
        check(unfiltered.getPixel(1, 0) == colors[0] || unfiltered.getPixel(1, 0) == colors[1],
                "unfiltered transformed subset retains nearest source color");
        android.graphics.Matrix shear = new android.graphics.Matrix();
        shear.setValues(new float[]{1,.5f,0, 0,1,0, 0,0,1});
        android.graphics.Bitmap sheared = android.graphics.Bitmap.createBitmap(source, 0, 0, 2, 2, shear, false);
        check(sheared.getWidth() == 3 && sheared.getHeight() == 2 && sheared.hasAlpha(),
                "non-rectilinear transform uses rounded mapped bounds and preserves source alpha flag");
        int filled = 0, empty = 0;
        for (int y = 0; y < 2; y++) {
            for (int x = 0; x < 3; x++) {
                if ((sheared.getPixel(x, y) >>> 24) == 0) { empty++; } else { filled++; }
            }
        }
        check(filled > 0 && empty > 0, "sheared image has real polygon coverage and unpainted corners");
        android.graphics.Matrix identity = new android.graphics.Matrix();
        android.graphics.Bitmap mutableCopy = android.graphics.Bitmap.createBitmap(source, 0, 0, 3, 2, identity, true);
        check(mutableCopy != source && mutableCopy.isMutable(), "mutable full-source identity creates independent mutable result");
        ByteArrayOutputStream png = new ByteArrayOutputStream();
        source.compress(android.graphics.Bitmap.CompressFormat.PNG, 80, png);
        byte[] encoded = png.toByteArray();
        android.graphics.Bitmap immutable = android.graphics.BitmapFactory.decodeByteArray(encoded, 0, encoded.length);
        check(android.graphics.Bitmap.createBitmap(immutable, 0, 0, 3, 2, null, false) == immutable
                && android.graphics.Bitmap.createBitmap(immutable, 0, 0, 3, 2, identity, true) == immutable,
                "immutable full-source null or identity Matrix preserves instance");
        check(android.graphics.Bitmap.createBitmap(immutable, 1, 0, 2, 2, identity, false) != immutable,
                "immutable partial subset cannot take identity instance shortcut");
        android.graphics.Bitmap movedImmutable = android.graphics.Bitmap.createBitmap(immutable, 0, 0, 3, 2, move, false);
        check(movedImmutable != immutable && movedImmutable.isMutable(), "nonidentity translation creates mutable result even when output pixels match");
        raises(IllegalArgumentException.class, () -> android.graphics.Bitmap.createBitmap(source, -1, 0, 1, 1, null, false));
        raises(IllegalArgumentException.class, () -> android.graphics.Bitmap.createBitmap(source, 0, 0, 0, 1, null, false));
        raises(IllegalArgumentException.class, () -> android.graphics.Bitmap.createBitmap(source, 1, 0, Integer.MAX_VALUE, 1, null, false));
        raises(NullPointerException.class, () -> android.graphics.Bitmap.createBitmap(null, 0, 0, 1, 1, null, false));
        android.graphics.Matrix singular = new android.graphics.Matrix(); singular.setScale(0, 1);
        raises(IllegalArgumentException.class, () -> android.graphics.Bitmap.createBitmap(source, 0, 0, 3, 2, singular, false));
        android.graphics.Matrix overflow = new android.graphics.Matrix(); overflow.setScale(Float.MAX_VALUE, 1);
        raises(IllegalArgumentException.class, () -> android.graphics.Bitmap.createBitmap(source, 0, 0, 3, 2, overflow, false));
        check(source.getPixel(0, 0) == colors[0] && source.getWidth() == 3, "invalid transforms do not change source pixels or shape");
        source.recycle();
        check(flipped.getPixel(0, 0) == colors[3], "transformed pixels survive original source recycling");
        raises(IllegalArgumentException.class, () -> android.graphics.Bitmap.createBitmap(source, 0, 0, 3, 2, flip, false));

        for (int type : new int[]{BufferedImage.TYPE_INT_RGB, BufferedImage.TYPE_BYTE_INDEXED, BufferedImage.TYPE_INT_ARGB_PRE}) {
            BufferedImage backing = new BufferedImage(3, 2, type);
            backing.setRGB(1, 0, 0xff000000); backing.setRGB(1, 1, 0xffffffff);
            Bitmap portable = MarshalManager.marshal(backing, BufferedImage.class, Bitmap.class);
            android.graphics.Bitmap borrowed = MarshalManager.marshal(portable, Bitmap.class, android.graphics.Bitmap.class);
            android.graphics.Bitmap result = android.graphics.Bitmap.createBitmap(borrowed, 1, 0, 1, 2, flip, false);
            check(result.getPixel(0, 0) == backing.getRGB(1, 1) && result.getPixel(0, 1) == backing.getRGB(1, 0),
                    "borrowed layout crop/flip converts actual pixel colors");
            check(result.getConfig() == android.graphics.Bitmap.Config.ARGB_8888
                    && result.hasAlpha() == borrowed.hasAlpha(), "transformed borrowed result owns ARGB and preserves alpha metadata");
            check(view(borrowed) == backing && borrowed.getWidth() == 3, "borrowed source backing identity and shape survive transform");
            android.graphics.Bitmap opaqueShear = android.graphics.Bitmap.createBitmap(borrowed, 0, 0, 3, 2, shear, true);
            check(opaqueShear.hasAlpha() == borrowed.hasAlpha(), "AOSP final source alpha flag applies even to non-rectilinear transform");
        }
    }

    public static void main(String[] args) throws Exception {
        pixels(); decode(); marshal(); lifecycleAndBounds(); ownedReuse(); borrowedReuse(); metadataScalingAndCodecs(); cropAndTransform();
        System.out.println("PASS " + checks + " bitmap/decoder/upstream-marshal checks");
    }
}
