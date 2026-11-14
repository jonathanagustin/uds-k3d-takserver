// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.map.elevation.*;
import com.atakmap.map.layer.feature.geometry.*;
import com.atakmap.coremap.maps.coords.GeoPoint;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

public final class ElevationFaultControls {
    static int checks;
    static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);checks++;}
    static final class State {
        String fault; boolean armed, thrown, secondary; int closeCalls,disposeCalls,secondaryCalls;
        final RuntimeException primary=new RuntimeException("owned elevation primary");
        final RuntimeException cleanup=new RuntimeException("owned elevation cleanup");
        State(String fault){this.fault=fault;}
        void hit(String method){if(armed&&fault.equals(method)){armed=false;thrown=true;throw primary;}}
        void cleanup(String method){
            hit(method);
            if(secondary&&thrown){secondaryCalls++;throw cleanup;}
        }
    }
    static Object invoke(Object target,Method method,Object[] args)throws Throwable {
        try{return method.invoke(target,args);}catch(InvocationTargetException error){throw error.getCause();}
    }
    static ElevationChunk wrap(ElevationChunk target,State state){
        return (ElevationChunk)Proxy.newProxyInstance(ElevationChunk.class.getClassLoader(),new Class<?>[]{ElevationChunk.class},(proxy,method,args)->{
            if(method.getName().equals("dispose")){
                state.disposeCalls++;
                try{return invoke(target,method,args);}finally{state.cleanup("chunk:dispose");}
            }
            state.hit("chunk:"+method.getName());
            return invoke(target,method,args);
        });
    }
    static ElevationSource.Cursor wrap(ElevationSource.Cursor target,State state){
        return (ElevationSource.Cursor)Proxy.newProxyInstance(ElevationSource.Cursor.class.getClassLoader(),new Class<?>[]{ElevationSource.Cursor.class},(proxy,method,args)->{
            if(method.getName().equals("close")){
                state.closeCalls++;
                try{return invoke(target,method,args);}finally{state.cleanup("cursor:close");}
            }
            state.hit("cursor:"+method.getName());
            Object value=invoke(target,method,args);
            return method.getName().equals("get")&&value!=null?wrap((ElevationChunk)value,state):value;
        });
    }
    static final class Source extends ElevationSource {
        final ElevationSource delegate;final State state;
        Source(ElevationSource delegate,State state){this.delegate=delegate;this.state=state;}
        public String getName(){state.hit("source:getName");return delegate.getName();}
        public Cursor query(QueryParameters params){state.hit("source:query");return wrap(delegate.query(params),state);}
        public Envelope getBounds(){state.hit("source:getBounds");return delegate.getBounds();}
        public void addOnContentChangedListener(OnContentChangedListener listener){state.hit("source:add");delegate.addOnContentChangedListener(listener);}
        public void removeOnContentChangedListener(OnContentChangedListener listener){state.hit("source:remove");delegate.removeOnContentChangedListener(listener);}
    }
    static void sample(ElevationSource.QueryParameters query){
        List<GeoPoint> points=List.of(new GeoPoint(.2,.4),new GeoPoint(-.3,-.6));double[] values={Double.NaN,Double.NaN};
        check(ElevationManager.getElevation(points.iterator(),values,query),"real bulk sampling incomplete");
        check(Math.abs(values[0]-50)<1e-10&&Math.abs(values[1]+75)<1e-10,"real analytic plane differs");
    }
    public static void main(String[] args)throws Exception {
        for(String line:Files.readAllLines(Path.of(args[0])))System.load(line.split(" ",2)[1]);
        State state=new State(args[1]);state.secondary=args.length>2&&args[2].equals("secondary");
        Polygon bounds=new Polygon(2);LineString ring=new LineString(2);ring.addPoint(-1,-1);ring.addPoint(1,-1);ring.addPoint(1,1);ring.addPoint(-1,1);ring.addPoint(-1,-1);bounds.addRing(ring);
        ElevationChunk chunk=ElevationChunk.Factory.create("owned-elevation-fault","memory://owned-elevation-fault",ElevationData.MODEL_TERRAIN,1,bounds,0,0,true,new ElevationChunk.Factory.Sampler(){
            public double sample(double lat,double lon){return 100*lon+50*lat;}
            public void dispose(){ }
        });
        Source source=new Source(ElevationSourceBuilder.build("owned-elevation-fault",List.of(chunk)),state);
        ElevationSource.QueryParameters query=new ElevationSource.QueryParameters();query.types=Set.of("owned-elevation-fault");query.spatialFilter=bounds;query.flags=ElevationData.MODEL_TERRAIN;
        boolean registered=false;
        try {
            if(!state.fault.equals("source:getName")){ElevationSourceManager.attach(source);registered=true;sample(query);}
            int oldClose=state.closeCalls,oldDispose=state.disposeCalls;state.armed=true;
            boolean caught=false;
            try {
                if(state.fault.equals("source:getName")){ElevationSourceManager.attach(source);registered=true;}
                else sample(query);
            }catch(RuntimeException failure){caught=true;check(failure==state.primary,"primary exception identity lost: "+failure.getClass().getName());}
            check(caught&&state.thrown,"target callback failure not observed");
            if(state.fault.startsWith("chunk:")||state.fault.startsWith("cursor:"))check(state.closeCalls>oldClose,"cursor cleanup skipped");
            if(state.fault.startsWith("chunk:"))check(state.disposeCalls>oldDispose,"chunk cleanup skipped");
            if(state.secondary)check(state.secondaryCalls>0,"secondary cleanup was not attempted");
            state.secondary=false;state.thrown=false;
            if(!registered){ElevationSourceManager.attach(source);registered=true;}
            sample(query);
            System.out.println("ELEVATION_FAULT_CONTROLS_PASS case="+args[1]+" checks="+checks);
        }finally{
            state.armed=false;state.secondary=false;
            if(registered)ElevationSourceManager.detach(source);
            chunk.dispose();bounds.dispose();ring.dispose();
        }
    }
}
