// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.content.res;

import java.io.FileNotFoundException;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.net.URLClassLoader;
import java.net.JarURLConnection;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;
import java.util.jar.JarFile;

/** Real directory/JAR classpath assets, with caller-owned streams. */
public class AssetManager {
    private final ClassLoader loader;
    public AssetManager(ClassLoader loader) { this.loader = Objects.requireNonNull(loader); }
    static String safePath(String path) {
        if (path == null || path.isEmpty() || path.startsWith("/") || path.indexOf('\\') >= 0 || path.indexOf('%') >= 0 || path.matches("[A-Za-z]:.*") || path.chars().anyMatch(c -> c < 32))
            throw new IllegalArgumentException("Invalid classpath resource path");
        for (String part : path.split("/", -1))
            if (part.isEmpty() || part.equals(".") || part.equals(".."))
                throw new IllegalArgumentException("Resource traversal is not permitted");
        return path;
    }
    private List<Path> roots() throws IOException {
        Set<Path> roots = new LinkedHashSet<>();
        boolean system = false;
        for (ClassLoader current = loader; current != null; current = current.getParent()) {
            if (current == ClassLoader.getSystemClassLoader()) system = true;
            if (current instanceof URLClassLoader) for (URL url : ((URLClassLoader)current).getURLs()) {
                if (!url.getProtocol().equals("file")) throw new IOException("Only local directory/JAR asset roots are supported");
                roots.add(path(url).toAbsolutePath().normalize());
            }
        }
        if (system) for (String entry : System.getProperty("java.class.path", "").split(java.io.File.pathSeparator, -1))
            roots.add(Path.of(entry.isEmpty() ? "." : entry).toAbsolutePath().normalize());
        if (roots.isEmpty() && !(loader instanceof URLClassLoader))
            throw new IOException("ClassLoader does not expose real directory/JAR asset roots");
        return new ArrayList<>(roots);
    }
    private static Path path(URL url) throws IOException {
        try { return Path.of(url.toURI()); }
        catch (java.net.URISyntaxException | IllegalArgumentException error) { throw new IOException("Invalid asset root URL", error); }
    }
    private static Path bounded(Path root, String relative) throws IOException {
        return bounded(root, relative, true);
    }
    private static Path bounded(Path root, String relative, boolean asset) throws IOException {
        Path realRoot = root.toRealPath();
        Path base = asset ? realRoot.resolve("assets") : realRoot;
        Path target = base.resolve(relative);
        // Resolve every existing ancestor, including dangling/malicious symlinks.
        Path current = base;
        if (Files.exists(current, LinkOption.NOFOLLOW_LINKS) && !current.toRealPath().startsWith(realRoot))
            throw new IOException("Asset root symlink escapes classpath root");
        for (Path component : Path.of(relative)) {
            current = current.resolve(component);
            if (Files.exists(current, LinkOption.NOFOLLOW_LINKS) && !current.toRealPath().startsWith(base.toRealPath()))
                throw new IOException("Asset symlink escapes asset root");
        }
        return target;
    }
    public InputStream open(String name) throws IOException {
        return openResource("assets/" + safePath(name), true);
    }
    InputStream openResource(String name) throws IOException {
        return openResource(safePath(name), false);
    }
    private InputStream openResource(String resource, boolean asset) throws IOException {
        URL url = loader.getResource(resource);
        if (url == null) throw new FileNotFoundException("Asset/resource not found: " + resource);
        List<Path> roots = roots();
        if (url.getProtocol().equals("file")) {
            Path selected = path(url).toAbsolutePath().normalize();
            for (Path root : roots) if (Files.isDirectory(root) && selected.equals(root.resolve(resource)))
                return Files.newInputStream(bounded(root, asset ? resource.substring(7) : resource, asset));
        } else if (url.getProtocol().equals("jar")) {
            JarURLConnection connection = (JarURLConnection)url.openConnection();
            connection.setUseCaches(false);
            Path selected = path(connection.getJarFileURL()).toAbsolutePath().normalize();
            if (!roots.contains(selected) || !resource.equals(connection.getEntryName()))
                throw new IOException("Asset JAR is outside declared classpath roots");
            final JarFile jar = new JarFile(selected.toFile());
            try {
                var entry = jar.getJarEntry(resource);
                if (entry == null || entry.isDirectory()) throw new FileNotFoundException("Asset entry is absent or a directory");
                return new FilterInputStream(jar.getInputStream(entry)) {
                    @Override public void close() throws IOException {
                        try { super.close(); } finally { jar.close(); }
                    }
                };
            } catch (IOException | RuntimeException error) { jar.close(); throw error; }
        }
        throw new IOException("Asset URL has no bounded local directory/JAR backend");
    }
    public String[] list(String directory) throws IOException {
        String relative = directory.isEmpty() ? "" : safePath(directory);
        Set<String> names = new TreeSet<>();
        for (Path root : roots()) {
            if (Files.isDirectory(root)) {
                Path target = bounded(root, relative);
                if (Files.isDirectory(target)) try (var children = Files.list(target)) {
                    for (Path child : (Iterable<Path>)children::iterator) {
                        bounded(root, (relative.isEmpty() ? "" : relative + "/") + child.getFileName());
                        names.add(child.getFileName().toString());
                    }
                }
            } else if (Files.isRegularFile(root)) {
                try (JarFile jar = new JarFile(root.toFile())) {
                    String prefix = "assets/" + (relative.isEmpty() ? "" : relative + "/");
                    for (var entries = jar.entries(); entries.hasMoreElements();) {
                        String name = entries.nextElement().getName();
                        if (!name.startsWith(prefix) || name.equals(prefix)) continue;
                        String rest = name.substring(prefix.length());
                        String normalized = rest.endsWith("/") ? rest.substring(0, rest.length()-1) : rest;
                        safePath(normalized); // Do not expose traversal entries from a malformed JAR.
                        int slash = rest.indexOf('/');
                        names.add(slash < 0 ? rest : rest.substring(0, slash));
                    }
                }
            }
        }
        return names.toArray(new String[0]);
    }
}
