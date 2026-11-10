// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.AlphaComposite;
import java.awt.BasicStroke;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.Shape;
import java.awt.font.TextLayout;
import java.awt.geom.AffineTransform;
import java.awt.geom.Area;
import java.awt.geom.Rectangle2D;
import java.awt.image.BufferedImage;
import java.util.Objects;

/** Bounded software raster drawing surface; no Android native rendering contract. */
public final class Canvas {
    private final Bitmap target;

    public Canvas(Bitmap bitmap) {
        target = Objects.requireNonNull(bitmap, "bitmap");
        target.getDrawingImage();
    }

    private Graphics2D graphics(Paint paint, boolean bitmap) {
        Graphics2D g = target.getDrawingImage().createGraphics();
        g.setComposite(AlphaComposite.getInstance(AlphaComposite.SRC_OVER,
                bitmap && paint != null ? paint.getAlpha() / 255f : 1f));
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_NEAREST_NEIGHBOR);
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,
                paint != null && paint.isAntiAlias() ? RenderingHints.VALUE_ANTIALIAS_ON : RenderingHints.VALUE_ANTIALIAS_OFF);
        g.setRenderingHint(RenderingHints.KEY_FRACTIONALMETRICS, RenderingHints.VALUE_FRACTIONALMETRICS_ON);
        if (paint != null) {
            g.setColor(new java.awt.Color(paint.getColor(), true));
            g.setStroke(new BasicStroke(paint.getStrokeWidth() == 0f ? 1f : paint.getStrokeWidth(),
                    BasicStroke.CAP_BUTT, BasicStroke.JOIN_MITER, 4f));
        }
        return g;
    }

    public void drawColor(int color) {
        Graphics2D g = graphics(null, false);
        try {
            g.setColor(new java.awt.Color(color, true));
            g.fillRect(0, 0, target.getWidth(), target.getHeight());
        } finally { g.dispose(); }
    }

    public void drawBitmap(Bitmap bitmap, float left, float top, Paint paint) {
        Objects.requireNonNull(bitmap, "bitmap");
        finite(left, top);
        drawBitmap(bitmap, null, new RectF(left, top, left + bitmap.getWidth(), top + bitmap.getHeight()), paint);
    }

    public void drawBitmap(Bitmap bitmap, Rect source, Rect destination, Paint paint) {
        Objects.requireNonNull(destination, "destination");
        drawBitmap(bitmap, source, new RectF(destination.left, destination.top, destination.right, destination.bottom), paint);
    }

    public void drawBitmap(Bitmap bitmap, Rect source, RectF destination, Paint paint) {
        BufferedImage image = Objects.requireNonNull(bitmap, "bitmap").getAwtBufferedImageImplementation();
        if (bitmap.getConfig() == Bitmap.Config.ALPHA_8 && paint != null && (paint.getColor() & 0x00ffffff) != 0) {
            throw new UnsupportedOperationException("ALPHA_8 source paint tint is outside this drawing slice");
        }
        Objects.requireNonNull(destination, "destination");
        finite(destination.left, destination.top, destination.right, destination.bottom);
        Rect src = source == null ? new Rect(0, 0, image.getWidth(), image.getHeight()) : source;
        if (src.left < 0 || src.top < 0 || src.right > image.getWidth() || src.bottom > image.getHeight()) {
            throw new IllegalArgumentException("source rectangle must be inside the bitmap");
        }
        Graphics2D g = graphics(paint, true);
        try {
            if (src.isEmpty() || destination.isEmpty()) { return; }
            g.clip(new Rectangle2D.Float(destination.left, destination.top, destination.width(), destination.height()));
            AffineTransform transform = new AffineTransform();
            transform.translate(destination.left, destination.top);
            transform.scale(destination.width() / src.width(), destination.height() / src.height());
            transform.translate(-src.left, -src.top);
            g.drawImage(image, transform, null);
        } finally { g.dispose(); }
    }

    public void drawRect(Rect rect, Paint paint) {
        Objects.requireNonNull(rect, "rect");
        drawRect(rect.left, rect.top, rect.right, rect.bottom, paint);
    }

    public void drawRect(float left, float top, float right, float bottom, Paint paint) {
        Objects.requireNonNull(paint, "paint");
        finite(left, top, right, bottom);
        Graphics2D g = graphics(paint, false);
        try {
            if (left >= right || top >= bottom) { return; }
            draw(g, new Rectangle2D.Float(left, top, right - left, bottom - top), paint);
        } finally { g.dispose(); }
    }

    public void drawText(String text, float x, float y, Paint paint) {
        Objects.requireNonNull(text, "text");
        drawText(text, 0, text.length(), x, y, paint);
    }

    public void drawText(String text, int start, int end, float x, float y, Paint paint) {
        Objects.requireNonNull(text, "text");
        Objects.requireNonNull(paint, "paint");
        if (start < 0 || end < start || end > text.length()) { throw new IndexOutOfBoundsException("text range"); }
        finite(x, y);
        Graphics2D g = graphics(paint, false);
        try {
            if (start == end || paint.getTextSize() == 0f) { return; }
            TextLayout layout = new TextLayout(text.substring(start, end), paint.awtFont(), paint.fontContext());
            float offset = paint.getTextAlign() == Paint.Align.CENTER ? layout.getAdvance() / 2f
                    : paint.getTextAlign() == Paint.Align.RIGHT ? layout.getAdvance() : 0f;
            draw(g, layout.getOutline(AffineTransform.getTranslateInstance(x - offset, y)), paint);
        } finally { g.dispose(); }
    }

    private static void draw(Graphics2D g, Shape shape, Paint paint) {
        if (paint.getStyle() == Paint.Style.FILL_AND_STROKE) {
            Area covered = new Area(shape);
            covered.add(new Area(g.getStroke().createStrokedShape(shape)));
            g.fill(covered);
        } else if (paint.getStyle() == Paint.Style.FILL) {
            g.fill(shape);
        } else {
            g.draw(shape);
        }
    }

    private static void finite(float... values) {
        for (float value : values) {
            if (!Float.isFinite(value)) { throw new IllegalArgumentException("non-finite drawing coordinate"); }
        }
    }
}
