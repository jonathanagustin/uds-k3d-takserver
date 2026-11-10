// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.Point;
import java.awt.Transparency;
import java.awt.color.ColorSpace;
import java.awt.image.BufferedImage;
import java.awt.image.ColorModel;
import java.awt.image.ComponentColorModel;
import java.awt.image.DataBuffer;
import java.awt.image.DataBufferByte;
import java.awt.image.PixelInterleavedSampleModel;
import java.awt.image.Raster;
import java.awt.image.SampleModel;
import java.awt.image.SinglePixelPackedSampleModel;
import java.awt.image.WritableRaster;

/** Canonical tight-row Android little-endian layouts over one owned byte array. */
final class BitmapStorage {
    private BitmapStorage() {}

    static BufferedImage view(byte[] bytes, int width, int height, Bitmap.Config config, boolean alpha) {
        if (config == Bitmap.Config.RGB_565) {
            SampleModel samples = new SinglePixelPackedSampleModel(DataBuffer.TYPE_USHORT,
                    width, height, width, new int[]{0xf800, 0x07e0, 0x001f});
            return new BufferedImage(new Rgb565(), new GenericRaster(samples, new LittleEndian16(bytes)), false, null);
        }
        if (config == Bitmap.Config.ALPHA_8) {
            SampleModel samples = new PixelInterleavedSampleModel(DataBuffer.TYPE_BYTE,
                    width, height, 1, width, new int[]{0});
            return new BufferedImage(new Alpha8(), new GenericRaster(samples, new DataBufferByte(bytes, bytes.length)), false, null);
        }
        if (!alpha) {
            SampleModel samples = new PixelInterleavedSampleModel(DataBuffer.TYPE_BYTE,
                    width, height, 4, width * 4, new int[]{0,1,2,3});
            return new BufferedImage(new OpaqueRgba(), new GenericRaster(samples, new DataBufferByte(bytes, bytes.length)), false, null);
        }
        ColorModel colors = new ComponentColorModel(ColorSpace.getInstance(ColorSpace.CS_sRGB),
                alpha, false, alpha ? Transparency.TRANSLUCENT : Transparency.OPAQUE, DataBuffer.TYPE_BYTE);
        SampleModel samples = new PixelInterleavedSampleModel(DataBuffer.TYPE_BYTE,
                width, height, 4, width * 4, alpha ? new int[]{0,1,2,3} : new int[]{0,1,2});
        return new BufferedImage(colors, new GenericRaster(samples, new DataBufferByte(bytes, bytes.length)), false, null);
    }

    static void makeOpaqueRgba(byte[] bytes, int count) {
        for (int i = 0; i < count; i++) { bytes[i * 4 + 3] = (byte) 255; }
    }

    private static final class GenericRaster extends WritableRaster {
        GenericRaster(SampleModel samples, DataBuffer data) { super(samples, data, new Point()); }
        @Override public WritableRaster createCompatibleWritableRaster(int width, int height) {
            SampleModel samples = sampleModel.createCompatibleSampleModel(width, height);
            return new GenericRaster(samples, samples.createDataBuffer());
        }
    }

    private static final class LittleEndian16 extends DataBuffer {
        private final byte[] bytes;
        LittleEndian16(byte[] bytes) { super(DataBuffer.TYPE_USHORT, bytes.length / 2); this.bytes = bytes; }
        @Override public int getElem(int index) { return (bytes[index * 2] & 255) | ((bytes[index * 2 + 1] & 255) << 8); }
        @Override public void setElem(int index, int value) { bytes[index * 2] = (byte) value; bytes[index * 2 + 1] = (byte) (value >> 8); }
        @Override public int getElem(int bank, int index) { return getElem(index); }
        @Override public void setElem(int bank, int index, int value) { setElem(index, value); }
    }

