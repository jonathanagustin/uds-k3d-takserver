// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.content.pm;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;

/** Explicit metadata for one real desktop application directory. */
public final class PackageManager {
    private final String ownPackage;
    private final Path nativeDirectory;
    public static class NameNotFoundException extends Exception {
        private static final long serialVersionUID = 1L;
        public NameNotFoundException(String name) { super(name); }
    }
    public PackageManager(String ownPackage, Path nativeDirectory) {
        this.ownPackage = java.util.Objects.requireNonNull(ownPackage);
        try {
            this.nativeDirectory = nativeDirectory.toRealPath();
            if (!Files.isDirectory(this.nativeDirectory)) throw new IOException("Native library directory is not a directory");
        } catch (IOException error) { throw new UncheckedIOException(error); }
    }
    public ApplicationInfo getApplicationInfo(String name, int flags) throws NameNotFoundException {
        if (flags != 0) throw new UnsupportedOperationException("Desktop package metadata supports flags=0 only");
        if (!ownPackage.equals(name)) throw new NameNotFoundException(name);
        ApplicationInfo result = new ApplicationInfo();
        result.packageName = ownPackage;
        result.nativeLibraryDir = nativeDirectory.toString();
        return result;
    }
}
