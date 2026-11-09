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

    public static void main(String[] args) throws Exception {
        pixels(); decode(); marshal();
        System.out.println("PASS " + checks + " bitmap/decoder/upstream-marshal checks");
    }
}
