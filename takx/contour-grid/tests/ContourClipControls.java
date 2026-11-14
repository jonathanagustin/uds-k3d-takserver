// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import gov.tak.project.contour.*;
import java.util.*;
import java.util.concurrent.CancellationException;
import java.util.concurrent.atomic.AtomicBoolean;

public final class ContourClipControls {
    static int checks;
    static void check(boolean value,String why){if(!value)throw new AssertionError(why);checks++;}
    static ContourGrid.Point point(double x,double y){return new ContourGrid.Point(x,y);}
    static ContourGrid.Line line(ContourGrid.Point... points){return new ContourGrid.Line(50,List.of(points));}
    static List<ContourGrid.Line> clip(ContourGrid.Line line){return ContourClip.clip(List.of(line),-.5,-.5,.5,.5,null,null);}
    static void rejects(Runnable work,Class<? extends Throwable> type){try{work.run();}catch(Throwable t){check(type.isInstance(t),"wrong error");return;}throw new AssertionError("missing failure");}
    // Independent parameter breakpoints and interval midpoints, rather than clipping inequalities.
    static boolean hasVisibleLength(ContourGrid.Point a,ContourGrid.Point b){
        if(a.equals(b))return false;
        double dx=b.longitude()-a.longitude(),dy=b.latitude()-a.latitude();
        List<Double> cuts=new ArrayList<>(List.of(0.0,1.0));
        for(double edge:new double[]{-.5,.5}){
            if(dx!=0){double t=(edge-a.longitude())/dx;if(t>0&&t<1)cuts.add(t);}
            if(dy!=0){double t=(edge-a.latitude())/dy;if(t>0&&t<1)cuts.add(t);}
        }
        Collections.sort(cuts);
        for(int i=1;i<cuts.size();i++){
            if(cuts.get(i).equals(cuts.get(i-1)))continue;
            double t=(cuts.get(i)+cuts.get(i-1))/2,x=a.longitude()+t*dx,y=a.latitude()+t*dy;
            if(x>=-.5&&x<=.5&&y>=-.5&&y<=.5)return true;
        }
        return false;
    }
    public static void main(String[] args){
        for(double ax:new double[]{-1,0,1})for(double ay:new double[]{-1,0,1})
        for(double bx:new double[]{-1,0,1})for(double by:new double[]{-1,0,1}){
            var a=point(ax,ay);var b=point(bx,by);var result=clip(line(a,b));
            check(!result.isEmpty()==hasVisibleLength(a,b),"segment clipping differs from midpoint oracle");
            check(result.size()<=1,"single segment split unexpectedly");
            for(var part:result){check(part.elevationMeters()==50,"elevation lost");for(var p:part.points()){
                check(p.longitude()>=-.5&&p.longitude()<=.5&&p.latitude()>=-.5&&p.latitude()<=.5,"vertex outside clip");
                check(Math.abs((p.longitude()-ax)*(by-ay)-(p.latitude()-ay)*(bx-ax))<1e-12,"vertex off source segment");
            }}
        }
        var tinyX=ContourClip.clip(List.of(line(point(-Double.MIN_VALUE,0),point(.5,0))),0,-1,1,1,null,null);
        check(tinyX.get(0).points().get(0).longitude()==0,"subnormal x leaked outside clip");
        var tinyY=ContourClip.clip(List.of(line(point(0,-Double.MIN_VALUE),point(0,.5))),-1,0,1,1,null,null);
        check(tinyY.get(0).points().get(0).latitude()==0,"subnormal y leaked outside clip");
        var crossing=clip(line(point(-1,0),point(1,0)));
        check(crossing.get(0).points().equals(List.of(point(-.5,0),point(.5,0))),"horizontal endpoints differ");
        check(clip(line(point(-1,0),point(0,1))).isEmpty(),"point-only corner contact emitted a line");
        var ring=line(point(0,-1),point(1,-1),point(1,1),point(-1,1),point(-1,-1),point(0,-1));
        var parts=ContourClip.clip(List.of(ring),-.5,-2,.5,2,null,null);
        check(parts.size()==2,"closed-ring visible pieces differ");
        check(parts.stream().anyMatch(v->v.points().size()==3&&v.points().contains(point(0,-1))),"cyclic first/last pieces not joined");
        var inside=line(point(-.2,-.2),point(.2,-.2),point(.2,.2),point(-.2,-.2));
        check(clip(inside).get(0).points().equals(inside.points()),"contained closed ring changed");
        check(clip(line(point(0,0),point(0,0),point(.2,.2))).get(0).points().equals(List.of(point(0,0),point(.2,.2))),"duplicate vertex split line");
        List<Integer> progress=new ArrayList<>();var immutable=ContourClip.clip(List.of(inside),-.5,-.5,.5,.5,null,progress::add);
        check(progress.equals(List.of(0,100)),"progress endpoints differ");
        rejects(immutable::clear,UnsupportedOperationException.class);rejects(()->immutable.get(0).points().clear(),UnsupportedOperationException.class);
        rejects(()->ContourClip.clip(List.of(inside),1,-1,-1,1,null,null),IllegalArgumentException.class);
        rejects(()->ContourClip.clip(List.of(line(point(Double.NaN,0),point(0,0))),-.5,-.5,.5,.5,null,null),IllegalArgumentException.class);
        rejects(()->ContourClip.clip(List.of(inside),-.5,-.5,.5,.5,()->true,null),CancellationException.class);
        AtomicBoolean cancel=new AtomicBoolean();rejects(()->ContourClip.clip(List.of(inside),-.5,-.5,.5,.5,cancel::get,value->cancel.set(true)),CancellationException.class);
        RuntimeException primary=new RuntimeException("owned progress failure");boolean caught=false;
        try{ContourClip.clip(List.of(inside),-.5,-.5,.5,.5,null,value->{throw primary;});}catch(RuntimeException error){caught=true;check(error==primary,"callback exception identity replaced");}
        check(caught,"progress failure swallowed");
        check(ContourClip.clip(List.of(),-.5,-.5,.5,.5,null,null).isEmpty(),"empty input differs");
        System.out.println("contour-clip-controls passed checks="+checks);
    }
}
