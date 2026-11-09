// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package geometry;

import android.graphics.Point;
import android.graphics.PointF;
import android.graphics.RectF;
import com.atakmap.math.PointD;
import com.atakmap.coremap.maps.coords.Vector2D;
import com.atakmap.map.layer.raster.tilematrix.TileMatrix;
import java.nio.FloatBuffer;
import java.util.List;

public final class GeometryCompatibilityTest {
    private static int checks;
    private static void check(boolean result) {
        checks++;
        if (!result) throw new AssertionError("geometry check " + checks);
    }
    private static void rect(RectF r, float l, float t, float right, float b) {
        check(r.left == l && r.top == t && r.right == right && r.bottom == b);
    }
    public static void main(String[] args) {
        Point p = new Point(-7, 3);
        Point copy = new Point(p);
        p.offset(2, -5);
        check(copy.equals(-7, 3)); check(p.equals(-5, -2));
        p.negate(); check(p.equals(5, 2)); p.set(copy); check(p.equals(copy));
        check(p.hashCode() == copy.hashCode()); check(!p.equals(null));
        check(new Point().equals(0, 0));
        PointF f = new PointF(p);
        f.offset(.5f, -.25f); check(f.equals(-6.5f, 2.75f));
        PointF fc = new PointF(f); f.negate(); check(fc.equals(-6.5f, 2.75f));
        f.set(3, 4); check(f.length() == 5); check(PointF.length(0, -5) == 5);
        f.set(fc); check(f.equals(fc)); check(f.hashCode() == fc.hashCode());
        check(new PointF(-0f, 0f).equals(new PointF(0f, -0f)));
        check(new PointF(-0f, 0f).hashCode() == new PointF(0f, -0f).hashCode());
        PointD d = new PointD(fc); check(d.x == -6.5 && d.y == 2.75 && d.z == 0);
        check(d.toPoint().equals(-6, 2)); check(d.toPointF().equals(fc));
        check(new PointD(copy).toPoint().equals(copy));

        RectF r = new RectF(-2, -3, 8, 7);
        check(r.width() == 10 && r.height() == 10 && r.centerX() == 3 && r.centerY() == 2);
        check(r.contains(-2, -3)); check(!r.contains(8, 0)); check(!r.contains(0, 7));
        check(new RectF((RectF) null).isEmpty());
        RectF rc = new RectF(r); r.offset(2, 3); rect(r, 0, 0, 10, 10); rect(rc, -2, -3, 8, 7);
        r.offsetTo(-5, -4); rect(r, -5, -4, 5, 6);
        r.inset(1, 2); rect(r, -4, -2, 4, 4);
        r.inset(1, 2, 3, 4); rect(r, -3, 0, 1, 0); check(r.isEmpty());
        r.set(new RectF(0, 0, 10, 10)); check(!r.intersect(10, 0, 20, 10)); rect(r, 0, 0, 10, 10);
        check(r.intersect(5, -1, 12, 4)); rect(r, 5, 0, 10, 4);
        check(r.contains(new RectF(6, 1, 9, 3))); check(!r.contains(0, 0, 11, 3));
        check(RectF.intersects(r, new RectF(9, 3, 12, 8)));
        check(!RectF.intersects(r, new RectF(10, 0, 12, 4)));
        check(!r.setIntersect(new RectF(0, 0, 1, 1), new RectF(2, 2, 3, 3))); rect(r, 5, 0, 10, 4);
        check(r.setIntersect(new RectF(0, 0, 3, 3), new RectF(1, 1, 4, 4))); rect(r, 1, 1, 3, 3);
        r.union(-2, -3, 0, 0); rect(r, -2, -3, 3, 3);
        r.union(20, 20, 10, 10); rect(r, -2, -3, 3, 3);
        r.union(4, 5); rect(r, -2, -3, 4, 5);
        r.set(9, 8, -1, -2); check(r.isEmpty()); check(r.width() == -10);
        r.sort(); rect(r, -1, -2, 9, 8); r.setEmpty(); check(r.isEmpty());
        r.union(new RectF(1, 2, 3, 4)); rect(r, 1, 2, 3, 4);
        check(new RectF(-0f, 0f, 1, 1).equals(new RectF(0f, -0f, 1, 1)));
        check(new RectF(-0f, 0f, 1, 1).hashCode() == new RectF(0f, -0f, 1, 1).hashCode());

        TileMatrix.ZoomLevel zoom = new TileMatrix.ZoomLevel.Builder().setTileSize(256).setPixelSize(2).build();
        check(TileMatrix.Util.getTileIndex(100, 1000, zoom, 612, 488).equals(1, 1));
        check(TileMatrix.Util.getTileIndex(100, 1000, zoom, -412, 1512).equals(-1, -1));
        // Upstream truncates rather than floors negative fractional tile indices.
        check(TileMatrix.Util.getTileIndex(100, 1000, zoom, 99, 1001).equals(0, 0));
        PointD pixel = TileMatrix.Util.getTilePoint(100, 1000, zoom, 1, 1, 0, 0);
        check(pixel.x == 612 && pixel.y == 488);
        // Actual consumer uses lower-left coordinates, independently of RectF.contains.
        RectF clip = new RectF(0, 10, 10, 0);
        FloatBuffer crossing = FloatBuffer.wrap(new float[] {-5, 5, 15, 5});
        List<List<Vector2D>> lines = Vector2D.clipPolylineCohenSutherland(clip, crossing);
        check(lines.size() == 1 && lines.get(0).size() == 2);
        check(lines.get(0).get(0).x == 0 && lines.get(0).get(1).x == 10);
        check(crossing.position() == 0);
        check(Vector2D.clipPolylineCohenSutherland(clip, FloatBuffer.wrap(new float[] {-5, -2, -1, -2})).isEmpty());
        lines = Vector2D.clipPolylineCohenSutherland(clip, FloatBuffer.wrap(new float[] {1, 2, 3, 4}));
        check(lines.size() == 1 && lines.get(0).get(0).x == 1 && lines.get(0).get(1).y == 4);
        System.out.println("Geometry compatibility: " + checks + " checks passed");
    }
}
