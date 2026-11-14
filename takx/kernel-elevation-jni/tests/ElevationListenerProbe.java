// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.map.elevation.ElevationSource;
import com.atakmap.map.layer.feature.geometry.Envelope;
import com.atakmap.interop.Pointer;
import java.nio.file.*;
import java.util.*;

public final class ElevationListenerProbe {
    static native int exercise(ElevationSource source,int operation);
    static int checks;
    static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);checks++;}
    public static final class Source extends ElevationSource {
        final RuntimeException primary=new RuntimeException("owned source primary");
        final RuntimeException secondary=new RuntimeException("owned source secondary");
        final Set<OnContentChangedListener> active=new LinkedHashSet<>();
        final List<OnContentChangedListener> added=new ArrayList<>();
        String fault;boolean armed,thrown,secondaryCleanup;int removes,secondaryCalls;
        void hit(String point){if(armed&&point.equals(fault)){armed=false;thrown=true;throw primary;}}
        public String getName(){hit("name");return "owned-listener-source";}
        public Cursor query(QueryParameters params){return Cursor.EMPTY;}
        public Envelope getBounds(){hit("bounds");return new Envelope(-1,-2,0,3,4,0);}
        public void addOnContentChangedListener(OnContentChangedListener listener){active.add(listener);added.add(listener);hit("add");}
        public void removeOnContentChangedListener(OnContentChangedListener listener){
            removes++;active.remove(listener);hit("remove");
            if(secondaryCleanup&&thrown){secondaryCalls++;throw secondary;}
        }
        public void fire(){for(OnContentChangedListener listener:List.copyOf(active))listener.onContentChanged(this);}
        void finalized()throws Exception {
            check(active.isEmpty(),"Java listener cleanup skipped");
            for(OnContentChangedListener listener:added){
                var field=listener.getClass().getDeclaredField("pointer");field.setAccessible(true);Pointer pointer=(Pointer)field.get(listener);
                check(pointer.raw==0,"native listener pointer not finalized");
                listener.onContentChanged(this); // A retired callback must safely ignore the destroyed parent.
            }
        }
    }
    public static void main(String[] args)throws Exception {
        for(String line:Files.readAllLines(Path.of(args[0])))System.load(line.split(" ",2)[1]);
        System.load(args[1]);
        for(int operation=0;operation<=5;operation++)for(boolean secondary:List.of(false,true)){
            if(operation==0&&secondary)continue;
            Source source=new Source();source.secondaryCleanup=secondary;source.fault=switch(operation){case 1->"add";case 2,4->"remove";case 3->"bounds";case 5->"name";default->"none";};source.armed=operation!=0;
            boolean caught=false;int notifications=0;
            try{notifications=exercise(source,operation);}catch(RuntimeException error){caught=true;check(error==source.primary,"primary exception identity replaced");}
            if(operation==0)check(!caught&&notifications==2,"normal listener cycle failed");
            else check(caught&&source.thrown,"requested callback fault not observed");
            source.finalized();
            if(secondary&&operation!=5)check(source.secondaryCalls>0,"secondary cleanup not attempted");
            source.secondaryCleanup=false;source.thrown=false;source.fault="none";source.armed=false;
            check(exercise(source,0)==2,"listener/bounds recovery failed");source.finalized();
        }
        System.out.println("ELEVATION_LISTENER_CONTROLS_PASS checks="+checks);
    }
}
