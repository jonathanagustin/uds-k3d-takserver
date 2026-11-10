// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.nasa.worldwind.util.gdal;

import java.awt.image.DataBuffer;
import java.awt.image.IndexColorModel;
import java.util.function.IntUnaryOperator;

/** Converts the pinned GDAL SWIG packed ARGB contract without loading JNI. */
public final class ProjectPaletteColorModel {
    private ProjectPaletteColorModel() { }

    public static IndexColorModel create(int bits, int count, IntUnaryOperator entry) {
        if (bits < 1 || bits > 16 || count < 1 || count > (1 << bits)) {
            throw new IllegalArgumentException("Invalid palette depth or size");
        }
        int[] argb = new int[count];
        for (int i = 0; i < count; i++) {
            argb[i] = entry.applyAsInt(i);
        }
        return new IndexColorModel(bits, count, argb, 0, true, -1,
                bits <= 8 ? DataBuffer.TYPE_BYTE : DataBuffer.TYPE_USHORT);
    }
}
