// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.ReadOnlyBufferException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import javax.imageio.ImageIO;

public final class NativeBitmapStorageTest {
    private static int checks;
    private static void check(boolean condition, String message) {
        checks++; if (!condition) { throw new AssertionError(message); }
    }
    private static void raises(Class<? extends Throwable> type, Runnable operation) {
        try { operation.run(); } catch (Throwable error) {
            check(type.isInstance(error), "unexpected " + error); return;
        }
        throw new AssertionError("missing " + type);
    }
    private static Object allocation(Bitmap image) throws Exception {
        java.lang.reflect.Field field = Bitmap.class.getDeclaredField("allocation");
        field.setAccessible(true); return field.get(image);
    }
    private static byte[] raw(Bitmap image) {
        ByteBuffer bytes = ByteBuffer.allocate(image.getByteCount()); image.copyPixelsToBuffer(bytes); return bytes.array();
    }
    private static void oracle(DataInputStream oracle) throws Exception {
        int[] colors = new int[65536];
        Bitmap rgb = Bitmap.createBitmap(1,1,Bitmap.Config.RGB_565);
        ByteBuffer bytes = ByteBuffer.allocate(2);
        for (int pixel=0;pixel<65536;pixel++) {
            colors[pixel] = oracle.readInt();
            bytes.clear(); bytes.put((byte)pixel).put((byte)(pixel>>8)).flip();
            rgb.copyPixelsFromBuffer(bytes);
            check(rgb.getPixel(0,0)==colors[pixel], "RGB565 unpack differs from pinned Skia integer math at " + pixel);
        }
        for (int i=0;i<5000;i++) {
            int color=oracle.readInt(); int packed=oracle.readUnsignedShort();
            rgb.setPixel(0,0,color);
            byte[] memory=raw(rgb);
            check((memory[0]&255)==(packed&255) && (memory[1]&255)==(packed>>8), "RGB565 pack differs from pinned Skia pipeline rounding");
            check(rgb.getPixel(0,0)==colors[packed], "RGB565 pixel round trip uses source-backed replication");
        }
        Bitmap alpha=Bitmap.createBitmap(1,1,Bitmap.Config.ALPHA_8);
        for (int value=0;value<256;value++) {
            alpha.setPixel(0,0,(value<<24)|0x123456);
            check(alpha.getPixel(0,0)==value<<24 && (raw(alpha)[0]&255)==value, "alpha-only storage ignores RGB");
        }
        Bitmap px=Bitmap.createBitmap(1,1,Bitmap.Config.ARGB_8888);
        px.setPremultiplied(false); px.setPixel(0,0,0xF1F2F3F4);
        ByteBuffer buffer=ByteBuffer.allocate(4);buffer.order(ByteOrder.BIG_ENDIAN);px.copyPixelsToBuffer(buffer);
        check(buffer.getInt(0)==0xF2F3F4F1, "unchanged tile-reader RGBA layout probe");
        byte[] expected=new byte[4];oracle.readFully(expected);
        check(Arrays.equals(buffer.array(),expected), "RGBA bytes agree with pinned Skia shifts and native little-endian layout");
        check(oracle.read()==-1, "oracle has no unexpected records");
    }
    private static void buffers() throws Exception {
        Bitmap image=Bitmap.createBitmap(1,1,Bitmap.Config.ARGB_8888);image.setPixel(0,0,0x80123456);
        for (ByteOrder order:new ByteOrder[]{ByteOrder.BIG_ENDIAN,ByteOrder.LITTLE_ENDIAN}) {
            ByteBuffer target=ByteBuffer.allocateDirect(9).order(order);target.position(2);target.limit(6);
            image.copyPixelsToBuffer(target);
            check(target.position()==6 && target.get(2)==0x12 && target.get(3)==0x34 && target.get(4)==0x56 && (target.get(5)&255)==0x80,
                    "raw memcpy respects window and ignores ByteBuffer typed order");
        }
        ByteBuffer source=ByteBuffer.wrap(new byte[]{99,0x11,0x22,0x33,0x44,98});source.position(1);source.limit(5);
        image.copyPixelsFromBuffer(source.asReadOnlyBuffer());
        check(image.getPixel(0,0)==0x44112233 && source.position()==1, "readonly source view can provide raw RGBA without changing sibling position");
        ByteBuffer shortInput=ByteBuffer.wrap(new byte[]{1,2,3});
        raises(RuntimeException.class,()->image.copyPixelsFromBuffer(shortInput));
        check(shortInput.position()==0 && image.getPixel(0,0)==0x44112233, "short input preserves image and buffer position");
        ByteBuffer shortOutput=ByteBuffer.allocate(3);
        raises(RuntimeException.class,()->image.copyPixelsToBuffer(shortOutput));
        check(shortOutput.position()==0 && Arrays.equals(shortOutput.array(),new byte[3]), "short output has no partial writes");
        ByteBuffer readonly=ByteBuffer.allocate(4).asReadOnlyBuffer();
        raises(ReadOnlyBufferException.class,()->image.copyPixelsToBuffer(readonly));
        check(readonly.position()==0, "readonly destination position preserved");
        raises(UnsupportedOperationException.class,()->image.copyPixelsToBuffer(java.nio.IntBuffer.allocate(1)));
        raises(UnsupportedOperationException.class,()->image.copyPixelsFromBuffer(java.nio.ShortBuffer.allocate(2)));
        raises(NullPointerException.class,()->image.copyPixelsToBuffer(null));
        check(!image.isPremultiplied(), "canonical owned RGBA is explicitly unpremultiplied");
        raises(UnsupportedOperationException.class,()->image.setPremultiplied(true));
        check(image.getPixel(0,0)==0x44112233, "unsupported premultiplication does not reinterpret or corrupt pixels");
        Bitmap immutable=Bitmap.createBitmap(new int[]{0xff123456},1,1,Bitmap.Config.ARGB_8888);
        ByteBuffer input=ByteBuffer.wrap(new byte[]{1,2,3,4});
        raises(IllegalStateException.class,()->immutable.copyPixelsFromBuffer(input));
        check(input.position()==0, "immutable input rejection does not consume buffer");
        Bitmap borrowed=new Bitmap(new BufferedImage(1,1,BufferedImage.TYPE_INT_ARGB_PRE));
        check(borrowed.isPremultiplied(), "borrowed view reports its actual premultiplication model");
        raises(UnsupportedOperationException.class,()->borrowed.copyPixelsToBuffer(ByteBuffer.allocate(4)));
        raises(UnsupportedOperationException.class,()->borrowed.setPremultiplied(false));
        image.recycle();
        raises(IllegalStateException.class,()->image.copyPixelsToBuffer(ByteBuffer.allocate(4)));
        raises(IllegalStateException.class,()->image.copyPixelsFromBuffer(ByteBuffer.allocate(4)));
    }
    private static void capacityAndDrawing() throws Exception {
        for (Bitmap.Config config : Bitmap.Config.values()) {
            raises(IllegalArgumentException.class, () -> Bitmap.createBitmap(Integer.MAX_VALUE, Integer.MAX_VALUE, config));
        }
        Bitmap image=Bitmap.createBitmap(3,2,Bitmap.Config.ARGB_8888);
        Object storage=allocation(image); BufferedImage old=image.getAwtBufferedImageImplementation();
        check(storage instanceof byte[] && ((byte[])storage).length==24, "canonical capacity is actual byte storage");
        image.reconfigure(5,2,Bitmap.Config.RGB_565);
        check(allocation(image)==storage && image.getByteCount()==20 && image.getRowBytes()==10 && image.getAllocationByteCount()==24,
                "RGB565 reinterpretation uses real two-byte pixels within original capacity");
        image.setPixel(0,0,0xffff0000);
        check(image.getPixel(0,0)==0xffff0000 && !image.hasAlpha() && image.getConfig()==Bitmap.Config.RGB_565, "RGB565 is opaque with real quantized storage");
        check(old.getWidth()==3 && old.getHeight()==2, "old view retains dimensions through cross-config reconfigure");
        image.reconfigure(24,1,Bitmap.Config.ALPHA_8);
        check(allocation(image)==storage && image.getByteCount()==24 && image.getRowBytes()==24 && image.hasAlpha(), "alpha-only pixels reuse the same byte capacity");
        image.setPixel(23,0,0x7fabcdef);check(image.getPixel(23,0)==0x7f000000, "last alpha sample uses actual final byte");
        raises(IllegalArgumentException.class,()->image.reconfigure(25,1,Bitmap.Config.ALPHA_8));
        check(image.getWidth()==24 && image.getConfig()==Bitmap.Config.ALPHA_8 && image.getPixel(23,0)==0x7f000000, "capacity failure preserves config shape and data");
        image.reconfigure(3,2,Bitmap.Config.ARGB_8888);
        check(allocation(image)==storage && image.getByteCount()==24 && image.getRowBytes()==12, "ARGB capacity recovered without replacement storage");
        for (Bitmap.Config config:Bitmap.Config.values()) {
            Bitmap target=Bitmap.createBitmap(3,2,config); Paint paint=new Paint();paint.setColor(0x80ff0000);
            new Canvas(target).drawRect(0,0,3,2,paint);
            int actual=target.getPixel(1,1);
            check(config==Bitmap.Config.RGB_565 ? actual==0xff840000 : config==Bitmap.Config.ALPHA_8 ? actual==0x80000000 : actual==0x80ff0000,
                    "Canvas uses actual format color and alpha conversion");
            Bitmap scaled=Bitmap.createScaledBitmap(target,6,4,false);
            check(scaled.getConfig()==config && scaled.getPixel(3,1)==actual, "scaling retains actual source config and semantic pixels");
            ByteArrayOutputStream png=new ByteArrayOutputStream();check(target.compress(Bitmap.CompressFormat.PNG,80,png), "real format image encodes PNG");
            check(ImageIO.read(new ByteArrayInputStream(png.toByteArray())).getRGB(1,1)==actual, "PNG codec receives semantic colors rather than misreading custom raster samples");
        }
        Bitmap opaque = Bitmap.decoded(2,1,new int[]{0xff0000ff,0xff0000ff},true,false);
        check(Arrays.equals(raw(opaque),new byte[]{0,0,(byte)255,(byte)255,0,0,(byte)255,(byte)255}),
                "opaque decoder writes physical RGBA alpha bytes as 255");
        Paint half = new Paint();half.setColor(0x80ff0000);
        new Canvas(opaque).drawRect(0,0,1,1,half);
        check(opaque.getPixel(0,0)==0xff80007f && (raw(opaque)[3]&255)==255,
                "opaque Java2D compositing preserves real physical alpha255");
        Bitmap mask = Bitmap.createBitmap(1,1,Bitmap.Config.ALPHA_8);mask.setPixel(0,0,0x80000000);
        Bitmap canvasTarget=Bitmap.createBitmap(1,1,Bitmap.Config.ARGB_8888);
        Paint tint=new Paint();tint.setColor(0xffff0000);
        raises(UnsupportedOperationException.class,()->new Canvas(canvasTarget).drawBitmap(mask,0,0,tint));
        new Canvas(canvasTarget).drawBitmap(mask,0,0,null);
        check(canvasTarget.getPixel(0,0)==0x80000000, "alpha-only source draws its actual black alpha pixels without a tint");
        Bitmap rgb=Bitmap.decoded(3,2,new int[]{-1,-1,-1,-1,-1,-1},true,true,Bitmap.Config.RGB_565);
        Object rgbStorage=allocation(rgb);rgb.replaceDecodedRegion(new int[]{0xff123456},1,1,1,true);
        check(rgb.getConfig()==Bitmap.Config.RGB_565 && !rgb.hasAlpha() && rgb.getPixel(0,0)==0xff103452
                && rgb.getPixel(2,1)==-1 && allocation(rgb)==rgbStorage, "region helper preserves RGB565 config/capacity and untouched pixels");
        Bitmap alpha=Bitmap.decoded(3,2,new int[]{0,0,0,0,0,0x7f000000},true,false,Bitmap.Config.ALPHA_8);
        Object alphaStorage=allocation(alpha);alpha.replaceDecodedRegion(new int[]{0x80112233},1,1,1,false);
        check(alpha.getConfig()==Bitmap.Config.ALPHA_8 && alpha.hasAlpha() && alpha.getPixel(0,0)==0x80000000
                && alpha.getPixel(2,1)==0x7f000000 && allocation(alpha)==alphaStorage, "region helper preserves alpha-only config and untouched alpha bytes");
    }
    public static void main(String[] args) throws Exception {
        try(DataInputStream input=new DataInputStream(Files.newInputStream(Path.of(args[0])))){oracle(input);}
        buffers();capacityAndDrawing();
        System.out.println("Native-layout bitmap math/raw bytes: "+checks+" checks passed");
    }
}
