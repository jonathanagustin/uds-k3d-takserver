// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.Set;
import jassimp.AiBufferAllocator;
import jassimp.AiIOStream;
import jassimp.AiIOSystem;
import jassimp.AiPostProcessSteps;
import jassimp.AiScene;
import jassimp.Jassimp;
import org.gdal.gdal.ColorTable;
import org.gdal.gdal.Dataset;
import org.gdal.gdalconst.gdalconst;

/** Compile-only consumer. Never executed: these calls require matching native JNI. */
final class CompileApiProbe {
    static int raster(Dataset dataset, ColorTable colors) {
        dataset.Interrupt();
        int pending = dataset.Interrupted();
        dataset.ClearInterrupt();
        int color = colors.GetColorEntry(0);
        int canceled = gdalconst.CE_Interrupted;
        return color + pending + canceled;
    }

    static AiScene model(String path, Set<AiPostProcessSteps> steps, AiIOSystem<AiIOStream> io,
                         AiBufferAllocator allocator) throws IOException {
        Jassimp.setBufferAllocator(allocator);
        ByteBuffer buffer = Jassimp.getBufferAllocator().allocate(16);
        AiIOStream stream = io.open(path, "rb");
        if (stream != null) {
            stream.read(buffer);
            stream.seek(0, 0);
            long position = stream.tell();
            int size = stream.getFileSize();
            if (position > size) { throw new IOException("position past end"); }
            io.close(stream);
        }
        io.exists(path);
        io.getOsSeparator();
        return Jassimp.importFile(path, steps, io);
    }
}
