// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.platform.client.dted;

import com.atakmap.coremap.maps.coords.GeoBounds;
import gov.tak.api.commons.resources.IResourceManager;
import java.io.ByteArrayInputStream;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.BitSet;

/** Offline controls for the real patched downloader. No scanCurrentAreas/network call. */
public final class ElevationDownloadControls {
    private static int assertions;
    private static void check(boolean value) {
        if (!value) throw new AssertionError("elevation contract assertion " + assertions);
        assertions++;
    }
    private static void rejects(Runnable action, Class<? extends Throwable> expected) {
        try { action.run(); } catch (Throwable failure) {
            check(expected.isInstance(failure)); return;
        }
        throw new AssertionError("missing rejection");
    }
    private static IResourceManager resource(BitSet coverage) {
        byte[] bytes = new byte[8098];
        if (coverage != null) {
            coverage.set(64783); // Last represented remote cell preserves upstream BitSet storage size.
            byte[] bits = coverage.toByteArray();
            System.arraycopy(bits, 0, bytes, 0, bits.length);
        }
        return (IResourceManager) Proxy.newProxyInstance(IResourceManager.class.getClassLoader(),
                new Class<?>[]{IResourceManager.class}, (proxy, method, args) -> {
                    if (method.getName().equals("openRawResource")) {
                        if (coverage == null) throw new java.io.IOException("owned missing resource fixture");
                        return new ByteArrayInputStream(bytes);
                    }
                    throw new UnsupportedOperationException("unexpected resource operation");
                });
    }
    private static int[] bounds(GeoBounds b) throws Exception {
        Method m = ElevationDownloader.class.getDeclaredMethod("getDownloadBounds", GeoBounds.class);
        m.setAccessible(true); return (int[]) m.invoke(null, b);
    }
    private static final class BorrowedWatcher extends Dt2FileWatcher {
        private Listener added;
        private int scans;
        BorrowedWatcher(Path root) { super(java.util.Collections.singletonList(root.toFile())); }
        @Override public synchronized void addListener(Listener listener) {
            check(added == null); added = listener; super.addListener(listener);
        }
        @Override public synchronized void removeListener(Listener listener) {
            check(added == listener); added = null; super.removeListener(listener);
        }
        @Override public void scan() { scans++; super.scan(); }
        @Override public void start() { throw new AssertionError("borrowed watcher started"); }
        @Override public void dispose() { throw new AssertionError("borrowed watcher disposed"); }
    }
    private static final class Borrower extends ElevationDownloader {
        Borrower(IResourceManager resource, BorrowedWatcher watcher) { super(resource, watcher); }
    }
    public static void main(String[] args) throws Exception {
        Path root = Path.of(args[0]);
        check(!Files.exists(root)); Files.createDirectory(root);
        check(ElevationDownloader.withinTileBudget(10, 10, 100));
        check(!ElevationDownloader.withinTileBudget(10, 11, 100));
        check(ElevationDownloader.withinTileBudget(10, 11, 110));
        check(!ElevationDownloader.withinTileBudget(Integer.MAX_VALUE, 2, Integer.MAX_VALUE));
        check(!ElevationDownloader.withinTileBudget(0, 1, 100));
        check(!ElevationDownloader.withinTileBudget(1, 1, 0));
        check(Arrays.equals(bounds(new GeoBounds(0, 0, 1, 1)), new int[]{0, 0, 1, 1}));
        GeoBounds dateline = new GeoBounds(-1, -179, 1, 179); dateline.setWrap180(true);
        check(Arrays.equals(bounds(dateline), new int[]{179, -1, 181, 1}));
        check(Arrays.equals(bounds(new GeoBounds(89, 0, 90, 0)), new int[]{0, 89, 0, 89}));
        check(bounds(new GeoBounds(90, 0, 90, 0)) == null);
        check(bounds(new GeoBounds(Double.NaN, 0, 1, 1)) == null);
        check(bounds(new GeoBounds(0, Double.POSITIVE_INFINITY, 1, 1)) == null);
        check(bounds(new GeoBounds(-91, 0, 1, 1)) == null);
        int zero = Dt2FileWatcher.getCoverageIndex(0, 0);
        BitSet remote = new BitSet(); remote.set(zero);
        ElevationDownloader downloader = new ElevationDownloader(resource(remote), root.toFile());
        try {
            check(downloader.getMaxTileRequests() == 100);
            downloader.setMaxTileRequests(Integer.MAX_VALUE);
            check(downloader.getMaxTileRequests() == Integer.MAX_VALUE);
            rejects(() -> downloader.setMaxTileRequests(0), IllegalArgumentException.class);
            rejects(() -> downloader.setMaxTileRequests(-1), IllegalArgumentException.class);
            GeoBounds tile = new GeoBounds(0, 0, 0, 0);
            check(downloader.getMissingTileCount(new GeoBounds[]{tile, tile}) == 1);
            BitSet detachedRemote = downloader.getRemoteCoverageSnapshot(); detachedRemote.clear();
            check(downloader.getRemoteCoverageSnapshot().get(zero));
            BitSet detachedLocal = downloader.getLocalCoverageSnapshot(); detachedLocal.set(zero);
            check(!downloader.getLocalCoverageSnapshot().get(zero));
            Path cell = root.resolve(Dt2FileWatcher.getRelativePath(0, 0, 0));
            Files.createDirectories(cell.getParent()); Files.createFile(cell);
            check(downloader.getMissingTileCount(new GeoBounds[]{tile}) == 0);
            Files.delete(cell);
            check(downloader.getMissingTileCount(new GeoBounds[]{tile}) == 1);
            rejects(() -> downloader.getMissingTileCount(null), IllegalArgumentException.class);
            rejects(() -> downloader.getMissingTileCount(new GeoBounds[]{null}), IllegalArgumentException.class);
            rejects(() -> downloader.getMissingTileCount(new GeoBounds[]{new GeoBounds(Double.NaN, 0, 1, 1)}), IllegalArgumentException.class);
        } finally { downloader.dispose(); }
        ElevationDownloader unavailable = new ElevationDownloader(resource(null), root.toFile());
        try {
            rejects(unavailable::getRemoteCoverageSnapshot, IllegalStateException.class);
            rejects(() -> unavailable.getMissingTileCount(new GeoBounds[0]), IllegalStateException.class);
        } finally { unavailable.dispose(); }
        BorrowedWatcher borrowedWatcher = new BorrowedWatcher(root);
        Borrower borrower = new Borrower(resource(remote), borrowedWatcher);
        check(borrowedWatcher.scans == 0);
        borrower.getLocalCoverageSnapshot();
        check(borrowedWatcher.scans == 1);
        borrower.dispose();
        check(borrowedWatcher.added == null);
        System.out.println("PASS_REAL_ELEVATION_DOWNLOAD_CONTROLS assertions=" + assertions);
    }
}
