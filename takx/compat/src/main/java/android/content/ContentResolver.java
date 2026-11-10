// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.content;

import android.content.res.Resources;
import android.net.Uri;
import java.io.FileNotFoundException;
import java.io.InputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Objects;

/** Real file streams and the existing explicit raw-resource catalog only. */
public final class ContentResolver {
    private final Resources resources;
    public ContentResolver(Resources resources) { this.resources = Objects.requireNonNull(resources); }
    public InputStream openInputStream(Uri uri) throws FileNotFoundException {
        Objects.requireNonNull(uri);
        try {
            if (uri.getQuery() != null || uri.getFragment() != null)
                throw new FileNotFoundException("Stream URI query/fragment is unsupported");
            if ("file".equals(uri.getScheme())) {
                String authority = uri.getAuthority();
                if (authority != null && !authority.isEmpty() && !authority.equals("localhost"))
                    throw new FileNotFoundException("Remote file authorities are unsupported");
                Path path = Path.of(Objects.requireNonNull(uri.getPath()));
                if (!path.isAbsolute()) throw new FileNotFoundException("File URI path must be absolute");
                if (!Files.isRegularFile(path)) throw new FileNotFoundException("File URI must name a regular local file");
                return Files.newInputStream(path);
            }
            if (!"android.resource".equals(uri.getScheme()))
                throw new FileNotFoundException("No desktop provider is registered for this URI scheme");
            String owner = uri.getAuthority();
            if (owner == null || !owner.matches("[A-Za-z_][A-Za-z0-9_.]*"))
                throw new FileNotFoundException("Resource URI requires a known catalog package");
            List<String> parts = uri.getPathSegments();
            int id;
            if (parts.size() == 1 && parts.get(0).matches("[0-9]+")) id = Integer.parseInt(parts.get(0));
            else if (parts.size() == 2 && parts.get(0).equals("raw"))
                id = resources.getIdentifier(parts.get(1), "raw", owner);
            else throw new FileNotFoundException("Expected resource ID or raw/name");
            return resources.openRawResourceForPackage(owner, id);
        } catch (Resources.NotFoundException | IllegalArgumentException | NullPointerException error) {
            FileNotFoundException failure = new FileNotFoundException("URI has no readable desktop resource");
            failure.initCause(error); throw failure;
        } catch (IOException error) {
            if (error instanceof FileNotFoundException) throw (FileNotFoundException)error;
            FileNotFoundException failure = new FileNotFoundException("Cannot open desktop file");
            failure.initCause(error); throw failure;
        }
    }
}