    /** Skia low-precision CPU RGB565 uses rounded packing and bit-replicated unpacking. */
    private static final class Rgb565 extends ColorModel {
        Rgb565() { super(16, new int[]{5,6,5}, ColorSpace.getInstance(ColorSpace.CS_sRGB),
                false, false, Transparency.OPAQUE, DataBuffer.TYPE_USHORT); }
        @Override public int getAlpha(int value) { return 255; }
        @Override public boolean isCompatibleRaster(Raster raster) {
            return raster.getSampleModel() instanceof SinglePixelPackedSampleModel
                    && raster.getDataBuffer().getDataType() == DataBuffer.TYPE_USHORT;
        }
        @Override public WritableRaster createCompatibleWritableRaster(int width, int height) {
            return new GenericRaster(new SinglePixelPackedSampleModel(DataBuffer.TYPE_USHORT,
                    width, height, width, new int[]{0xf800,0x07e0,0x001f}),
                    new LittleEndian16(new byte[width * height * 2]));
        }
        @Override public int[] getComponents(int pixel, int[] output, int offset) {
            int[] result = output == null ? new int[offset + 3] : output;
            result[offset] = (pixel >> 11) & 31; result[offset + 1] = (pixel >> 5) & 63; result[offset + 2] = pixel & 31;
            return result;
        }
        @Override public int[] getComponents(Object pixel, int[] output, int offset) {
            return getComponents(((short[]) pixel)[0] & 65535, output, offset);
        }
        @Override public int getRed(int value) { int v = (value >> 11) & 31; return (v << 3) | (v >> 2); }
        @Override public int getGreen(int value) { int v = (value >> 5) & 63; return (v << 2) | (v >> 4); }
        @Override public int getBlue(int value) { int v = value & 31; return (v << 3) | (v >> 2); }
        @Override public int getRGB(int value) { return 0xff000000 | (getRed(value) << 16) | (getGreen(value) << 8) | getBlue(value); }
        @Override public int getRGB(Object pixel) { return getRGB(((short[]) pixel)[0] & 65535); }
        @Override public Object getDataElements(int rgb, Object pixel) {
            short[] result = pixel == null ? new short[1] : (short[]) pixel;
            int r = ((rgb >> 16) & 255), g = ((rgb >> 8) & 255), b = rgb & 255;
            int red = (r * 9 + 36) / 74, green = (g * 21 + 42) / 85, blue = (b * 9 + 36) / 74;
            result[0] = (short) ((red << 11) | (green << 5) | blue);
            return result;
        }
    }

    /** Opaque RGBA still writes its physical alpha byte as 255. */
    private static final class OpaqueRgba extends ColorModel {
        OpaqueRgba() { super(32, new int[]{8,8,8}, ColorSpace.getInstance(ColorSpace.CS_sRGB),
                false, false, Transparency.OPAQUE, DataBuffer.TYPE_BYTE); }
        @Override public int getRed(int pixel) { return pixel & 255; }
        @Override public int getGreen(int pixel) { return (pixel >> 8) & 255; }
        @Override public int getBlue(int pixel) { return (pixel >> 16) & 255; }
        @Override public int getAlpha(int pixel) { return 255; }
        @Override public int getRGB(Object pixel) {
            byte[] p = (byte[]) pixel;
            return 0xff000000 | ((p[0] & 255) << 16) | ((p[1] & 255) << 8) | (p[2] & 255);
        }
        @Override public Object getDataElements(int rgb, Object pixel) {
            byte[] p = pixel == null ? new byte[4] : (byte[]) pixel;
            p[0] = (byte)(rgb >> 16); p[1] = (byte)(rgb >> 8); p[2] = (byte)rgb; p[3] = (byte)255;
            return p;
        }
        @Override public int[] getComponents(Object pixel, int[] output, int offset) {
            byte[] p = (byte[]) pixel;
            int[] result = output == null ? new int[offset + 3] : output;
            for (int i = 0; i < 3; i++) { result[offset + i] = p[i] & 255; }
            return result;
        }
        @Override public boolean isCompatibleRaster(Raster raster) {
            return raster.getTransferType() == DataBuffer.TYPE_BYTE && raster.getNumBands() == 4;
        }
        @Override public WritableRaster createCompatibleWritableRaster(int width, int height) {
            return new GenericRaster(new PixelInterleavedSampleModel(DataBuffer.TYPE_BYTE,
                    width, height, 4, width * 4, new int[]{0,1,2,3}), new DataBufferByte(width * height * 4));
        }
    }

    private static final class Alpha8 extends ColorModel {
        Alpha8() { super(8); }
        @Override public int getRed(int pixel) { return 0; }
        @Override public int getGreen(int pixel) { return 0; }
        @Override public int getBlue(int pixel) { return 0; }
        @Override public int getAlpha(int pixel) { return pixel & 255; }
        @Override public int getRGB(int pixel) { return (pixel & 255) << 24; }
        @Override public int getRGB(Object pixel) { return getRGB(((byte[]) pixel)[0]); }
        @Override public Object getDataElements(int rgb, Object pixel) {
            byte[] result = pixel == null ? new byte[1] : (byte[]) pixel;
            result[0] = (byte) (rgb >>> 24); return result;
        }
        @Override public boolean isCompatibleRaster(Raster raster) { return isCompatibleSampleModel(raster.getSampleModel()); }
        @Override public boolean isCompatibleSampleModel(SampleModel samples) { return samples.getDataType() == DataBuffer.TYPE_BYTE && samples.getNumBands() == 1; }
        @Override public WritableRaster createCompatibleWritableRaster(int width, int height) {
            return Raster.createInterleavedRaster(DataBuffer.TYPE_BYTE, width, height, 1, null);
        }
    }
}
