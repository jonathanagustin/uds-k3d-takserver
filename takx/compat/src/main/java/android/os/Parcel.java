// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: Apache-2.0
package android.os;

import java.util.Arrays;

/** Bounded in-memory Android primitive encoding. No Binder, file descriptors or IPC. */
public final class Parcel {
    private static final int MAX_BYTES = 16 * 1024 * 1024;
    private byte[] data = new byte[64];
    private int position;
    private int size;
    private boolean recycled;

    private Parcel() {}
    public static Parcel obtain() { return new Parcel(); }
    private void live() {
        if (recycled) throw new IllegalStateException("Parcel has been recycled");
    }
    private void require(int count) {
        live();
        if (count < 0 || count > size - position) throw new IllegalStateException("Truncated Parcel");
    }
    private void reserve(int count) {
        live();
        if (count < 0 || count > MAX_BYTES - position) throw new IllegalArgumentException("Parcel capacity exceeded");
        int end = position + count;
        if (end > data.length) data = Arrays.copyOf(data, Math.max(end, Math.min(MAX_BYTES, data.length * 2)));
        size = Math.max(size, end);
    }
    private static int padded(int count) {
        if (count < 0 || count > MAX_BYTES - 3) throw new IllegalArgumentException("Invalid Parcel length");
        return (count + 3) & ~3;
    }
    public int dataPosition() { live(); return position; }
    public int dataSize() { live(); return size; }
    public int dataAvail() { live(); return size - position; }
    public void setDataPosition(int value) {
        live();
        if (value < 0 || value > size) throw new IllegalArgumentException("Position outside Parcel");
        position = value;
    }
    public void recycle() {
        Arrays.fill(data, (byte) 0);
        position = size = 0;
        recycled = true;
    }
    public byte[] marshall() { live(); return Arrays.copyOf(data, size); }
    public void unmarshall(byte[] bytes, int offset, int length) {
        live();
        if (offset < 0 || length < 0 || offset > bytes.length - length || length > MAX_BYTES)
            throw new IllegalArgumentException("Invalid Parcel input range");
        data = Arrays.copyOfRange(bytes, offset, offset + length);
        size = length;
        position = 0;
    }
    private void writeBits(long value, int count) {
        reserve(count);
        for (int i = 0; i < count; i++) data[position++] = (byte) (value >>> (i * 8));
    }
    private long readBits(int count) {
        require(count);
        long value = 0;
        for (int i = 0; i < count; i++) value |= (data[position++] & 255L) << (i * 8);
        return value;
    }
    public void writeInt(int value) { writeBits(value, 4); }
    public int readInt() { return (int) readBits(4); }
    public void writeLong(long value) { writeBits(value, 8); }
    public long readLong() { return readBits(8); }
    public void writeDouble(double value) { writeLong(Double.doubleToRawLongBits(value)); }
    public double readDouble() { return Double.longBitsToDouble(readLong()); }
    public void writeString(String value) {
        if (value == null) { writeInt(-1); return; }
        int count = padded(Math.multiplyExact(Math.addExact(value.length(), 1), 2));
        reserve(Math.addExact(4, count));
        writeInt(value.length());
        int start = position;
        for (int i = 0; i < value.length(); i++) writeBits(value.charAt(i), 2);
        Arrays.fill(data, position, start + count, (byte) 0);
        position = start + count;
    }
    public String readString() {
        int length = readInt();
        if (length == -1) return null;
        int count = padded(Math.multiplyExact(Math.addExact(length, 1), 2));
        require(count);
        int start = position;
        char[] chars = new char[length];
        for (int i = 0; i < length; i++) chars[i] = (char) readBits(2);
        if (readBits(2) != 0) throw new IllegalStateException("Missing string terminator");
        position = start + count;
        return new String(chars);
    }
    public void writeByteArray(byte[] value) {
        if (value == null) { writeInt(-1); return; }
        int count = padded(value.length);
        reserve(Math.addExact(4, count));
        writeInt(value.length);
        System.arraycopy(value, 0, data, position, value.length);
        Arrays.fill(data, position + value.length, position + count, (byte) 0);
        position += count;
    }
    public byte[] createByteArray() {
        int length = readInt();
        if (length == -1) return null;
        int count = padded(length);
        require(count);
        byte[] result = Arrays.copyOfRange(data, position, position + length);
        position += count;
        return result;
    }
}
