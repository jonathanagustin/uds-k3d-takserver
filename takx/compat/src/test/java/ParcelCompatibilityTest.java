// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import android.os.Bundle;
import android.os.Parcel;
import com.atakmap.coremap.maps.assets.Icon;
import java.util.Arrays;

public final class ParcelCompatibilityTest {
    private static int checks;
    private static void check(boolean condition) {
        checks++;
        if (!condition) throw new AssertionError("Parcel contract " + checks);
    }
    private static void reject(Runnable action) {
        try { action.run(); throw new AssertionError("Expected rejection"); }
        catch (IllegalArgumentException | IllegalStateException expected) { checks++; }
    }
    public static void main(String[] args) {
        Parcel p = Parcel.obtain();
        p.writeInt(0x78563412);
        p.writeLong(0x0807060504030201L);
        p.writeDouble(1.0);
        p.writeString("A");
        p.writeString("\uD83D\uDE00");
        p.writeString(null);
        p.writeByteArray(new byte[]{9, 8, 7});
        // Android little-endian primitive/string16 encoding, 4-byte padding.
        byte[] golden = {0x12,0x34,0x56,0x78, 1,2,3,4,5,6,7,8,
            0,0,0,0,0,0,(byte)0xf0,0x3f, 1,0,0,0,0x41,0,0,0,
            2,0,0,0,0x3d,(byte)0xd8,0,(byte)0xde,0,0,0,0,
            -1,-1,-1,-1, 3,0,0,0,9,8,7,0};
        check(Arrays.equals(golden, p.marshall()));
        check(p.dataSize() == golden.length && p.dataPosition() == golden.length);
        p.setDataPosition(0);
        check(p.readInt() == 0x78563412);
        check(p.readLong() == 0x0807060504030201L);
        check(p.readDouble() == 1.0);
        check("A".equals(p.readString()));
        check("\uD83D\uDE00".equals(p.readString()));
        check(p.readString() == null);
        check(Arrays.equals(new byte[]{9,8,7}, p.createByteArray()));
        check(p.dataAvail() == 0);
        reject(p::readInt);
        reject(() -> p.setDataPosition(-1));
        reject(() -> p.setDataPosition(p.dataSize() + 1));
        Parcel input = Parcel.obtain();
        input.unmarshall(golden, 0, golden.length);
        check(input.readInt() == 0x78563412);
        input.setDataPosition(0);
        input.writeInt(7);
        input.setDataPosition(0);
        check(input.readInt() == 7 && input.dataSize() == golden.length);
        input.recycle();
        reject(input::dataSize);
        reject(() -> input.writeInt(0));
        Parcel malformed = Parcel.obtain();
        malformed.writeInt(100);
        malformed.setDataPosition(0);
        reject(malformed::readString);
        Parcel shortBytes = Parcel.obtain();
        shortBytes.writeInt(3);
        shortBytes.setDataPosition(0);
        reject(shortBytes::createByteArray);
        Parcel values = Parcel.obtain();
        int[] ints = {Integer.MIN_VALUE, -1, 0, 1, Integer.MAX_VALUE};
        long[] longs = {Long.MIN_VALUE, -1, 0, 1, Long.MAX_VALUE};
        long[] doubleBits = {0, Long.MIN_VALUE, 0x7ff0000000000000L,
                             0xfff0000000000000L, 0x7ff8000000001234L};
        for (int value : ints) values.writeInt(value);
        for (long value : longs) values.writeLong(value);
        for (long bits : doubleBits) values.writeDouble(Double.longBitsToDouble(bits));
        values.writeString("");
        values.writeString("\uD800"); // Unpaired UTF-16 units are preserved, not replaced.
        values.writeByteArray(null);
        values.writeByteArray(new byte[0]);
        values.setDataPosition(0);
        for (int value : ints) check(values.readInt() == value);
        for (long value : longs) check(values.readLong() == value);
        for (long bits : doubleBits) check(Double.doubleToRawLongBits(values.readDouble()) == bits);
        check("".equals(values.readString()));
        check("\uD800".equals(values.readString()));
        check(values.createByteArray() == null);
        check(values.createByteArray().length == 0);
        check(values.dataAvail() == 0);
        Bundle bundle = new Bundle();
        check(bundle.getInt("absent") == 0);
        check(bundle.getInt("absent", 12) == 12);
        byte[] cert = {1,2,3};
        bundle.putInt("certCount", 1);
        bundle.putByteArray("0", cert);
        check(bundle.getInt("certCount") == 1 && bundle.getByteArray("0") == cert);
        check(bundle.getByteArray("certCount") == null);
        check(bundle.getInt("0", 5) == 5);
        cert[0] = 4;
        check(bundle.getByteArray("0")[0] == 4);
        Icon icon = new Icon.Builder().setSize(32, 48).setAnchor(4, 5)
            .setImageUri(0, "file:///tmp/a%20b.png").setImageUri(2, "asset:///marker.png")
            .setColor(0, 0xff112233).setColor(2, 0xff445566).build();
        Parcel encoded = Parcel.obtain();
        icon.writeToParcel(encoded, 0);
        encoded.setDataPosition(0);
        Icon restored = Icon.CREATOR.createFromParcel(encoded);
        check(restored.getWidth() == 32 && restored.getHeight() == 48);
        check(restored.getAnchorX() == 4 && restored.getAnchorY() == 5);
        check(icon.getImageUri(0).equals(restored.getImageUri(0)));
        check(icon.getImageUri(2).equals(restored.getImageUri(2)));
        check(restored.getColor(2) == 0xff445566);
        check(encoded.dataAvail() == 0);
        check(Icon.CREATOR.newArray(3).length == 3);
        System.out.println(checks + " primitive wire/Bundle/unchanged Kernel Icon checks passed");
    }
}
