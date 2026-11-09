// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.content.res;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Explicit UTF-8 classpath catalog, not Android binary resource-table support. */
public class Resources {
    public static final String CATALOG = "META-INF/uds-desktop-resources.properties";
    private final ClassLoader loader;
    private final String packageName;
    private final AssetManager assets;
    private final Map<String, Integer> identifiers = new HashMap<>();
    private final Map<Integer, Entry> entries = new HashMap<>();
    private static final class Entry {
        final String type;
        final String path;
        Entry(String type, String path) { this.type = type; this.path = path; }
    }
    public static class NotFoundException extends RuntimeException {
        private static final long serialVersionUID = 1L;
        public NotFoundException(String message) { super(message); }
        public NotFoundException(String message, Throwable cause) { super(message, cause); }
    }
    public Resources(ClassLoader loader, String packageName) {
        this.loader = Objects.requireNonNull(loader);
        this.packageName = Objects.requireNonNull(packageName);
        assets = new AssetManager(loader);
        try {
            var urls = Collections.list(loader.getResources(CATALOG));
            if (urls.size() > 1) throw new IOException("Multiple desktop resource catalogs are ambiguous");
            if (urls.isEmpty()) return; // An empty catalog supplies no invented resources.
            Properties catalog;
            try (Reader input = new InputStreamReader(urls.get(0).openStream(), StandardCharsets.UTF_8.newDecoder())) {
                catalog = properties(input);
            }
            int id = 1;
            for (String key : new TreeSet<>(catalog.stringPropertyNames())) {
                String[] parts = key.split("/", -1);
                if (parts.length != 3 || !parts[0].matches("[A-Za-z_][A-Za-z0-9_.]*") ||
                    !Set.of("string", "array", "color", "raw").contains(parts[1]) ||
                    !parts[2].matches("[A-Za-z_][A-Za-z0-9_]*"))
                    throw new IOException("Invalid or unsupported desktop resource catalog key");
                String path = AssetManager.safePath(catalog.getProperty(key));
                if (loader.getResource(path) == null) throw new IOException("Catalog resource file is missing: " + path);
                identifiers.put(key, id);
                entries.put(id++, new Entry(parts[1], path));
            }
        } catch (IOException | IllegalArgumentException error) {
            throw new NotFoundException("Cannot load desktop resource catalog", error);
        }
    }
    private static Properties properties(Reader input) throws IOException {
        Properties result = new Properties() {
            @Override public synchronized Object put(Object key, Object value) {
                if (containsKey(key)) throw new IllegalArgumentException("Duplicate resource key");
                return super.put(key, value);
            }
        };
        result.load(input);
        return result;
    }
    public AssetManager getAssets() { return assets; }
    public int getIdentifier(String name, String type, String pkg) {
        if (name == null) throw new NullPointerException("name");
        int colon = name.indexOf(':');
        if (colon >= 0) { pkg = name.substring(0, colon); name = name.substring(colon + 1); }
        int slash = name.indexOf('/');
        if (slash >= 0) { type = name.substring(0, slash); name = name.substring(slash + 1); }
        if (pkg == null) pkg = packageName;
        if (type == null) return 0;
        if (!name.matches("[A-Za-z_][A-Za-z0-9_]*")) throw new IllegalArgumentException("Invalid resource name");
        return identifiers.getOrDefault(pkg + "/" + type + "/" + name, 0);
    }
    private Entry entry(int id, String type) {
        Entry value = entries.get(id);
        if (value == null || type != null && !value.type.equals(type))
            throw new NotFoundException("Resource identifier is absent or has the wrong type: " + id);
        return value;
    }
    public InputStream openRawResource(int id) {
        Entry value = entry(id, null);
        InputStream stream = loader.getResourceAsStream(value.path);
        if (stream == null) throw new NotFoundException("Catalog resource file is missing");
        return stream;
    }
    private String text(int id, String type) {
        entry(id, type);
        try (InputStream stream = openRawResource(id)) {
            return StandardCharsets.UTF_8.newDecoder().decode(java.nio.ByteBuffer.wrap(stream.readAllBytes())).toString();
        } catch (IOException error) { throw new NotFoundException("Cannot read resource", error); }
    }
    public String getString(int id) { return text(id, "string"); }
    public String getString(int id, Object... arguments) { return String.format(Locale.getDefault(), getString(id), arguments); }
    public int getColor(int id) {
        String value = text(id, "color").strip();
        if (!value.matches("#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?")) throw new NotFoundException("Invalid color resource");
        long color = Long.parseLong(value.substring(1), 16);
        return (int) (value.length() == 7 ? color | 0xff000000L : color);
    }
    public String[] getStringArray(int id) {
        try {
            Properties values = properties(new StringReader(text(id, "array")));
            int count = Integer.parseInt(values.getProperty("count"));
            if (count < 0 || count > 100000 || values.size() != count + 1) throw new IllegalArgumentException();
            String[] result = new String[count];
            for (int i = 0; i < count; i++) result[i] = Objects.requireNonNull(values.getProperty(Integer.toString(i)));
            return result;
        } catch (IOException | IllegalArgumentException | NullPointerException error) {
            throw new NotFoundException("Invalid string array resource", error);
        }
    }
}
