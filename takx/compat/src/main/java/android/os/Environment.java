// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.os;

import java.io.File;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;

/** App-owned desktop storage, not Android shared-storage or mount emulation. */
public final class Environment {
    private Environment() {}

    private static String setting(String name) {
        String value = System.getProperty(name);
        return value == null || value.isBlank() ? System.getenv(name) : value;
    }

    public static File getExternalStorageDirectory() {
        String configured = setting("TAK_EXTERNAL_STORAGE");
        Path path;
        if (configured != null && !configured.isBlank()) {
            path = Path.of(configured);
        } else {
            String data = setting("TAK_APP_DATA_PATH");
            Path root = data == null || data.isBlank()
                    ? Path.of(System.getProperty("user.home"), ".tak", "desktop") : Path.of(data);
            path = root.resolve("external");
        }
        if (!path.isAbsolute()) throw new IllegalArgumentException("Desktop storage must be absolute");
        try {
            Files.createDirectories(path);
            return path.toRealPath().toFile();
        } catch (IOException error) {
            throw new UncheckedIOException("Cannot initialize desktop external storage", error);
        }
    }
}
