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
            int minorColor=0xff336699,majorColor=0xffddaa33;
            ContourFeatures batch=ContourFeatures.create(result.lines(),25,0,2,minorColor,majorColor,1.5f,3,null);
            try {
                check(batch.features().size()==result.lines().size(),"native feature count differs");
                rejects(()->batch.features().clear(),UnsupportedOperationException.class);
                for(int i=0;i<batch.features().size();i++){
                    var feature=batch.features().get(i);var line=result.lines().get(i);
                    var geometry=(LineString)feature.getGeometry();
                    var style=(com.atakmap.map.layer.feature.style.BasicStrokeStyle)feature.getStyle();
                    var attributes=feature.getAttributes();
                    try{
                        boolean major=Math.floorMod((long)Math.rint(line.elevationMeters()/25),2)==0;
                        check(geometry.getNumPoints()==line.points().size(),"native geometry point count differs");
                        for(int point=0;point<geometry.getNumPoints();point++){
                            check(geometry.getX(point)==line.points().get(point).longitude(),"native longitude differs");
                            check(geometry.getY(point)==line.points().get(point).latitude(),"native latitude differs");
                        }
                        check(style.getColor()==(major?majorColor:minorColor),"major/minor color differs");
                        check(style.getStrokeWidth()==(major?3:1.5f),"major/minor width differs");
                        check(attributes.getDoubleAttribute("elevation_hae_m")==line.elevationMeters(),"elevation metadata lost");
                        check(attributes.getLongAttribute("level_index")==Math.round(line.elevationMeters()/25),"level index lost");
                        check(attributes.getStringAttribute("contour_class").equals(major?"major":"minor"),"classification metadata differs");
                        check(feature.getName().endsWith(" m HAE"),"elevation datum label differs");
                    }finally{geometry.dispose();style.dispose();attributes.dispose();}
                }
            }finally{batch.close();batch.close();}
            rejects(batch::features,IllegalStateException.class);
            rejects(()->ContourFeatures.create(result.lines(),25,0,2,minorColor,majorColor,0,3,null),IllegalArgumentException.class);
            rejects(()->ContourFeatures.create(result.lines(),25,0,2,minorColor,majorColor,1,3,()->true),CancellationException.class);
            var invalid=List.of(new ContourGrid.Line(12,List.of(new ContourGrid.Point(0,0),new ContourGrid.Point(1,1))));
            rejects(()->ContourFeatures.create(invalid,25,0,2,minorColor,majorColor,1,3,null),IllegalArgumentException.class);
            AtomicInteger conversionChecks=new AtomicInteger();
            rejects(()->ContourFeatures.create(result.lines(),25,0,2,minorColor,majorColor,1,3,
                    ()->conversionChecks.incrementAndGet()>2*result.lines().size()+2),CancellationException.class);
            check(conversionChecks.get()>2*result.lines().size()+2,"mid-conversion cancellation unused");
            AtomicInteger throwingChecks=new AtomicInteger();boolean conversionCaught=false;
            try{ContourFeatures.create(result.lines(),25,0,2,minorColor,majorColor,1,3,()->{
                if(throwingChecks.incrementAndGet()>2*result.lines().size()+2)throw primary;return false;
            });}catch(RuntimeException error){conversionCaught=true;check(error==primary,"conversion callback primary replaced");}
            check(conversionCaught,"conversion callback error swallowed");
            try(var recovered=ContourFeatures.create(result.lines(),25,0,2,minorColor,majorColor,1,3,null)){
                check(recovered.features().size()==result.lines().size(),"conversion recovery failed");
            }
            var clipped=result.clipped(-.3,-.3,.3,.3,null,null);
            var storedLines=clipped.lines();
            Path database=Path.of(args[1]);
            long storedSet;
            try(var storedBatch=ContourFeatures.create(storedLines,25,0,2,minorColor,majorColor,1,3,null)){
                ContourLayer owner=ContourLayer.create("Owned native contour layer",database,storedBatch);
                storedSet=owner.featureSetId();
                try{
                    var layer=owner.layer();
                    check(layer.getName().equals("Owned native contour layer"),"native layer name differs");
                    check(layer.getDataStore().queryFeaturesCount(null)==storedLines.size(),"native layer feature count differs");
                    layer.setVisible(false);check(!layer.isVisible(),"layer visibility false ignored");
                    layer.setVisible(true);check(layer.isVisible(),"layer visibility true ignored");
                    int read=0;
                    try(var cursor=layer.getDataStore().queryFeatures(null)){
                        while(cursor.moveToNext()){
                            var feature=cursor.get();var attributes=feature.getAttributes();
                            try{
                                check(feature.getFeatureSetId()==storedSet,"stored feature set identity differs");
                                check(Double.isFinite(attributes.getDoubleAttribute("elevation_hae_m")),"stored elevation metadata absent");
                                read++;
                            }finally{attributes.dispose();feature.dispose();}
                        }
                    }
                    check(read==storedLines.size(),"native feature cursor incomplete");
                    boolean existsRefused=false;
                    try{ContourLayer.create("Existing must refuse",database,storedBatch);}catch(FileAlreadyExistsException expected){existsRefused=true;}
                    check(existsRefused,"existing database overwritten");
                    Path alias=database.resolveSibling("database-alias");Files.createSymbolicLink(alias,database.getParent());
                    boolean aliasRefused=false;
                    try{ContourLayer.create("Alias must refuse",alias.resolve("new.sqlite"),storedBatch);}catch(IllegalArgumentException expected){aliasRefused=true;}
                    finally{Files.delete(alias);}
                    check(aliasRefused&&!Files.exists(database.resolveSibling("new.sqlite")),"symlink database path followed");
                }finally{owner.close();owner.close();}
                rejects(owner::layer,IllegalStateException.class);
                rejects(owner::featureSetId,IllegalStateException.class);
                check(storedBatch.features().size()==storedLines.size(),"caller batch was disposed");
            }
            var reopened=new com.atakmap.map.layer.feature.datastore.FeatureSetDatabase2(database.toFile());
            try{
                check(reopened.queryFeaturesCount(null)==storedLines.size(),"persistent contour readback differs");
                reopened.deleteFeatureSet(storedSet);
                check(reopened.queryFeaturesCount(null)==0,"owned feature set cleanup failed");
            }finally{reopened.dispose();}
            check(clipped.sampledPoints()==result.sampledPoints()&&clipped.totalPoints()==result.totalPoints(),"clipping rewrote source-grid coverage");
            check(!clipped.lines().isEmpty(),"clipping removed all analytic contours");
            for(var line:clipped.lines())for(var point:line.points()){
                check(point.longitude()>=-.3&&point.longitude()<=.3&&point.latitude()>=-.3&&point.latitude()<=.3,"clipped vertex outside requested extent");
                check(Math.abs(100*point.longitude()+50*point.latitude()-line.elevationMeters())<1e-8,"clipped vertex off analytic contour");
            }
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
