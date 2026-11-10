// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.util.Arrays;
import javax.imageio.ImageIO;

/** Focused contracts from final-api-sources.lock.json, with real pixels/streams. */
public final class FinalGraphicsApiTest {
    private static int checks;
    private static void check(boolean value, String message) {
        checks++; if (!value) throw new AssertionError(message);
    }
    private static void raises(Class<? extends Throwable> type, Runnable call) {
        try { call.run(); } catch (Throwable error) {
            check(type.isInstance(error), "expected " + type + ", got " + error); return;
        }
        throw new AssertionError("missing " + type);
    }
    private static byte[] raw(Bitmap b) {
        ByteBuffer data = ByteBuffer.allocate(b.getByteCount()); b.copyPixelsToBuffer(data); return data.array();
    }
    private static void bitmap() {
        Bitmap alias = Bitmap.createBitmap(2, 1, Bitmap.Config.ARGB_4444);
        check(alias.getConfig() == Bitmap.Config.ARGB_8888 && alias.getByteCount() == 8
                && alias.getRowBytes() == 8 && alias.getAllocationByteCount() == 8, "legacy creation has real N32 allocation");
        alias.setPixel(0, 0, 0x80123456); alias.setPixel(1, 0, 0x00456789);
        byte[] before = raw(alias);
        alias.setHasAlpha(false);
        check(!alias.hasAlpha() && alias.getPixel(0, 0) == 0xff123456, "opaque hint changes semantic interpretation");
        check(Arrays.equals(before, raw(alias)), "opaque hint preserves underlying alpha bytes");
        Bitmap copied = alias.copy(Bitmap.Config.ARGB_4444, false);
        check(copied != alias && !copied.isMutable() && !copied.hasAlpha()
                && copied.getConfig() == Bitmap.Config.ARGB_8888, "copy applies alias and requested mutability");
        check(Arrays.equals(raw(copied), before), "same-format copy preserves actual bytes under an opaque hint");
        copied.setHasAlpha(true);
        check(copied.hasAlpha() && copied.getPixel(0, 0) == 0x80123456, "immutable copy permits metadata hint and retains alpha");
        check(!alias.hasAlpha(), "copy metadata is independent");
        alias.setHasAlpha(true);
        check(alias.getPixel(1, 0) == 0x00456789, "alpha hint round trip preserves transparent RGB");
        alias.setPixel(0, 0, 0xffffffff);
        check(copied.getPixel(0, 0) == 0x80123456, "copy owns separate pixels");
        raises(IllegalStateException.class, () -> copied.setPixel(0, 0, 0));
        Bitmap mutable = copied.copy(Bitmap.Config.ARGB_8888, true); mutable.setPixel(0, 0, 0xffabcdef);
        check(copied.getPixel(0, 0) == 0x80123456, "mutable copy of immutable source is independent");
        Bitmap alpha = copied.copy(Bitmap.Config.ALPHA_8, true);
        check(alpha.getByteCount() == 2 && alpha.getPixel(0, 0) == 0x80000000, "A8 copy extracts actual alpha");
        alpha.setHasAlpha(true); check(alpha.hasAlpha(), "A8 supported hint");
        byte[] alphaBefore = raw(alpha);
        raises(UnsupportedOperationException.class, () -> alpha.setHasAlpha(false));
        check(alpha.hasAlpha() && Arrays.equals(raw(alpha), alphaBefore), "unsupported A8 opacity preserves state");
        Bitmap rgb = Bitmap.createBitmap(new int[]{0x80ff0000,0x8000ff00}, 2, 1, Bitmap.Config.ARGB_8888)
                .copy(Bitmap.Config.RGB_565, true);
        check(!rgb.hasAlpha() && rgb.getPixel(0, 0) == 0xffff0000 && rgb.getPixel(1, 0) == 0xff00ff00,
                "RGB565 copy discards alpha and converts colors");
        rgb.setHasAlpha(true); check(!rgb.hasAlpha(), "RGB565 ignores unsupported alpha hint as AOSP documents");
        raises(UnsupportedOperationException.class, () -> rgb.copy(Bitmap.Config.ALPHA_8,true));
        check(!rgb.hasAlpha() && rgb.getPixel(0,0)==0xffff0000,"opaque-to-A8 rejection preserves the source");
        raises(IllegalArgumentException.class, () -> rgb.reconfigure(2, 1, Bitmap.Config.ARGB_4444));
        check(rgb.getConfig() == Bitmap.Config.RGB_565 && rgb.getByteCount() == 4, "alias reconfiguration checks normalized capacity atomically");
        alias.reconfigure(1, 2, Bitmap.Config.ARGB_4444);
        check(alias.getConfig() == Bitmap.Config.ARGB_8888 && alias.getRowBytes() == 4, "alias reconfiguration resolves real storage");
        Bitmap immutableAlias = Bitmap.createBitmap(new int[]{0x87654321},1,1,Bitmap.Config.ARGB_4444);
        check(!immutableAlias.isMutable() && immutableAlias.getConfig() == Bitmap.Config.ARGB_8888
                && immutableAlias.getPixel(0,0) == 0x87654321, "array creation resolves alias without four-bit quantization");
        BufferedImage backing = new BufferedImage(1,1,BufferedImage.TYPE_INT_ARGB_PRE);
        backing.setRGB(0,0,0x80123456); Bitmap borrowed = new Bitmap(backing);
        Bitmap owned = borrowed.copy(Bitmap.Config.ARGB_8888, true);
        check(owned.getPixel(0,0) == backing.getRGB(0,0) && owned.getConfig() == Bitmap.Config.ARGB_8888,
                "borrowed premultiplied pixels convert to independent desktop straight-alpha storage");
        raises(UnsupportedOperationException.class, () -> borrowed.setHasAlpha(false));
        raises(NullPointerException.class, () -> owned.copy(null,true));
        copied.recycle();
        raises(IllegalStateException.class, () -> copied.copy(Bitmap.Config.ARGB_8888,true));
        raises(IllegalStateException.class, () -> copied.setHasAlpha(true));
    }
    private static void canvasAndPaint() {
        Bitmap b = Bitmap.createBitmap(3,2,Bitmap.Config.ARGB_8888); Canvas c = new Canvas(b);
        c.drawColor(0xff0000ff); c.drawColor(0x00ff0000);
        for (int y=0;y<2;y++) for(int x=0;x<3;x++) check(b.getPixel(x,y)==0xff0000ff,"transparent SRC_OVER keeps destination");
        c.drawColor(0x80ff0000);
        for (int y=0;y<2;y++) for(int x=0;x<3;x++) check(b.getPixel(x,y)==0xff80007f,"SRC_OVER fills complete surface");
        c.drawColor(0xff123456); check(b.getPixel(2,1)==0xff123456,"opaque drawColor replaces destination");
        Bitmap a = Bitmap.createBitmap(1,1,Bitmap.Config.ALPHA_8); new Canvas(a).drawColor(0x80123456);
        check(a.getPixel(0,0)==0x80000000,"drawColor writes actual A8 alpha");
        Bitmap r = Bitmap.createBitmap(1,1,Bitmap.Config.RGB_565); new Canvas(r).drawColor(0xffff0000);
        check(r.getPixel(0,0)==0xffff0000,"drawColor writes actual RGB565 color");
        b.recycle(); raises(IllegalStateException.class, () -> c.drawColor(0));
        Paint p = new Paint(); p.setTypeface(Typeface.MONOSPACE); p.setTextSize(23); p.setAntiAlias(true);
        p.setStyle(Paint.Style.FILL_AND_STROKE); p.setTextAlign(Paint.Align.RIGHT); p.setColor(0x80123456); p.setStrokeWidth(3.5f);
        Paint q = new Paint(p);
        check(q.getTypeface()==p.getTypeface() && q.getTextSize()==23 && q.isAntiAlias(),"copy retains text metrics state");
        check(q.getStyle()==Paint.Style.FILL_AND_STROKE && q.getTextAlign()==Paint.Align.RIGHT
                && q.getColor()==0x80123456 && q.getStrokeWidth()==3.5f,"copy retains supported drawing state");
        check(q.measureText("TAK") == p.measureText("TAK"),"copy produces identical real text measurement");
        q.setTextSize(11); q.setColor(0xffffffff); q.setAntiAlias(false); q.setStyle(Paint.Style.STROKE);
        check(p.getTextSize()==23 && p.getColor()==0x80123456 && p.isAntiAlias()
                && p.getStyle()==Paint.Style.FILL_AND_STROKE,"paint mutations are independent");
        check(Paint.UNDERLINE_TEXT_FLAG==0x08 && Paint.STRIKE_THRU_TEXT_FLAG==0x10,"pinned MapTextFormat flag masks");
        raises(NullPointerException.class, () -> new Paint(null));
    }
    private static final class Borrowed extends ByteArrayInputStream {
        boolean closed;
        Borrowed(byte[] bytes) { super(bytes); }
        @Override public void close() { closed = true; }
    }
    private static void decoder() throws Exception {
        BufferedImage image = new BufferedImage(3,2,BufferedImage.TYPE_INT_ARGB); image.setRGB(2,1,0x80123456);
        ByteArrayOutputStream encoded = new ByteArrayOutputStream(); ImageIO.write(image,"png",encoded); byte[] png=encoded.toByteArray();
        Borrowed stream = new Borrowed(png); Bitmap direct = BitmapFactory.decodeStream(stream);
        check(direct.getWidth()==3 && direct.getHeight()==2 && direct.getPixel(2,1)==0x80123456,"one-argument stream decodes real PNG pixels");
        check(!stream.closed,"decoder leaves caller stream open");
        check(BitmapFactory.decodeStream(null)==null,"null stream remains null");
        BitmapFactory.Options o = new BitmapFactory.Options(); o.inDither=true; o.inPurgeable=true;
        o.inInputShareable=true; o.inPreferQualityOverSpeed=true; o.requestCancelDecode();
        o.inPreferredConfig=Bitmap.Config.ARGB_4444;
        Bitmap legacy=BitmapFactory.decodeByteArray(png,0,png.length,o);
        check(o.mCancel && legacy.getPixel(2,1)==direct.getPixel(2,1)
                && legacy.getConfig()==Bitmap.Config.ARGB_8888,"only pinned deprecated flags are ignored; cancellation flag persists");
        for (boolean scaled:new boolean[]{false,true}) for (int target:new int[]{0,160,320}) {
            BitmapFactory.Options density=new BitmapFactory.Options(); density.inDensity=160; density.inTargetDensity=target;
            density.inScreenDensity=160; density.inScaled=scaled;
            Borrowed input=new Borrowed(png);
            raises(UnsupportedOperationException.class, () -> BitmapFactory.decodeStream(input,null,density));
            check(input.available()==png.length && !input.closed,"unsupported metadata request fails before consuming input");
        }
        BitmapFactory.Options bounds=new BitmapFactory.Options(); bounds.inJustDecodeBounds=true;
        bounds.inDensity=160; bounds.inTargetDensity=320;
        check(BitmapFactory.decodeByteArray(png,0,png.length,bounds)==null && bounds.outWidth==3
                && bounds.outHeight==2,"bounds-only returns before density scaling as pinned native code does");
        BitmapFactory.Options noSourceDensity=new BitmapFactory.Options(); noSourceDensity.inTargetDensity=320;
        check(BitmapFactory.decodeByteArray(png,0,png.length,noSourceDensity).getWidth()==3,"target alone does not request scaling");
        BitmapFactory.Options scratch=new BitmapFactory.Options(); scratch.inTempStorage=new byte[16];
        Borrowed untouched=new Borrowed(png);
        raises(UnsupportedOperationException.class, () -> BitmapFactory.decodeStream(untouched,null,scratch));
        check(untouched.available()==png.length && !untouched.closed,"active scratch option cannot be silently discarded");
    }
    public static void main(String[] args) throws Exception {
        bitmap(); canvasAndPaint(); decoder();
        System.out.println("Final graphics API checks: " + checks);
    }
}
