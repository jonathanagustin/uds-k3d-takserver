// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Owned mixed-interface CPU regression; no renderer qualification.
import gov.tak.api.engine.map.*;
public final class SurfaceModesProbe {
    static class Legacy implements RenderSurface {
        public double getDpi(){return 96;}
        public int getWidth(){return 80;}
        public int getHeight(){return 60;}
        public void addOnSizeChangedListener(OnSizeChangedListener value){}
        public void removeOnSizeChangedListener(OnSizeChangedListener value){}
    }
    static final class Modern extends Legacy implements RenderSurface2 {
        public int getSurfaceWidth(){return 160;}
        public int getSurfaceHeight(){return 120;}
    }
    static native long[] sizes(Legacy legacy, Modern modern, boolean modernFirst);
    static void check(boolean order, boolean noisy) {
        long[] values=sizes(new Legacy(),new Modern(),order);
        if(noisy)System.out.println("SURFACE_MODES order="+order+" sizes="+java.util.Arrays.toString(values));
        if(!java.util.Arrays.equals(values,new long[]{80,60,160,120}))throw new AssertionError("Surface mode crossed instance boundaries");
    }
    public static void main(String[] args) throws Exception {
        for(String path:args)System.load(path);
        check(true,true);check(false,true);
        var failure=new java.util.concurrent.atomic.AtomicReference<Throwable>();
        Thread[] threads=new Thread[2];
        for(int index=0;index<threads.length;index++) {
            final int selected=index;
            threads[index]=new Thread(() -> {
                try {for(int n=0;n<50;n++)check((n+selected)%2==0,false);}
                catch(Throwable error){failure.compareAndSet(null,error);}
            },"owned-surface-mode-"+index);
            threads[index].start();
        }
        for(Thread thread:threads){thread.join(10000);if(thread.isAlive())throw new AssertionError("Mode control timeout");}
        if(failure.get()!=null)throw new AssertionError("Concurrent mode mismatch",failure.get());
        System.out.println("SURFACE_MODES_COMPLETED both construction orders and 100 concurrent calls");
    }
}
