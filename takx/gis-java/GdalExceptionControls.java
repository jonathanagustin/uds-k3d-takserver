// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import java.util.Enumeration;
import java.util.Vector;
import org.gdal.gdal.Dataset;
import org.gdal.gdal.Driver;
import org.gdal.gdal.ProgressCallback;
import org.gdal.gdal.gdal;

/** Invoke only after the independently qualified genuine SDK loader initializes. */
public final class GdalExceptionControls {
    private interface Operation { void run(); }
    private static void sameThrowable(Throwable token, Operation operation) {
        try { operation.run(); }
        catch (Throwable actual) {
            if (actual == token) return;
            throw new AssertionError("original Java callback Throwable was replaced", actual);
        }
        throw new AssertionError("callback Throwable was swallowed");
    }
    public static void run() {
        Driver memory = gdal.GetDriverByName("MEM"), tiff = gdal.GetDriverByName("GTiff");
        if (memory == null || tiff == null) throw new AssertionError("actual GDAL drivers required");
        Dataset source = memory.Create("", 8, 8, 1);
        if (source == null) throw new AssertionError("genuine GDAL source dataset required");
        String path = "/vsimem/uds-gdal-exception-controls.tif";
        try {
            for (int stage = 0; stage < 3; stage++) {
                final int selected = stage;
                final AssertionError token = new AssertionError("owned enumeration token " + stage);
                Vector<String> options = new Vector<String>() {
                    @Override public synchronized Enumeration<String> elements() {
                        if (selected == 0) throw token;
                        return new Enumeration<String>() {
                            @Override public boolean hasMoreElements() {
                                if (selected == 1) throw token;
                                return true;
                            }
                            @Override public String nextElement() { throw token; }
                        };
                    }
                };
                sameThrowable(token, () -> {
                    Dataset unexpected = tiff.CreateCopy(path, source, 0, options);
                    if (unexpected != null) unexpected.delete();
                });
                gdal.Unlink(path);
            }
            Vector<String> nullEnumeration = new Vector<String>() {
                @Override public synchronized Enumeration<String> elements() { return null; }
            };
            boolean nullRejected = false;
            try {
                Dataset unexpected = tiff.CreateCopy(path, source, 0, nullEnumeration);
                if (unexpected != null) unexpected.delete();
            } catch (NullPointerException expected) {
                if (!"Vector.elements() returned null".equals(expected.getMessage()))
                    throw new AssertionError("null Enumeration rejected by an unexpected failure", expected);
                nullRejected = true;
            }
            if (!nullRejected) throw new AssertionError("null Enumeration was not rejected");
            gdal.Unlink(path);
            AssertionError progressToken = new AssertionError("owned progress token");
            ProgressCallback callback = new ProgressCallback() {
                @Override public int run(double progress, String message) { throw progressToken; }
            };
            try {
                for (boolean useExceptions : new boolean[]{false, true}) {
                    if (useExceptions) gdal.UseExceptions();
                    else gdal.DontUseExceptions();
                    gdal.ErrorReset();
                    sameThrowable(progressToken, () -> {
                        Dataset unexpected = tiff.CreateCopy(path, source, 0, new Vector<String>(), callback);
                        if (unexpected != null) unexpected.delete();
                    });
                    gdal.Unlink(path);
                }
            } finally { callback.delete(); gdal.DontUseExceptions(); }
            System.out.println("PASS_REAL_GDAL_ENUMERATION_PROGRESS_ORIGINAL_THROWABLE_CONTROLS");
        } finally { source.delete(); gdal.Unlink(path); }
    }
}
