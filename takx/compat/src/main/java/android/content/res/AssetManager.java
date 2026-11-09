// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.content.res;

import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.util.Objects;

/** Classpath assets under assets/, with caller-owned streams. */
public class AssetManager {
    private final ClassLoader loader;
    public AssetManager(ClassLoader loader) { this.loader = Objects.requireNonNull(loader); }
    static String safePath(String path) {
        if (path == null || path.isEmpty() || !path.matches("[A-Za-z0-9_./-]+") || path.startsWith("/"))
            throw new IllegalArgumentException("Invalid classpath resource path");
        for (String part : path.split("/", -1))
            if (part.isEmpty() || part.equals(".") || part.equals(".."))
                throw new IllegalArgumentException("Resource traversal is not permitted");
        return path;
    }
    public InputStream open(String path) throws IOException {
        InputStream stream = loader.getResourceAsStream("assets/" + safePath(path));
        if (stream == null) throw new FileNotFoundException("Asset not found: " + path);
        return stream;
    }
}
