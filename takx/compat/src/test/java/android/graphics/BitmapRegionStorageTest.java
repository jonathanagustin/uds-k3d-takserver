// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.image.BufferedImage;
import java.awt.image.DataBufferByte;

/** Package-level storage contracts only; not a BitmapRegionDecoder substitute. */
public final class BitmapRegionStorageTest {
    private static int checks;
    private static void check(boolean value, String message) {
        checks++;
        if (!value) { throw new AssertionError(message); }
    }
    private static void raises(Class<? extends Throwable> type, Runnable operation) {
        try { operation.run(); } catch (Throwable error) {
            check(type.isInstance(error), "unexpected " + error); return;
        }
        throw new AssertionError("missing " + type);
    }
    public static void main(String[] args) {
        Bitmap target = Bitmap.decoded(3, 2, new int[]{0xff123456,0xff234567,0xff345678,
                0xff456789,0xff56789a,0xff6789ab}, true, false);
        target.setPixel(2, 1, 0x00010203);
        BufferedImage previous = target.getAwtBufferedImageImplementation();
        Object allocation = ((DataBufferByte) previous.getRaster().getDataBuffer()).getData();
        target.replaceDecodedRegion(new int[]{0x80112233, 0x40445566, 99, 0x20778899, 0x10aabbcc}, 3, 2, 2, true);
        check(target.getWidth() == 3 && target.getHeight() == 2 && target.getAllocationByteCount() == 24,
                "region reuse retains shape and capacity");
        check(((DataBufferByte) target.getAwtBufferedImageImplementation().getRaster().getDataBuffer()).getData() == allocation,
                "region alpha transition retains exact pixel allocation");
        check(target.hasAlpha() && target.getPixel(0,0) == 0x80112233 && target.getPixel(1,1) == 0x10aabbcc,
                "region rows honor source stride and alpha");
        check(target.getPixel(2,0) == 0xff345678 && target.getPixel(2,1) == 0xff010203,
                "opaque-to-alpha transition preserves untouched visible pixels");
        BufferedImage current = target.getAwtBufferedImageImplementation();
        target.replaceDecodedRegion(new int[]{0xffabcdef}, 1, 1, 1, true);
        check(target.getAwtBufferedImageImplementation() == current, "same-alpha region copy retains current view identity");
        check(target.getPixel(0,0) == 0xffabcdef && target.getPixel(1,1) == 0x10aabbcc,
                "partial region copy leaves other rows unchanged");
        raises(IllegalArgumentException.class, () -> target.replaceDecodedRegion(new int[1], 1, 2, 1, false));
        raises(IllegalArgumentException.class, () -> target.replaceDecodedRegion(new int[1], Integer.MAX_VALUE, 1, 2, false));
        raises(IllegalArgumentException.class, () -> target.replaceDecodedRegion(new int[1], 1, 4, 1, false));
        raises(NullPointerException.class, () -> target.replaceDecodedRegion(null, 1, 1, 1, false));
        check(target.hasAlpha() && target.getAwtBufferedImageImplementation() == current && target.getPixel(0,0) == 0xffabcdef,
                "invalid input preserves view, metadata and pixels");
        target.replaceDecodedRegion(new int[]{0x00123456}, 1, 1, 1, false);
        check(!target.hasAlpha() && target.getPixel(0,0) == 0xff123456, "alpha-to-opaque copy uses real opaque interpretation");
        Bitmap immutable = Bitmap.decoded(1,1,new int[]{0},false,true);
        raises(IllegalStateException.class, () -> immutable.replaceDecodedRegion(new int[1],1,1,1,true));
        Bitmap borrowed = new Bitmap(new BufferedImage(1,1,BufferedImage.TYPE_INT_ARGB));
        raises(UnsupportedOperationException.class, () -> borrowed.replaceDecodedRegion(new int[1],1,1,1,true));
        target.recycle();
        raises(IllegalStateException.class, () -> target.replaceDecodedRegion(new int[1],1,1,1,true));
        System.out.println("Region storage helper: " + checks + " checks passed");
    }
}
