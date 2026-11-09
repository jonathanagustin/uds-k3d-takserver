// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.image.BufferedImage;
import java.io.FilterOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.util.Iterator;
import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.ImageWriter;
import javax.imageio.stream.ImageOutputStream;
import javax.imageio.stream.MemoryCacheImageOutputStream;

/** JDK codec backend; no native Skia codec or bitstream-equivalence claim. */
final class BitmapEncoder {
    private BitmapEncoder() {}

    static boolean write(BufferedImage image, Bitmap.CompressFormat format, int quality, OutputStream stream) {
        Iterator<ImageWriter> writers = ImageIO.getImageWritersByFormatName(format.name());
        if (!writers.hasNext()) { return false; }
        ImageWriter writer = writers.next();
        OutputStream borrowed = new FilterOutputStream(stream) {
            @Override public void close() throws IOException { flush(); }
            @Override public void write(byte[] bytes, int offset, int length) throws IOException {
                out.write(bytes, offset, length);
            }
        };
        try (ImageOutputStream output = new MemoryCacheImageOutputStream(borrowed)) {
            writer.setOutput(output);
            BufferedImage encoded = image;
            ImageWriteParam parameters = writer.getDefaultWriteParam();
            if (format == Bitmap.CompressFormat.JPEG) {
                // JPEG has no alpha channel: retain the decoded straight RGB values.
                encoded = new BufferedImage(image.getWidth(), image.getHeight(), BufferedImage.TYPE_INT_RGB);
                int[] pixels = image.getRGB(0, 0, image.getWidth(), image.getHeight(), null, 0, image.getWidth());
                encoded.setRGB(0, 0, image.getWidth(), image.getHeight(), pixels, 0, image.getWidth());
                parameters.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
                parameters.setCompressionQuality(quality / 100f);
            }
            writer.write(null, new IIOImage(encoded, null, null), parameters);
            output.flush();
            return true;
        } catch (IOException exception) {
            return false;
        } finally { writer.dispose(); }
    }
}
