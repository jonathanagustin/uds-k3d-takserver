// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.project.contour;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.CancellationException;
import java.util.function.BooleanSupplier;
import java.util.function.IntConsumer;

/** Rectangle clipping of project WGS84 polylines; no polygon fill or map renderer. */
public final class ContourClip {
    private ContourClip() { }
    public static List<ContourGrid.Line> clip(List<ContourGrid.Line> source,
            double west, double south, double east, double north,
            BooleanSupplier cancelled, IntConsumer progress) {
        Objects.requireNonNull(source,"source");
        if (!Double.isFinite(west) || !Double.isFinite(east) || !Double.isFinite(south) || !Double.isFinite(north) ||
                west < -180 || east > 180 || south < -90 || north > 90 || west >= east || south >= north || source.size() > 4096)
            throw new IllegalArgumentException("bounded non-wrapping WGS84 clipping rectangle required");
        List<ContourGrid.Line> snapshot = List.copyOf(source);
        long input = 0;
        for (var line : snapshot) {
            check(cancelled);
            if (!Double.isFinite(line.elevationMeters()) || line.points().size() < 2 || (input += line.points().size()) > 1_000_000)
                throw new IllegalArgumentException("bounded finite contour lines required");
            for (var point : line.points()) {
                check(cancelled);
                if (!Double.isFinite(point.longitude()) || !Double.isFinite(point.latitude()) || point.longitude() < -180 ||
                        point.longitude() > 180 || point.latitude() < -90 || point.latitude() > 90)
                    throw new IllegalArgumentException("finite WGS84 vertices required");
            }
        }
        report(progress,0);
        List<ContourGrid.Line> result = new ArrayList<>();
        int output = 0, completed = 0;
        for (var line : snapshot) {
            List<ContourGrid.Line> paths = new ArrayList<>();
            List<ContourGrid.Point> path = new ArrayList<>();
            for (int i = 1; i < line.points().size(); i++) {
                check(cancelled);
                var a = line.points().get(i - 1);var b = line.points().get(i);
                if (a.equals(b)) continue;
                double[] range = segment(a,b,west,south,east,north);
                if (range == null) { flush(path,paths,line.elevationMeters());continue; }
                var first = point(a,b,range[0],west,south,east,north);
                var last = point(a,b,range[1],west,south,east,north);
                if (first.equals(last)) continue; // A point-only touch is not a line.
                if (!path.isEmpty() && !path.get(path.size()-1).equals(first)) flush(path,paths,line.elevationMeters());
                if (path.isEmpty()) { path.add(first);output++; }
                path.add(last);
                if (++output > 1_000_000) throw new IllegalArgumentException("clipped output vertex bound exceeded");
                if (range[1] < 1) flush(path,paths,line.elevationMeters());
            }
            flush(path,paths,line.elevationMeters());
            // A closed input may start inside the rectangle; join its cyclic first/last pieces.
            if (line.points().get(0).equals(line.points().get(line.points().size()-1)) && paths.size() > 1) {
                var first = paths.get(0);var last = paths.get(paths.size()-1);
                if (last.points().get(last.points().size()-1).equals(first.points().get(0))) {
                    List<ContourGrid.Point> joined = new ArrayList<>(last.points());
                    joined.addAll(first.points().subList(1,first.points().size()));
                    paths.set(0,new ContourGrid.Line(line.elevationMeters(),joined));paths.remove(paths.size()-1);
                }
            }
            result.addAll(paths);
            report(progress,++completed * 100 / snapshot.size());
        }
        if (snapshot.isEmpty()) report(progress,100);
        check(cancelled);
        return List.copyOf(result);
    }
    private static double[] segment(ContourGrid.Point a, ContourGrid.Point b,
            double west,double south,double east,double north) {
        double dx=b.longitude()-a.longitude(),dy=b.latitude()-a.latitude(),low=0,high=1;
        double[] p={-dx,dx,-dy,dy};
        double[] q={a.longitude()-west,east-a.longitude(),a.latitude()-south,north-a.latitude()};
        for(int i=0;i<4;i++) {
            if(p[i]==0) { if(q[i]<0)return null;continue; }
            double t=q[i]/p[i];
            if(p[i]<0)low=Math.max(low,t);else high=Math.min(high,t);
            if(low>high)return null;
        }
        return new double[]{low,high};
    }
    private static ContourGrid.Point point(ContourGrid.Point a,ContourGrid.Point b,double t,
            double west,double south,double east,double north) {
        var value=t==0?a:t==1?b:new ContourGrid.Point(a.longitude()+t*(b.longitude()-a.longitude()),
                a.latitude()+t*(b.latitude()-a.latitude()));
        double x=Math.max(west,Math.min(east,value.longitude())),y=Math.max(south,Math.min(north,value.latitude()));
        return x==value.longitude()&&y==value.latitude()?value:new ContourGrid.Point(x,y);
    }
    private static void flush(List<ContourGrid.Point> path,List<ContourGrid.Line> paths,double elevation) {
        if(path.size()>=2)paths.add(new ContourGrid.Line(elevation,path));
        path.clear();
    }
    private static void check(BooleanSupplier cancelled) {
        if(Thread.currentThread().isInterrupted() || cancelled!=null&&cancelled.getAsBoolean())
            throw new CancellationException("contour clipping cancelled");
    }
    private static void report(IntConsumer progress,int percent) { if(progress!=null)progress.accept(percent); }
}
