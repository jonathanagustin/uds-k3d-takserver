// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.map.elevation.*;
import com.atakmap.map.layer.feature.geometry.*;
import gov.tak.project.contour.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.CancellationException;
import java.util.concurrent.atomic.*;
import java.util.function.*;

public final class ElevationContourControls {
    static int checks;
    static void check(boolean value,String why){if(!value)throw new AssertionError(why);checks++;}
    static void rejects(Runnable work,Class<? extends Throwable> type){
        try{work.run();}catch(Throwable error){check(type.isInstance(error),"wrong failure: "+error);return;}
        throw new AssertionError("expected failure: "+type.getName());
    }
    static ElevationContours.Result generate(String type,BooleanSupplier cancel,IntConsumer progress){
        return ElevationContours.generate(type,ElevationData.MODEL_TERRAIN,9,9,-.8,-.8,.8,.8,25,0,cancel,progress);
    }
    public static void main(String[] args)throws Exception {
        for(String line:Files.readAllLines(Path.of(args[0])))System.load(line.split(" ",2)[1]);
        Polygon bounds=new Polygon(2);LineString ring=new LineString(2);
        ring.addPoint(-1,-1);ring.addPoint(1,-1);ring.addPoint(1,1);ring.addPoint(-1,1);ring.addPoint(-1,-1);bounds.addRing(ring);
        AtomicInteger calls=new AtomicInteger();AtomicBoolean fault=new AtomicBoolean(),hole=new AtomicBoolean();
        RuntimeException primary=new RuntimeException("owned elevation contour fault");
        ElevationChunk chunk=ElevationChunk.Factory.create("owned-contour-provider","memory://owned-contour-provider",ElevationData.MODEL_TERRAIN,1,bounds,0,0,true,new ElevationChunk.Factory.Sampler(){
            public double sample(double lat,double lon){calls.incrementAndGet();if(fault.get())throw primary;return hole.get()&&lon>0?Double.NaN:100*lon+50*lat;}
            public void dispose(){}
        });
        ElevationSource source=ElevationSourceBuilder.build("owned-contour-provider",List.of(chunk));
        ElevationSourceManager.attach(source);
        try{
            List<Integer> progress=new ArrayList<>();var result=generate("owned-contour-provider",null,progress::add);
            check(result.fullySampled()&&result.sampledPoints()==81&&result.totalPoints()==81,"real grid sampling incomplete");
            check(calls.get()>0&&!result.lines().isEmpty(),"provider or contour algorithm unused");
            for(var line:result.lines())for(var point:line.points()){
                check(Math.abs(100*point.longitude()+50*point.latitude()-line.elevationMeters())<1e-8,"contour vertex not on analytic plane");
                check(point.longitude()>=-.8&&point.longitude()<=.8&&point.latitude()>=-.8&&point.latitude()<=.8,"contour vertex outside grid");
            }
            check(progress.get(0)==0&&progress.get(progress.size()-1)==100,"progress endpoints differ");
            for(int i=1;i<progress.size();i++)check(progress.get(i)>=progress.get(i-1),"progress regressed");
            rejects(()->result.lines().clear(),UnsupportedOperationException.class);
            int before=calls.get();var missing=generate("not-the-owned-source",null,null);
            check(!missing.fullySampled()&&missing.sampledPoints()==0&&missing.lines().isEmpty(),"source type filter ignored");
            check(calls.get()==before,"unselected source sampled");
            rejects(()->generate("*",null,null),IllegalArgumentException.class);check(calls.get()==before,"invalid type reached provider");
            rejects(()->generate("owned-contour-provider",()->true,null),CancellationException.class);check(calls.get()==before,"pre-cancel reached provider");
            AtomicBoolean cancel=new AtomicBoolean();
            rejects(()->generate("owned-contour-provider",cancel::get,value->{if(value>0)cancel.set(true);}),CancellationException.class);
            check(calls.get()>before,"mid-sampling cancel not exercised");
            rejects(()->generate("owned-contour-provider",null,value->{throw primary;}),RuntimeException.class);
            fault.set(true);boolean caught=false;
            try{generate("owned-contour-provider",null,null);}catch(RuntimeException error){caught=true;check(error==primary,"provider exception identity replaced");}
            check(caught,"provider failure swallowed");fault.set(false);
            check(generate("owned-contour-provider",null,null).fullySampled(),"provider recovery failed");
            hole.set(true);var partial=generate("owned-contour-provider",null,null);
            check(!partial.fullySampled()&&partial.sampledPoints()>0&&partial.sampledPoints()<81,"no-data coverage hidden");
            for(var line:partial.lines())for(var point:line.points())check(point.longitude()<=1e-12,"contour crossed omitted no-data cells");
            hole.set(false);
        }finally{ElevationSourceManager.detach(source);}
        var detached=generate("owned-contour-provider",null,null);
        check(detached.sampledPoints()==0&&detached.lines().isEmpty(),"detached provider leaked");
        chunk.dispose();bounds.dispose();ring.dispose();
        System.out.println("ELEVATION_CONTOUR_CONTROLS_PASS checks="+checks);
    }
}
