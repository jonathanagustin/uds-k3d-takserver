// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import android.annotation.SuppressLint;
import android.os.Environment;
import android.util.Patterns;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import java.lang.annotation.ElementType;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;

public final class PlatformServicesCompatibilityTest {
    private static int checks;
    private static void check(boolean value) {
        checks++;
        if (!value) throw new AssertionError("platform contract " + checks);
    }
    private static void rejects(Runnable action, Class<? extends Throwable> kind) {
        checks++;
        try { action.run(); } catch (Throwable error) {
            if (kind.isInstance(error)) return;
            throw new AssertionError("unexpected failure", error);
        }
        throw new AssertionError("missing failure");
    }
    public static void main(String[] args) throws Exception {
        Path work = Path.of(args[0]).toRealPath();
        System.setProperty("TAK_EXTERNAL_STORAGE", "");
        System.setProperty("TAK_APP_DATA_PATH", work.resolve("data").toString());
        Path storage = Environment.getExternalStorageDirectory().toPath();
        check(storage.equals(work.resolve("data/external")));
        check(Files.isDirectory(storage));
        Files.writeString(storage.resolve("actual.txt"), "stored");
        check(Files.readString(Environment.getExternalStorageDirectory().toPath().resolve("actual.txt")).equals("stored"));
        Path custom = work.resolve("explicit storage");
        System.setProperty("TAK_EXTERNAL_STORAGE", custom.toString());
        check(Environment.getExternalStorageDirectory().toPath().equals(custom));
        System.setProperty("TAK_EXTERNAL_STORAGE", "relative");
        rejects(Environment::getExternalStorageDirectory, IllegalArgumentException.class);
        Path file = work.resolve("file"); Files.writeString(file, "not a directory");
        System.setProperty("TAK_EXTERNAL_STORAGE", file.toString());
        rejects(Environment::getExternalStorageDirectory, java.io.UncheckedIOException.class);
        for (int value = 0; value < 256; value++) {
            check(Patterns.IP_ADDRESS.matcher("192.168.0." + value).matches());
            check(Patterns.IP_ADDRESS.matcher("192.168." + value + ".1").matches());
            check(Patterns.IP_ADDRESS.matcher(value + ".1.2.3").matches() == (value != 0));
        }
        for (String invalid : new String[]{"", "1.2.3", "256.1.2.3", "1.2.3.256", "1.2.3.4x", " 1.2.3.4", "::1", "2001:db8::1"}) {
            check(!Patterns.IP_ADDRESS.matcher(invalid).matches());
        }
        // These legacy leading-zero choices are from the actual AOSP regex.
        check(Patterns.IP_ADDRESS.matcher("001.002.003.004").matches());
        check(!Patterns.IP_ADDRESS.matcher("01.2.3.4").matches());
        check(SuppressLint.class.getAnnotation(Retention.class).value() == RetentionPolicy.CLASS);
        check(Set.of(SuppressLint.class.getAnnotation(Target.class).value()).equals(Set.of(
                ElementType.TYPE, ElementType.FIELD, ElementType.METHOD, ElementType.PARAMETER,
                ElementType.CONSTRUCTOR, ElementType.LOCAL_VARIABLE)));
        check(SuppressLint.class.getDeclaredMethod("value").getReturnType() == String[].class);
        System.out.println("PASS desktop storage, legacy IPv4 and annotation contracts: " + checks);
    }
}
