// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.system;

import java.io.IOException;
import java.nio.file.AccessDeniedException;
import java.nio.file.FileSystemLoopException;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.NotDirectoryException;
import java.nio.file.Paths;
import java.util.Map;
import java.util.Objects;

/** Real NIO Unix metadata, following symlinks as stat(2) does. */
public final class Os {
    private Os() {}

    public static StructStat stat(String path) throws ErrnoException {
        Objects.requireNonNull(path, "path");
        // Paths.get("") denotes the Java working directory; POSIX stat("")
        // instead fails with ENOENT. Keep the native call's path semantics.
        if (path.isEmpty()) { throw new ErrnoException("stat", 2, null); }
        try {
            Map<String, Object> values = Files.readAttributes(Paths.get(path), "unix:dev,ino,rdev,uid,gid");
            return new StructStat(number(values, "dev").longValue(), number(values, "ino").longValue(),
                    number(values, "rdev").longValue(), number(values, "uid").intValue(),
                    number(values, "gid").intValue());
        } catch (NoSuchFileException error) {
            throw new ErrnoException("stat", 2, error);
        } catch (AccessDeniedException error) {
            throw new ErrnoException("stat", 13, error);
        } catch (NotDirectoryException error) {
            throw new ErrnoException("stat", 20, error);
        } catch (FileSystemLoopException error) {
            throw new ErrnoException("stat", 40, error);
        } catch (IOException error) {
            throw new UnsupportedOperationException("unclassified Unix stat failure", error);
        }
    }

    private static Number number(Map<String, Object> values, String name) {
        Object value = values.get(name);
        if (!(value instanceof Number)) {
            throw new UnsupportedOperationException("Unix stat field unavailable: " + name);
        }
        return (Number) value;
    }
}
