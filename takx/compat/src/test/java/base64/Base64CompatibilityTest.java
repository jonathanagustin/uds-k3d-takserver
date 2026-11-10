// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package base64;

import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Random;

public final class Base64CompatibilityTest {
    private static int checks;
    private static void check(boolean condition) {
        checks++;
        if (!condition) throw new AssertionError("Base64 check " + checks);
    }
    private static byte[] ascii(String text) { return text.getBytes(StandardCharsets.US_ASCII); }
    private static void encoded(String input, int flags, String expected) {
        check(Base64.encodeToString(ascii(input), flags).equals(expected));
        check(Arrays.equals(Base64.encode(ascii(input), flags), ascii(expected)));
    }
    private static void decoded(String input, int flags, String expected) {
        check(Arrays.equals(Base64.decode(input, flags), ascii(expected)));
        check(Arrays.equals(Base64.decode(ascii(input), flags), ascii(expected)));
    }
    private static void vectors() {
        encoded("", Base64.DEFAULT, "");
        encoded("f", Base64.DEFAULT, "Zg==\n");
        encoded("f" + "o", Base64.NO_WRAP, "Zm8=");
        encoded("foo", Base64.CRLF, "Zm9v\r\n");
        encoded("f", Base64.NO_PADDING, "Zg\n");
        encoded("f", Base64.NO_PADDING | Base64.NO_WRAP, "Zg");
        encoded("f", Base64.NO_WRAP | Base64.CRLF, "Zg==");
        check(Base64.encodeToString(new byte[] {(byte)251, (byte)255}, Base64.NO_WRAP).equals("+/8="));
        check(Base64.encodeToString(new byte[] {(byte)251, (byte)255}, Base64.URL_SAFE | Base64.NO_WRAP).equals("-_8="));
        decoded("Zg==", Base64.DEFAULT, "f"); decoded("Zg", Base64.DEFAULT, "f");
        decoded("Zm8", Base64.DEFAULT, "f" + "o"); decoded(" Z\tm\r8=\n", Base64.DEFAULT, "f" + "o");
        decoded("Z!m$8=", Base64.DEFAULT, "f" + "o"); // Android skips non-alphabet bytes, not just whitespace.
        decoded("Zh==", Base64.DEFAULT, "f"); // Unused tail bits are not rejected.
        check(Arrays.equals(Base64.decode("-_8=", Base64.URL_SAFE), new byte[] {(byte)251, (byte)255}));
        for (String invalid : new String[] {"A", "A===", "AA=", "AA===", "AAAA=", "=AAA", "AA==AA", "AA=A", "AAA==="}) {
            try { Base64.decode(invalid, Base64.DEFAULT); throw new AssertionError("accepted bad padding: " + invalid); }
            catch (IllegalArgumentException expected) { check(true); }
        }
        decoded("!!!", Base64.DEFAULT, "");
        decoded("Z\u3042g==", Base64.DEFAULT, "f");
        check(Arrays.equals(Base64.decode(new byte[] {'Z', (byte)255, 'g', '=', '='}, Base64.DEFAULT), ascii("f")));
        check(Base64.encodeToString(ascii("user:password"), Base64.NO_WRAP).equals("dXNlcjpwYXNzd29yZA=="));
        check(Base64.encodeToString(ascii("user:password"), Base64.DEFAULT).endsWith("\n"));
    }
    private static void randomizedFlagsAndLines() {
        Random random = new Random(18001);
        for (int length = 0; length <= 200; length++) {
            byte[] input = new byte[length]; random.nextBytes(input);
            for (int flags = 0; flags < 32; flags++) {
                byte[] encoded = Base64.encode(input, flags);
                check(Arrays.equals(Base64.decode(encoded, flags), input));
                java.util.Base64.Encoder encoder = (flags & Base64.URL_SAFE) == 0 ?
                    java.util.Base64.getEncoder() : java.util.Base64.getUrlEncoder();
                if ((flags & Base64.NO_PADDING) != 0) encoder = encoder.withoutPadding();
                String plain = encoder.encodeToString(input);
                String expected = plain;
                if ((flags & Base64.NO_WRAP) == 0 && !plain.isEmpty()) {
                    String newline = (flags & Base64.CRLF) == 0 ? "\n" : "\r\n";
                    StringBuilder wrapped = new StringBuilder();
                    for (int i = 0; i < plain.length(); i += 76)
                        wrapped.append(plain, i, Math.min(i + 76, plain.length())).append(newline);
                    expected = wrapped.toString();
                }
                check(Arrays.equals(encoded, ascii(expected)));
                byte[] envelope = new byte[length + 4];
                System.arraycopy(input, 0, envelope, 2, length);
                check(Arrays.equals(Base64.encode(envelope, 2, length, flags), encoded));
                byte[] framed = new byte[encoded.length + 4];
                System.arraycopy(encoded, 0, framed, 2, encoded.length);
                check(Arrays.equals(Base64.decode(framed, 2, encoded.length, flags), input));
            }
        }
    }
    private static String outcome(byte[] bytes, int offset, int length, boolean decode) {
        try {
            byte[] result = decode ? Base64.decode(bytes, offset, length, 0) : Base64.encode(bytes, offset, length, 0);
            return Arrays.toString(result);
        } catch (RuntimeException error) { return error.getClass().getSimpleName(); }
    }
    public static void main(String[] args) {
        vectors(); randomizedFlagsAndLines();
        StringBuilder ranges = new StringBuilder();
        for (int[] range : new int[][] {{0, 0}, {1, 2}, {2, 2}, {-1, 1}, {0, -1}, {0, 5}, {5, 0}, {Integer.MAX_VALUE, 1}}) {
            ranges.append(outcome(ascii("Zm8="), range[0], range[1], true)).append('|');
            ranges.append(outcome(ascii("abcd"), range[0], range[1], false)).append('|');
        }
        ranges.append(outcome(null, 0, 1, true)).append('|').append(outcome(null, 0, 1, false));
        System.out.println("RANGE CONTRACTS " + ranges);
        System.out.println("PASS Base64 Android flag/permissive-decoding contracts: " + checks + " checks");
    }
}
