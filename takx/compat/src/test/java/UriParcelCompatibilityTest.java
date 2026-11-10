// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.net;

import android.os.Parcel;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.util.Arrays;

public final class UriParcelCompatibilityTest {
    private static int checks;
    private static void check(boolean result) {
        checks++;
        if (!result) throw new AssertionError("URI parcel check " + checks);
    }
    public static void main(String[] args) throws Exception {
        String[] strings = {"", "plain", "a\0b", "\uD83D\uDE00", "\uD800", "snowman\u2603"};
        for (String text : strings) {
            // writeUTF is an independent JDK modified UTF-8 oracle, not serialization of Parcel.
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            new DataOutputStream(bytes).writeUTF(text);
            byte[] oracle = bytes.toByteArray();
            Parcel parcel = Parcel.obtain();
            parcel.writeString8(text);
            byte[] wire = parcel.marshall();
            int length = (oracle[0] & 255) * 256 + (oracle[1] & 255);
            check(wire[0] == (byte) length && wire[1] == (byte) (length >> 8));
            check(Arrays.equals(Arrays.copyOfRange(oracle, 2, oracle.length),
                                Arrays.copyOfRange(wire, 4, 4 + length)));
            check(wire[4 + length] == 0 && wire.length == 4 + ((length + 4) & ~3));
            parcel.setDataPosition(0);
            check(text.equals(parcel.readString8()) && parcel.dataAvail() == 0);
        }
        Uri[] uris = {
            Uri.parse("https://user@host:80/a%2Fb?q=a%2Bb#fragment"),
            Uri.parse("relative/path"), Uri.EMPTY,
            new Uri.Builder().scheme("https").authority("host").appendPath("a/b")
                .appendQueryParameter("q", "a+b").build(),
            new Uri.Builder().scheme("mailto").opaquePart("name@example.org").fragment("f").build(),
            new Uri.Builder().scheme("opaque").encodedOpaquePart("a%2Fb").build(),
            new Uri.Builder().encodedPath("/").build(),
            Uri.parse("scheme:a\0b\uD83D\uDE00"), null
        };
        for (Uri uri : uris) {
            Parcel parcel = Parcel.obtain();
            Uri.writeToParcel(parcel, uri);
            parcel.setDataPosition(0);
            Uri decoded = Uri.CREATOR.createFromParcel(parcel);
            check(uri == null ? decoded == null : uri.equals(decoded));
            check(parcel.dataAvail() == 0);
            if (uri != null) {
                check(uri.toString().equals(decoded.toString()));
                check(uri.getClass() == decoded.getClass());
                check(uri.describeContents() == 0 && decoded.describeContents() == 0);
                check(java.util.Objects.equals(uri.getEncodedPath(), decoded.getEncodedPath()));
                check(java.util.Objects.equals(uri.getEncodedQuery(), decoded.getEncodedQuery()));
                check(java.util.Objects.equals(uri.getEncodedFragment(), decoded.getEncodedFragment()));
            }
        }
        for (String value : new String[]{null, "", "a%2Fb", "a b"}) {
            for (Uri.Part part : new Uri.Part[]{Uri.Part.fromEncoded(value), Uri.Part.fromDecoded(value)}) {
                Parcel parcel = Parcel.obtain();
                part.writeTo(parcel);
                parcel.setDataPosition(0);
                Uri.Part restored = Uri.Part.readFrom(parcel);
                check(java.util.Objects.equals(part.getEncoded(), restored.getEncoded()));
                check(java.util.Objects.equals(part.getDecoded(), restored.getDecoded()));
                check(parcel.dataAvail() == 0);
            }
        }
        check(Uri.CREATOR.newArray(4).length == 4);
        Parcel bad = Parcel.obtain();
        bad.writeInt(99);
        bad.setDataPosition(0);
        try { Uri.CREATOR.createFromParcel(bad); throw new AssertionError("Unknown type accepted"); }
        catch (IllegalArgumentException expected) { checks++; }
        System.out.println(checks + " modified UTF-8/typed URI parcel checks passed");
    }
}
