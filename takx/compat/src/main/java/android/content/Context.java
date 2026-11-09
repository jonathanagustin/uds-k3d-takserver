// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.content;

import android.content.pm.PackageManager;
import android.content.res.AssetManager;
import android.content.res.Resources;
import java.io.File;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.ConcurrentHashMap;

/** Concrete desktop context. This is not an Android application/service context. */
public class Context {
    public static final int MODE_PRIVATE = 0;
    private static final ConcurrentHashMap<Path, SharedPreferences> PREFERENCES = new ConcurrentHashMap<>();
    private final Path appRoot;
    private final PackageManager packageManager;
    private final Path files;
    private final Path cache;
    private final String packageName;
    private final Resources resources;

    public Context() {
        this(defaultDataPath(), System.getProperty("uds.desktop.package", "gov.tak.desktop"),
             defaultLoader());
    }

    public Context(Path appDataPath, String packageName, ClassLoader loader) {
        if (!packageName.matches("[A-Za-z_][A-Za-z0-9_.]*"))
            throw new IllegalArgumentException("Invalid desktop package name");
        this.packageName = packageName;
        try {
            Path root = appDataPath.toAbsolutePath().normalize();
            Files.createDirectories(root);
            root = root.toRealPath();
            appRoot = root;
            String configuredLibrary = System.getProperty("uds.desktop.nativeLibraryPath");
            Path library;
            if (configuredLibrary == null || configuredLibrary.isBlank()) library = directory(root, "lib");
            else {
                library = Path.of(configuredLibrary);
                if (!library.isAbsolute()) throw new IllegalArgumentException("Native library path must be absolute");
            }
            packageManager = new PackageManager(packageName, library);
            files = directory(root, "files");
            cache = directory(root, "cache");
        } catch (IOException error) {
            throw new UncheckedIOException("Cannot initialize desktop app data", error);
        }
        resources = new Resources(loader, packageName);
    }

    private static ClassLoader defaultLoader() {
        ClassLoader loader = Thread.currentThread().getContextClassLoader();
        return loader == null ? Context.class.getClassLoader() : loader;
    }

    private static Path defaultDataPath() {
        String value = System.getProperty("TAK_APP_DATA_PATH");
        if (value == null || value.isBlank()) value = System.getenv("TAK_APP_DATA_PATH");
        if (value == null || value.isBlank())
            return Path.of(System.getProperty("user.home"), ".tak", "desktop");
        Path path = Path.of(value);
        if (!path.isAbsolute()) throw new IllegalArgumentException("TAK_APP_DATA_PATH must be absolute");
        return path;
    }

    static Path directory(Path root, String name) throws IOException {
        Path path = root.resolve(name);
        Files.createDirectories(path);
        path = path.toRealPath();
        if (!path.startsWith(root)) throw new IOException("App data directory escapes its root");
        return path;
    }

    public PackageManager getPackageManager() { return packageManager; }
    public ContentResolver getContentResolver() { return new ContentResolver(resources); }
    public File getDatabasePath(String name) {
        if (name == null || !name.matches("[A-Za-z0-9_][A-Za-z0-9_.-]*") || name.contains(".."))
            throw new IllegalArgumentException("Database name must be a single private filename");
        try {
            Path root = directory(appRoot, "databases");
            Path file = root.resolve(name);
            if (Files.exists(file, java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
                file = file.toRealPath();
                if (!file.startsWith(root) || Files.isDirectory(file))
                    throw new IOException("Database path escapes private directory or is a directory");
            }
            return file.toFile();
        } catch (IOException error) { throw new UncheckedIOException(error); }
    }

    public File getFilesDir() { return files.toFile(); }
    public File getCacheDir() { return cache.toFile(); }
    public String getPackageName() { return packageName; }
    public Context getApplicationContext() { return this; }
    public Resources getResources() { return resources; }
    public AssetManager getAssets() { return resources.getAssets(); }
    public String getString(int id) { return resources.getString(id); }
    public String getString(int id, Object... arguments) { return resources.getString(id, arguments); }

    public SharedPreferences getSharedPreferences(String name, int mode) {
        if (mode != MODE_PRIVATE) throw new UnsupportedOperationException("Only MODE_PRIVATE is supported");
        if (name == null || !name.matches("[A-Za-z0-9_-][A-Za-z0-9_.-]*") || name.contains(".."))
            throw new IllegalArgumentException("Invalid preference name");
        try {
            Path path = directory(files, "shared_prefs").resolve(name + ".properties");
            return PREFERENCES.computeIfAbsent(path, DesktopSharedPreferences::new);
        } catch (IOException error) {
            throw new UncheckedIOException(error);
        }
    }
}
