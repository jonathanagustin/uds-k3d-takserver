// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.Resources;
import android.preference.PreferenceManager;
import java.io.*;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;

public final class DesktopContextTest {
    private static int checks;
    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }
    private static void fails(Class<? extends Throwable> type, Runnable action) {
        checks++;
        try { action.run(); } catch (Throwable error) {
            if (type.isInstance(error)) return;
            throw new AssertionError("Wrong exception", error);
        }
        throw new AssertionError("Expected " + type.getSimpleName());
    }
    private static Process child(Path data, String mode, String... extra) throws IOException {
        List<String> command = new ArrayList<>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
            "-DTAK_APP_DATA_PATH=" + data, "-cp", System.getProperty("java.class.path"), DesktopContextTest.class.getName(), mode));
        command.addAll(List.of(extra));
        return new ProcessBuilder(command).inheritIO().start();
    }
    private static int finish(Process process) throws InterruptedException {
        if (!process.waitFor(30, java.util.concurrent.TimeUnit.SECONDS)) {
            process.destroyForcibly();
            throw new AssertionError("Child JVM timed out");
        }
        return process.exitValue();
    }
    private static void persisted(String mode, String[] args) {
        SharedPreferences preferences = PreferenceManager.getDefaultSharedPreferences(new Context());
        if (mode.equals("write")) {
            check(preferences.edit().putString("message", "hello\n世界").putStringSet("set", Set.of("", "a,b", "世界"))
                .putInt("int", 42).putLong("long", Long.MAX_VALUE).putFloat("float", 1.25f).putBoolean("bool", true).commit(), "commit");
        } else if (mode.equals("read")) {
            check(preferences.getString("message", "").equals("hello\n世界"), "new JVM string");
            check(preferences.getStringSet("set", Set.of()).equals(Set.of("", "a,b", "世界")), "new JVM set");
            check(preferences.getInt("int", 0) == 42 && preferences.getLong("long", 0) == Long.MAX_VALUE, "new JVM numbers");
            check(preferences.getFloat("float", 0) == 1.25f && preferences.getBoolean("bool", false), "new JVM types");
        } else {
            for (int i = 0; i < 10; i++) check(preferences.edit().putInt(args[1], i).commit(), "concurrent JVM commit");
        }
    }
    public static void main(String[] args) throws Exception {
        if (args.length > 0) { persisted(args[0], args); return; }
        Path data = Files.createTempDirectory("desktop-context-test-");
        System.setProperty("TAK_APP_DATA_PATH", data.toString());
        try {
            Context one = new Context(), two = new Context();
            check(one.getFilesDir().equals(two.getFilesDir()), "consistent files");
            check(one.getCacheDir().equals(two.getCacheDir()), "consistent cache");
            check(one.getFilesDir().toPath().equals(data.resolve("files")), "app data files");
            check(one.getCacheDir().toPath().equals(data.resolve("cache")), "app data cache");
            check(one.getApplicationContext() == one, "application context");
            check(finish(child(data, "write")) == 0, "writer JVM");
            check(finish(child(data, "read")) == 0, "reader JVM restart");
            List<Process> writers = new ArrayList<>();
            for (int i = 0; i < 4; i++) writers.add(child(data, "concurrent", "writer" + i));
            for (Process process : writers) check(finish(process) == 0, "concurrent writer");
            SharedPreferences preferences = PreferenceManager.getDefaultSharedPreferences(two);
            for (int i = 0; i < 4; i++) check(preferences.getInt("writer" + i, -1) == 9, "no lost concurrent keys");
            // Context caches preferences by their canonical path. Distinct
            // Context objects must therefore share one synchronized instance,
            // before taking OS locks that cannot overlap within a JVM.
            check(preferences == PreferenceManager.getDefaultSharedPreferences(one), "same canonical preference instance");
            java.util.concurrent.ExecutorService threads = java.util.concurrent.Executors.newFixedThreadPool(4);
            try {
                List<java.util.concurrent.Future<?>> writes = new ArrayList<>();
                for (int i = 0; i < 4; i++) {
                    final int writer = i;
                    writes.add(threads.submit(() -> {
                        SharedPreferences shared = PreferenceManager.getDefaultSharedPreferences(new Context());
                        for (int j = 0; j < 10; j++) {
                            if (!shared.edit().putInt("thread" + writer, j).commit())
                                throw new AssertionError("Same-JVM commit failed");
                        }
                    }));
                }
                for (java.util.concurrent.Future<?> write : writes) write.get(30, java.util.concurrent.TimeUnit.SECONDS);
            } finally { threads.shutdownNow(); }
            for (int i = 0; i < 4; i++) check(preferences.getInt("thread" + i, -1) == 9, "same-JVM writers preserved");
            fails(ClassCastException.class, () -> preferences.getString("int", ""));
            fails(UnsupportedOperationException.class, () -> preferences.getAll().clear());
            fails(UnsupportedOperationException.class, () -> preferences.getStringSet("set", Set.of()).clear());
            AtomicInteger notifications = new AtomicInteger();
            SharedPreferences.OnSharedPreferenceChangeListener listener = (p, key) -> notifications.incrementAndGet();
            preferences.registerOnSharedPreferenceChangeListener(listener);
            preferences.edit().putString("message", null).apply();
            check(!preferences.contains("message") && notifications.get() == 1, "remove and listener");
            preferences.unregisterOnSharedPreferenceChangeListener(listener);
            preferences.edit().clear().putBoolean("only", true).apply();
            check(preferences.getAll().equals(Map.of("only", true)), "clear before additions");
            SharedPreferences.Editor editor = preferences.edit().putInt("value", 1);
            check(editor.commit(), "reusable editor first commit");
            preferences.edit().putInt("value", 2).apply();
            check(editor.commit() && preferences.getInt("value", 0) == 2, "editor modifications reset");
            fails(IllegalArgumentException.class, () -> one.getSharedPreferences("../escape", 0));
            fails(UnsupportedOperationException.class, () -> one.getSharedPreferences("mode", 1));
            Files.writeString(data.resolve("files/shared_prefs/corrupt.properties"), "a=Z:bad");
            fails(UncheckedIOException.class, () -> one.getSharedPreferences("corrupt", 0).getAll());
            check(!one.getSharedPreferences("corrupt", 0).edit().putInt("x", 1).commit(), "corruption not overwritten");
            Files.createDirectory(data.resolve("files/shared_prefs/unwritable.properties"));
            fails(UncheckedIOException.class, () -> one.getSharedPreferences("unwritable", 0).edit().putInt("x", 1).apply());
            Path outside = Files.createTempDirectory("desktop-outside-");
            Files.createSymbolicLink(data.resolve("files/shared_prefs/link.properties"), outside.resolve("target"));
            check(!one.getSharedPreferences("link", 0).edit().putInt("x", 1).commit(), "preference symlink rejected");
            check(!Files.exists(outside.resolve("target")), "outside not modified");
            Files.delete(outside);
            Path escaped = Files.createTempDirectory("desktop-escape-");
            Path app = Files.createDirectory(data.resolve("app"));
            Files.createSymbolicLink(app.resolve("files"), escaped);
            fails(UncheckedIOException.class, () -> new Context(app, "test.app", DesktopContextTest.class.getClassLoader()));
            Files.delete(escaped);
            resources(data);
            System.setProperty("TAK_APP_DATA_PATH", "relative/path");
            fails(IllegalArgumentException.class, Context::new);
            System.out.println("Desktop context checks passed: " + checks);
        } finally {
            try (var paths = Files.walk(data)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).collect(java.util.stream.Collectors.toList())) Files.deleteIfExists(path);
            }
        }
    }
    private static void resources(Path data) throws Exception {
        Path cp = Files.createDirectory(data.resolve("classpath"));
        Files.createDirectories(cp.resolve("META-INF")); Files.createDirectories(cp.resolve("res")); Files.createDirectories(cp.resolve("assets/maps"));
        Files.writeString(cp.resolve("META-INF/uds-desktop-resources.properties"),
            "test.app/string/greeting=res/greeting.txt\ntest.app/array/labels=res/labels.properties\ntest.app/color/accent=res/color.txt\ntest.app/raw/payload=res/payload.bin\ntest.app/drawable/image=res/payload.bin\n");
        Files.writeString(cp.resolve("res/greeting.txt"), "Hello 世界 %s", StandardCharsets.UTF_8);
        Files.writeString(cp.resolve("res/labels.properties"), "count=3\n0=one\n1=世界\n2=\n", StandardCharsets.UTF_8);
        Files.writeString(cp.resolve("res/color.txt"), "#80402010\n");
        Files.write(cp.resolve("res/payload.bin"), new byte[]{0, 1, -1});
        Files.writeString(cp.resolve("assets/maps/map.txt"), "actual asset");
        try (URLClassLoader loader = new URLClassLoader(new java.net.URL[]{cp.toUri().toURL()}, null)) {
            Context context = new Context(data.resolve("resources-app"), "test.app", loader);
            Resources r = context.getResources(), again = new Resources(loader, "test.app");
            int string = r.getIdentifier("greeting", "string", "test.app");
            check(string > 0 && string == again.getIdentifier("test.app:string/greeting", null, null), "consistent catalog IDs");
            check(r.getIdentifier("missing", "string", "test.app") == 0, "missing identifier");
            check(r.getIdentifier("greeting", "string", "other.app") == 0, "package isolation");
            check(context.getString(string, "reader").equals("Hello 世界 reader"), "real UTF-8 string");
            int array = r.getIdentifier("labels", "array", "test.app");
            String[] labels = r.getStringArray(array); labels[0] = "changed";
            check(Arrays.equals(r.getStringArray(array), new String[]{"one", "世界", ""}), "real defensive array");
            check(r.getColor(r.getIdentifier("accent", "color", "test.app")) == 0x80402010, "ARGB color");
            int drawable = r.getIdentifier("image", "drawable", "test.app");
            check(drawable > 0 && r.getIdentifier("image", "drawable", "other.app") == 0, "drawable namespace isolation");
            try (InputStream input = r.openRawResource(drawable)) { check(Arrays.equals(input.readAllBytes(), new byte[]{0, 1, -1}), "real drawable bytes without getDrawable emulation"); }
            fails(Resources.NotFoundException.class, () -> r.openRawResourceForPackage("test.app", drawable));
            int raw = r.getIdentifier("payload", "raw", "test.app");
            try (InputStream input = r.openRawResource(raw)) { check(Arrays.equals(input.readAllBytes(), new byte[]{0, 1, -1}), "real raw bytes"); }
            try (InputStream input = context.getAssets().open("maps/map.txt")) {
                check(new String(input.readAllBytes(), StandardCharsets.UTF_8).equals("actual asset"), "real asset");
            }
            fails(Resources.NotFoundException.class, () -> r.getString(0));
            fails(Resources.NotFoundException.class, () -> r.getString(raw));
            for (String path : List.of("../res/payload.bin", "/absolute", "maps/../map.txt", "maps//map.txt", "maps\\map.txt", "%2e%2e/escape"))
                fails(IllegalArgumentException.class, () -> { try { context.getAssets().open(path); } catch (IOException e) { throw new UncheckedIOException(e); } });
            fails(UncheckedIOException.class, () -> { try { context.getAssets().open("missing"); } catch (IOException e) { throw new UncheckedIOException(e); } });
            Files.write(cp.resolve("res/greeting.txt"), new byte[]{(byte) 0xff});
            fails(Resources.NotFoundException.class, () -> r.getString(string));
            Files.writeString(cp.resolve("res/color.txt"), "not-a-color");
            fails(Resources.NotFoundException.class, () -> r.getColor(r.getIdentifier("accent", "color", "test.app")));
            Files.writeString(cp.resolve("res/labels.properties"), "count=2\n0=only-one\n");
            fails(Resources.NotFoundException.class, () -> r.getStringArray(array));
            Files.writeString(cp.resolve("META-INF/uds-desktop-resources.properties"), "test.app/layout/image=res/payload.bin\n");
            fails(Resources.NotFoundException.class, () -> new Resources(loader, "test.app"));
            Files.writeString(cp.resolve("META-INF/uds-desktop-resources.properties"), "test.app/raw/bad=../escape\n");
            fails(Resources.NotFoundException.class, () -> new Resources(loader, "test.app"));
            Files.writeString(cp.resolve("META-INF/uds-desktop-resources.properties"), "test.app/raw/bad=res/missing\n");
            fails(Resources.NotFoundException.class, () -> new Resources(loader, "test.app"));
            Files.writeString(cp.resolve("META-INF/uds-desktop-resources.properties"), "test.app/raw/payload=res/payload.bin\ntest.app/raw/payload=res/payload.bin\n");
            fails(Resources.NotFoundException.class, () -> new Resources(loader, "test.app"));
        }
        try (URLClassLoader loader = new URLClassLoader(new java.net.URL[0], null)) {
            Resources empty = new Resources(loader, "test.app");
            check(empty.getIdentifier("absent", "string", null) == 0, "empty catalog not fabricated");
            fails(Resources.NotFoundException.class, () -> empty.openRawResource(0));
        }
    }
}
