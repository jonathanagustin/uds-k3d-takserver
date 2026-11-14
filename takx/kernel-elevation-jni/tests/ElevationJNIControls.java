// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.map.elevation.*;
import com.atakmap.map.layer.feature.geometry.*;
import com.atakmap.coremap.maps.coords.GeoPoint;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;

public final class ElevationJNIControls {
    static int checks;
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    public static void main(String[] args)throws Exception {
        for(String line:Files.readAllLines(Path.of(args[0])))System.load(line.split(" ",2)[1]);
        Polygon bounds=new Polygon(2);LineString ring=new LineString(2);
        ring.addPoint(-1,-1);ring.addPoint(1,-1);ring.addPoint(1,1);ring.addPoint(-1,1);ring.addPoint(-1,-1);bounds.addRing(ring);
        AtomicInteger calls=new AtomicInteger();
        ElevationChunk.Factory.Sampler sampler=new ElevationChunk.Factory.Sampler(){
            public double sample(double lat,double lon){calls.incrementAndGet();return 100*lon+50*lat;}
            public void dispose(){}
        };
        ElevationChunk chunk=ElevationChunk.Factory.create("owned-contour-plane","memory://owned-contour-plane",ElevationData.MODEL_TERRAIN,1,bounds,0,0,true,sampler);
        ElevationSource source=ElevationSourceBuilder.build("owned-contour-plane",List.of(chunk));
        ElevationSource.QueryParameters query=new ElevationSource.QueryParameters();query.types=Set.of("owned-contour-plane");query.spatialFilter=bounds;query.flags=ElevationData.MODEL_TERRAIN;
        List<GeoPoint> points=new ArrayList<>();
        for(int y=0;y<9;y++)for(int x=0;x<9;x++)points.add(new GeoPoint(-.8+y*.2,-.8+x*.2));
        double[] elevations=new double[points.size()];Arrays.fill(elevations,Double.NaN);
        ElevationSourceManager.attach(source);
        try{
            check(ElevationSourceManager.findSource("owned-contour-plane")!=null,"attached source absent");
            check(ElevationManager.getElevation(points.iterator(),elevations,query),"bulk plane sampling incomplete");
            check(calls.get()>0,"real sampler callback unused");
            for(int i=0;i<points.size();i++){GeoPoint p=points.get(i);check(Math.abs(elevations[i]-(100*p.getLongitude()+50*p.getLatitude()))<1e-10,"analytic plane sample differs");}
        }finally{ElevationSourceManager.detach(source);}
        Arrays.fill(elevations,Double.NaN);
        check(!ElevationManager.getElevation(points.iterator(),elevations,query),"detached source still resolves");
        for(double value:elevations)check(Double.isNaN(value),"detached data leaked");
        chunk.dispose();bounds.dispose();ring.dispose();
        System.out.println("ELEVATION_JNI_CONTROLS_PASS checks="+checks);
    }
}
