// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Owned CPU JNI callback control; not renderer acceptance.
import gov.tak.api.engine.map.RenderContext;
import gov.tak.api.engine.map.RenderSurface2;
public final class ManagedBridgeProbe {
    static final RuntimeException SENTINEL = new RuntimeException("owned callback sentinel");
    static final RuntimeException CLEANUP = new RuntimeException("owned cleanup sentinel");
    static String throwing = "";
    static int removed, destroyed;
    static void call(String name) { if (throwing.equals(name) || (throwing.equals("cleanupDpi") && name.equals("dpi"))) throw SENTINEL; }
    static final class Surface implements RenderSurface2 {
        public double getDpi() { call("dpi"); return 96; }
        public int getWidth() { call("width"); return 160; }
        public int getHeight() { call("height"); return 120; }
        public int getSurfaceWidth() { call("width"); return 160; }
        public int getSurfaceHeight() { call("height"); return 120; }
        public void addOnSizeChangedListener(OnSizeChangedListener l) { call("addListener"); }
        public void removeOnSizeChangedListener(OnSizeChangedListener l) {
            call("removeListener"); removed++;
            if(throwing.equals("cleanupDpi")) throw CLEANUP;
        }
    }
    static final class Context implements RenderContext<Surface> {
        final Surface surface = new Surface();
        float frameRate=60;
        boolean continuous=true;
        final boolean child;
        Context() { this(false); }
        Context(boolean value) { child=value; }
        public boolean isRenderThread() { call("renderThread"); return true; }
        public void queueEvent(Runnable r) { call("queue"); r.run(); }
        public void requestRefresh() { call("refresh"); }
        public void setFrameRate(float rate) { call("setRate"); frameRate=rate; }
        public float getFrameRate() { call("rate"); return frameRate; }
        public void setContinuousRenderEnabled(boolean value) { call("setContinuous"); continuous=value; }
        public boolean isContinuousRenderEnabled() { call("continuous"); return continuous; }
        public boolean supportsChildContext() { call("supportsChild"); return throwing.startsWith("child"); }
        public RenderContext createChildContext() { call("childCreate"); return new Context(true); }
        public void destroyChildContext(RenderContext child) { destroyed++;
            if(throwing.equals("childSurface")) throw CLEANUP;
            call("childDestroy"); }
        public boolean isAttached() { call("attached"); return true; }
        public boolean attach() { call("attach"); return true; }
        public boolean detach() { call("detach"); return true; }
        public boolean isMainContext() { call("main"); return true; }
        public Surface getRenderSurface() { if(child) call("childSurface"); call("surface"); return surface; }
    }
    static native void exercise(Context value, int operation);
    public static void main(String[] args) {
        for(String path:args) System.load(path);
        exercise(new Context(), 0);
        String[] names={"renderThread","refresh","setRate","rate","setContinuous","continuous","supportsChild","attached","attach","detach","main","dpi","width","height","surface","queue","addListener","removeListener","cleanupDpi","childSurface","childDestroy","childCreate"};
        for(int i=0;i<names.length;i++) {
            throwing=names[i];
            try { exercise(new Context(),i+1); throw new AssertionError("Lost exception: "+throwing); }
            catch(RuntimeException failure) { if(failure!=SENTINEL) throw new AssertionError("Replaced exception",failure); }
        }
        if(removed!=4 || destroyed!=2) throw new AssertionError("Lost cleanup: listeners="+removed+" children="+destroyed);
        throwing=""; exercise(new Context(),23);
        System.out.println("BRIDGE_CALLBACKS_COMPLETED operations="+names.length+" listeners="+removed+" children="+destroyed);
    }
}
