// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.map.elevation.*;
import com.atakmap.map.layer.feature.geometry.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

public final class ElevationChunkProbe {
    static native void exercise(ElevationChunk chunk,int operation);
    static native int status();
    static int checks;
    static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);checks++;}
    static final class State {
        String fault;boolean secondary,thrown;int disposed,cleanupErrors,callbacks,postFailure;
        final RuntimeException primary=new RuntimeException("owned chunk primary");
        final RuntimeException cleanup=new RuntimeException("owned chunk cleanup");
        Object invoke(Object target,Method method,Object[] args)throws Throwable {
            String name=method.getName();
            if(name.equals("dispose")){
                disposed++;
                if(name.equals(fault)){thrown=true;throw primary;}
                if(thrown&&secondary){cleanupErrors++;throw cleanup;}
            }else {
                callbacks++;
                if(thrown)postFailure++;
                if(name.equals(fault)){thrown=true;throw primary;}
            }
            try{return method.invoke(target,args);}catch(InvocationTargetException error){throw error.getCause();}
        }
    }
    public static void main(String[] args)throws Exception {
        for(String line:Files.readAllLines(Path.of(args[0])))System.load(line.split(" ",2)[1]);
        System.load(args[1]);
        String[] faults={"none","getResolution","getCE","getLE","isAuthoritative","getFlags","createData","sample","sample","dispose","getType","getUri","getBounds"};
        List<Integer> schedule=new ArrayList<>();schedule.add(0);
        for(int operation=1;operation<faults.length;operation++){
            schedule.add(operation);schedule.add(0);schedule.add(operation);schedule.add(0);
        }
        for(int trial=0;trial<schedule.size();trial++){
            int operation=schedule.get(trial);boolean secondary=trial%4==3;
            State state=new State();state.fault=faults[operation];state.secondary=secondary;
            Polygon bounds=new Polygon(2);LineString ring=new LineString(2);
            ring.addPoint(-.001,-.001);ring.addPoint(.001,-.001);ring.addPoint(.001,.001);ring.addPoint(-.001,.001);ring.addPoint(-.001,-.001);bounds.addRing(ring);
            ElevationChunk actual=ElevationChunk.Factory.create("owned-chunk","memory://owned-chunk",1,1,bounds,2,3,true,new ElevationChunk.Factory.Sampler(){
                public double sample(double lat,double lon){return 100*lon+50*lat;}
                public void dispose(){}
            });
            ElevationChunk wrapped=(ElevationChunk)Proxy.newProxyInstance(ElevationChunk.class.getClassLoader(),new Class<?>[]{ElevationChunk.class},(proxy,method,values)->state.invoke(actual,method,values));
            try{
                boolean caught=false;
                try{exercise(wrapped,operation);}catch(RuntimeException error){caught=true;check(error==state.primary,"primary exception replaced");}
                check(operation==0?!caught:caught&&state.thrown,"fault observation differs");
                check(status()==(operation==0?2:operation>=10?1:operation==9?0:3),"native value/guard check failed");
                check(state.postFailure==0,"callback entered with a pending primary");
                check(state.disposed==1,"native cleanup not attempted exactly once");
                if(secondary&&operation!=9)check(state.cleanupErrors==1,"secondary cleanup error not exercised");
            }finally{actual.dispose();bounds.dispose();ring.dispose();}
        }
        System.out.println("ELEVATION_CHUNK_CONTROLS_PASS checks="+checks);
    }
}
