// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.content;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.CopyOnWriteArraySet;

final class DesktopSharedPreferences implements SharedPreferences {
    private final Path path;
    private final Set<OnSharedPreferenceChangeListener> listeners = new CopyOnWriteArraySet<>();
    DesktopSharedPreferences(Path path) { this.path = path; }

    private Map<String, Object> load() throws IOException {
        Properties properties = new Properties();
        if (Files.exists(path, LinkOption.NOFOLLOW_LINKS)) {
            try (InputStream input = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
                properties.load(input);
            }
        }
        Map<String, Object> values = new HashMap<>();
        try {
            for (String key : properties.stringPropertyNames()) values.put(decode(key), parse(properties.getProperty(key)));
        } catch (RuntimeException error) {
            throw new IOException("Invalid desktop preference data", error);
        }
        return values;
    }

    private synchronized Map<String, Object> read() {
        try (FileChannel channel = FileChannel.open(path.resolveSibling(path.getFileName() + ".lock"),
                StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
             FileLock lock = channel.lock()) {
            if (!lock.isValid()) throw new IOException("Preference lock is invalid");
            return load();
        } catch (IOException error) { throw new UncheckedIOException(error); }
    }

    private static String encode(String text) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(text.getBytes(StandardCharsets.UTF_8));
    }
    private static String decode(String text) {
        return new String(Base64.getUrlDecoder().decode(text), StandardCharsets.UTF_8);
    }
    private static Object parse(String text) {
        if (text.length() < 2 || text.charAt(1) != ':') throw new IllegalArgumentException("Missing preference type");
        String value = text.substring(2);
        switch (text.charAt(0)) {
            case 'S': return decode(value);
            case 'I': return Integer.valueOf(value);
            case 'L': return Long.valueOf(value);
            case 'F': return Float.valueOf(value);
            case 'B':
                if (!value.equals("true") && !value.equals("false")) throw new IllegalArgumentException("Invalid boolean");
                return Boolean.valueOf(value);
            case 'T':
                // A count distinguishes an empty set from a set containing "".
                int colon = value.indexOf(':');
                int count = Integer.parseInt(value.substring(0, colon));
                String[] items = count == 0 ? new String[0] : value.substring(colon + 1).split(",", -1);
                if (count < 0 || items.length != count) throw new IllegalArgumentException("Invalid set");
                Set<String> set = new HashSet<>();
                for (String item : items) set.add(decode(item));
                return Collections.unmodifiableSet(set);
            default: throw new IllegalArgumentException("Unknown preference type");
        }
    }

    private static String serialize(Object value) {
        if (value instanceof String) return "S:" + encode((String) value);
        if (value instanceof Integer) return "I:" + value;
        if (value instanceof Long) return "L:" + value;
        if (value instanceof Float) return "F:" + value;
        if (value instanceof Boolean) return "B:" + value;
        if (value instanceof Set<?>) {
            Set<?> set = (Set<?>) value;
            List<String> encoded = new ArrayList<>();
            for (Object item : set) encoded.add(encode((String) item));
            Collections.sort(encoded);
            return "T:" + set.size() + ":" + String.join(",", encoded);
        }
        throw new IllegalArgumentException("Unsupported preference type");
    }
    private <T> T get(String key, T fallback, Class<T> type) {
        Object value = read().get(Objects.requireNonNull(key));
        return value == null ? fallback : type.cast(value);
    }
    public Map<String, ?> getAll() { return Collections.unmodifiableMap(read()); }
    public String getString(String key, String fallback) { return get(key, fallback, String.class); }
    public Set<String> getStringSet(String key, Set<String> fallback) {
        Object value = read().get(Objects.requireNonNull(key));
        if (value == null) return fallback;
        if (!(value instanceof Set<?>)) throw new ClassCastException("Preference is not a string set");
        @SuppressWarnings("unchecked") Set<String> set = (Set<String>) value;
        return set;
    }
    public int getInt(String key, int fallback) { return get(key, fallback, Integer.class); }
    public long getLong(String key, long fallback) { return get(key, fallback, Long.class); }
    public float getFloat(String key, float fallback) { return get(key, fallback, Float.class); }
    public boolean getBoolean(String key, boolean fallback) { return get(key, fallback, Boolean.class); }
    public boolean contains(String key) { return read().containsKey(Objects.requireNonNull(key)); }
    public Editor edit() { return new Edit(); }
    public void registerOnSharedPreferenceChangeListener(OnSharedPreferenceChangeListener listener) { listeners.add(Objects.requireNonNull(listener)); }
    public void unregisterOnSharedPreferenceChangeListener(OnSharedPreferenceChangeListener listener) { listeners.remove(listener); }

    private final class Edit implements Editor {
        private final Map<String, Object> updates = new HashMap<>();
        private boolean clear;
        private Editor put(String key, Object value) { updates.put(Objects.requireNonNull(key), value); return this; }
        public Editor putString(String key, String value) { return put(key, value); }
        public Editor putStringSet(String key, Set<String> value) {
            return put(key, value == null ? null : Set.copyOf(value));
        }
        public Editor putInt(String key, int value) { return put(key, value); }
        public Editor putLong(String key, long value) { return put(key, value); }
        public Editor putFloat(String key, float value) { return put(key, value); }
        public Editor putBoolean(String key, boolean value) { return put(key, value); }
        public Editor remove(String key) { return put(key, null); }
        public Editor clear() { clear = true; return this; }
        public boolean commit() {
            Set<String> changed = new HashSet<>();
            synchronized (DesktopSharedPreferences.this) {
                Path temporary = null;
                try (FileChannel channel = FileChannel.open(path.resolveSibling(path.getFileName() + ".lock"),
                        StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
                     FileLock lock = channel.lock()) {
                    if (!lock.isValid()) throw new IOException("Preference lock is invalid");
                    Map<String, Object> before = load();
                    Map<String, Object> after = clear ? new HashMap<>() : new HashMap<>(before);
                    updates.forEach((key, value) -> { if (value == null) after.remove(key); else after.put(key, value); });
                    changed.addAll(before.keySet()); changed.addAll(after.keySet());
                    changed.removeIf(key -> Objects.equals(before.get(key), after.get(key)));
                    Properties properties = new Properties();
                    after.forEach((key, value) -> properties.setProperty(encode(key), serialize(value)));
                    ByteArrayOutputStream output = new ByteArrayOutputStream();
                    properties.store(output, "UDS desktop preferences v1");
                    temporary = Files.createTempFile(path.getParent(), ".preferences-", ".tmp");
                    try (FileChannel data = FileChannel.open(temporary, StandardOpenOption.WRITE)) {
                        ByteBuffer buffer = ByteBuffer.wrap(output.toByteArray());
                        while (buffer.hasRemaining()) data.write(buffer);
                        data.force(true);
                    }
                    Files.move(temporary, path, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
                    updates.clear(); clear = false;
                } catch (IOException error) {
                    return false;
                } finally {
                    if (temporary != null) try { Files.deleteIfExists(temporary); } catch (IOException ignored) { /* no data committed */ }
                }
            }
            for (String key : changed) for (OnSharedPreferenceChangeListener listener : listeners)
                listener.onSharedPreferenceChanged(DesktopSharedPreferences.this, key);
            return true;
        }
        public void apply() {
            if (!commit()) throw new UncheckedIOException(new IOException("Cannot persist desktop preferences"));
        }
    }
}
