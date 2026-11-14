// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package com.atakmap.map.opengl;

import android.graphics.Typeface;
import com.atakmap.android.maps.MapTextFormat;
import com.atakmap.map.Globe;
import com.atakmap.map.layer.control.RenderContextControl;
import com.atakmap.opengl.GLText;
import com.atakmap.opengl.Shader;
import com.jogamp.opengl.*;
import com.jogamp.opengl.awt.GLCanvas;
import gov.tak.platform.commons.opengl.GLES30;
import gov.tak.platform.engine.JOGLRenderContext;
import java.awt.EventQueue;
import java.awt.Frame;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicReference;

/** Genuine headed test. Requires the reviewed feature Core/JNI and real providers.
 * This source is preparation, not evidence of a runtime pass. */
public final class ContextRecreationProbe {
    static final AtomicReference<Throwable> failure = new AtomicReference<>();
    static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    static void rejected(Runnable action) {
        try { action.run(); throw new AssertionError("Illegal lifecycle operation accepted"); }
        catch (IllegalStateException expected) {}
    }
    static void rejectAllTextGpuOverloads(GLText text) {
        int checked=0;
        for (java.lang.reflect.Method method:GLText.class.getDeclaredMethods()) {
            if (!java.lang.reflect.Modifier.isPublic(method.getModifiers()) ||
                    !(method.getName().startsWith("draw") || method.getName().startsWith("batch"))) continue;
            Object[] args=new Object[method.getParameterCount()];
            Class<?>[] types=method.getParameterTypes();
            for(int i=0;i<types.length;i++) {
                if(types[i]==float.class) args[i]=0f;
                else if(types[i]==int.class) args[i]=0;
                else if(types[i]==String.class) args[i]="retired";
                // All GPU overloads must reject ownership BEFORE touching a
                // batch/array argument, even if that argument is null.
            }
            try { method.invoke(text,args); throw new AssertionError("Stale text overload accepted: "+method); }
            catch(java.lang.reflect.InvocationTargetException error) {
                check(error.getCause() instanceof IllegalStateException,"Wrong stale text failure: "+error.getCause());
            } catch(ReflectiveOperationException error) { throw new AssertionError(error); }
            checked++;
        }
        check(checked==14,"Unexpected GLText GPU overload inventory");
        check(Float.isFinite(text.getStringWidth("CPU metrics remain owned")),"Stale CPU metrics invalid");
    }
    static String sha256(Path path) throws Exception {
        java.security.MessageDigest digest=java.security.MessageDigest.getInstance("SHA-256");
        try(java.io.InputStream input=Files.newInputStream(path)) {
            byte[] buffer=new byte[32768]; int count;
            while((count=input.read(buffer))!=-1) digest.update(buffer,0,count);
        }
        StringBuilder result=new StringBuilder();
        for(byte value:digest.digest()) result.append(String.format("%02x",value&255));
        return result.toString();
    }
    static void classOrigin(String name,Path expected) throws Exception {
        Class<?> type=Class.forName(name,false,ContextRecreationProbe.class.getClassLoader());
        Path origin=Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath();
        check(origin.equals(expected),"Unexpected class origin: "+name+" "+origin);
        Path bytes=origin.resolve(name.replace('.','/')+".class");
        System.out.println("CLASS_ORIGIN\t"+name+"\t"+origin+"\t"+sha256(bytes));
    }
    static java.util.Map<Path,String> mappedElfs(String phase) throws Exception {
        java.util.Map<Path,String> result=new java.util.TreeMap<>();
        for(String line:Files.readAllLines(Path.of("/proc/self/maps"))) {
            int start=line.indexOf('/'); if(start<0) continue;
            String raw=line.substring(start);
            if(raw.endsWith(" (deleted)")) {
                check(!line.split("\\s+")[1].contains("x"),"Deleted executable mapping");
                continue; // non-executable JVM perf/shared-memory data is not a provider ELF
            }
            Path path=Path.of(raw).toRealPath();
            if(result.containsKey(path) || !Files.isRegularFile(path)) continue;
            try(java.io.InputStream input=Files.newInputStream(path)) {
                byte[] magic=input.readNBytes(4);
                if(magic.length!=4 || magic[0]!=127 || magic[1]!='E' || magic[2]!='L' || magic[3]!='F') continue;
            }
            result.put(path,sha256(path));
        }
        for(java.util.Map.Entry<Path,String> entry:result.entrySet())
            System.out.println("MAPPED_ELF\t"+phase+"\t"+entry.getKey()+"\t"+entry.getValue());
        return result;
    }
    static final class View implements GLEventListener {
        final GLCanvas canvas;
        final float red;
        final Set<String> threads = ConcurrentHashMap.newKeySet();
        GLMapView view;
        Globe globe;
        JOGLRenderContext actualContext;
        GLText text;
        Shader shader;
        gov.tak.api.engine.Shader modernShader;
        volatile int initCount, releaseCount, drawCount;
        volatile boolean terminal;
        volatile String lastDisplayThread, lastDisposeThread;
        int callbacks;
        int queuedTextDrains;
        int managedBasemapDraws;
        int preRealizationCallbacks;
        View(GLCanvas canvas, float red) {
            this.canvas=canvas; this.red=red;
            // Match the real TAKX create() order: CPU view construction and
            // configuration precede first GL init/realization.
            actualContext=new JOGLRenderContext(canvas);
            globe=new Globe();
            // Exercise the public com-interface overload selected by actual TAKX.
            // This is the existing production forwarding adapter over the real
            // JOGL context, never a synthetic/test/current/bootstrap context.
            com.atakmap.map.RenderContext clientContext=new RenderContextBinding(actualContext);
            view=new GLMapView(clientContext,
                    globe,0,0,canvas.getWidth(),canvas.getHeight());
            installBasemap();
            view.queueEvent(() -> preRealizationCallbacks++);
        }
        void installBasemap() {
            view.setBaseMap(new GLMapRenderable() {
                public void draw(GLMapView ignored) {
                    managedBasemapDraws++;
                    GLES30.glClearColor(red,0.25f,0.5f,1f);
                    GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT | GLES30.GL_DEPTH_BUFFER_BIT);
                }
                public void release() {}
            });
        }
        void current(GLAutoDrawable drawable) {
            check(drawable == canvas && drawable.getContext().isCurrent(), "Wrong/noncurrent drawable");
            threads.add(Thread.currentThread().getName());
        }
        void record(Throwable error) {
            failure.compareAndSet(null,error);
            if (error instanceof Error) throw (Error)error;
            if (error instanceof RuntimeException) throw (RuntimeException)error;
            throw new RuntimeException(error);
        }
        @Override public void init(GLAutoDrawable drawable) {
            try {
                current(drawable);
                HeadedAdmission.verifyMaps("owning-init",true);
                System.out.println("GL_CONTEXT\t"+initCount+"\t"+drawable.getChosenGLCapabilities()+"\t"+
                        drawable.getGL().glGetString(GL.GL_VENDOR)+"\t"+drawable.getGL().glGetString(GL.GL_RENDERER)+"\t"+
                        drawable.getGL().glGetString(GL.GL_VERSION));
                if (initCount!=0) {
                    actualContext = new JOGLRenderContext(drawable);
                    check(!terminal,"Recreated disposed view");
                    RenderContextControl control = view.getControl(RenderContextControl.class);
                    check(control != null,"Missing genuine context control");
                    control.setRenderContext(actualContext);
                    installBasemap();
                } else {
                    check(actualContext.isRenderThread() && actualContext.isAttached(),"Pre-realization wrapper did not capture current context");
                }
                view.start();
                check(preRealizationCallbacks==1,"Pre-realization owned work was lost or duplicated");
                GLText nextText = GLText.getInstance(view.getRenderContext(),new MapTextFormat(Typeface.DEFAULT,16));
                Shader nextShader = Shader.get(view.getRenderContext());
                if (text != null) check(text == nextText,"Borrowed GLText CPU identity changed");
                if (shader != null) check(shader == nextShader,"Borrowed Shader CPU identity changed");
                text=nextText; shader=nextShader;
                gov.tak.api.engine.Shader nextModern=gov.tak.api.engine.Shader.create(
                        gov.tak.api.engine.Shader.FLAG_2D,view.getRenderContext());
                if(modernShader!=null) check(modernShader==nextModern,"Borrowed actual pipeline Shader identity changed");
                modernShader=nextModern;
                check(shader.handle != 0,"Missing recreated shader program");
                ContextWorkerProbe.hold(view.ctxptr); // real live view-owned pointer only
                view.queueEvent(() -> callbacks++);
                initCount++;
            } catch(Throwable error) { record(error); }
        }
        @Override public void display(GLAutoDrawable drawable) {
            try {
                current(drawable);
                lastDisplayThread = Thread.currentThread().getName();
                view.render();
                // Kernel terrain is asynchronous. Its managed basemap callback
                // can target an offscreen surface tile rather than pixel(0,0)
                // of the window. Do not mislabel fixture clear as terrain proof.
                int[] framebuffer={-1};
                GLES30.glGetIntegerv(GLES30.GL_FRAMEBUFFER_BINDING,framebuffer,0);
                check(framebuffer[0]==drawable.getContext().getDefaultDrawFramebuffer(),"Kernel did not restore window framebuffer");
                GLES30.glDisable(GLES30.GL_DEPTH_TEST);
                GLES30.glDisable(GLES30.GL_SCISSOR_TEST);
                GLES30.glColorMask(true,true,true,true);
                if(!drawable.getGL().isGLES()) GLES30.glDisable(GL3.GL_FRAMEBUFFER_SRGB);
                GLES30.glViewport(0,0,drawable.getSurfaceWidth(),drawable.getSurfaceHeight());
                GLES30.glClearColor(red,0.25f,0.5f,1);
                GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
                ByteBuffer pixel=ByteBuffer.allocateDirect(4);
                GLES30.glReadPixels(0,0,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
                check(Math.abs((pixel.get(0)&255)-Math.round(red*255))<=2,"Real renderer callback/readback mismatch");
                check(Math.abs((pixel.get(1)&255)-64)<=2,"Real readback green mismatch");
                modernShader.useProgram(true);
                float[] identity={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
                modernShader.setProjection(identity); modernShader.setModelView(identity);
                modernShader.setColor4f(1,1,1,1); modernShader.useProgram(false);
                com.atakmap.opengl.GLES20FixedPipeline.glMatrixMode(com.atakmap.opengl.GLES20FixedPipeline.GL_PROJECTION);
                com.atakmap.opengl.GLES20FixedPipeline.glLoadIdentity();
                com.atakmap.opengl.GLES20FixedPipeline.glOrthof(0,drawable.getSurfaceWidth(),0,drawable.getSurfaceHeight(),-1,1);
                com.atakmap.opengl.GLES20FixedPipeline.glMatrixMode(com.atakmap.opengl.GLES20FixedPipeline.GL_MODELVIEW);
                com.atakmap.opengl.GLES20FixedPipeline.glLoadIdentity();
                text.draw("context",1,1,1,1); // actual native text draw; no pixel inference from metrics
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"GL error after actual renderer/text calls");
                ByteBuffer textPixels=ByteBuffer.allocateDirect(drawable.getSurfaceWidth()*drawable.getSurfaceHeight()*4);
                GLES30.glReadPixels(0,0,drawable.getSurfaceWidth(),drawable.getSurfaceHeight(),GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,textPixels);
                int glyphPixels=0;
                for(int offset=0;offset<textPixels.capacity();offset+=4)
                    if((textPixels.get(offset)&255)>Math.round(red*255)+4 &&
                       (textPixels.get(offset+1)&255)>72 && (textPixels.get(offset+2)&255)>136) glyphPixels++;
                check(glyphPixels>0,"Actual native glyph draw produced no pixels");
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"GL error reading actual native glyph pixels");
                drawCount++;
            } catch(Throwable error) { record(error); }
        }
        @Override public void dispose(GLAutoDrawable drawable) {
            try {
                current(drawable);
                lastDisposeThread = Thread.currentThread().getName();
                // Use the real package-level release barrier to hold genuine
                // old-context text work pending across stop/release. No fake
                // context, raw substitute pointer, or manual JNI_OnLoad call.
                ((RenderContextBinding)view.getRenderContext()).beginRelease();
                view.queueEvent(() -> {
                    GLText queued=GLText.getInstance(view.getRenderContext(),new MapTextFormat(Typeface.DEFAULT,17+initCount));
                    queued.draw("queued old-context release",1,1,1,1);
                    check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Queued old-context text failed");
                    queuedTextDrains++;
                });
                view.stop();
                ContextWorkerProbe.queuePending(view.ctxptr);
                view.release();
                check(queuedTextDrains==releaseCount+1,"Pending old-context text work was not drained");
                ContextWorkerProbe.requireRetired(view.ctxptr);
                check(callbacks==initCount,"Queued work was lost/duplicated");
                rejectAllTextGpuOverloads(text);
                rejected(() -> Shader.get(view.getRenderContext()));
                rejected(() -> modernShader.getHandle());
                rejected(() -> modernShader.useProgram(true));
                if (terminal) {
                    view.dispose();
                    rejectAllTextGpuOverloads(text);
                    rejected(() -> GLText.getInstance(view.getRenderContext(),new MapTextFormat(Typeface.DEFAULT,16)));
                    rejected(() -> Shader.get(view.getRenderContext()));
                    rejected(() -> modernShader.getHandle());
                    rejected(() -> modernShader.setColor4f(1,1,1,1));
                    rejected(() -> view.getControl(RenderContextControl.class).setRenderContext(actualContext));
                }
                releaseCount++;
            } catch(Throwable error) { record(error); }
        }
        @Override public void reshape(GLAutoDrawable drawable,int x,int y,int width,int height) {}
    }
    static void healthy() {
        Throwable error=failure.get();
        if(error!=null) throw new AssertionError("GL callback failed",error);
    }
    static final class BorrowedOwnerFixture {
        java.lang.ref.WeakReference<GLMapView> renderer;
        Object[] owners;
        long destroyedBefore;
    }
    static void destroyView(View target) {
        // Public JOGL disposal runs each genuine callback with a current context.
        // Initialize this caller's dispatch before renderer cleanup, and remove
        // listeners before AWT can repaint/reinitialize them during destruction.
        target.canvas.disposeGLEventListener(target.actualContext,true);
        target.canvas.disposeGLEventListener(target,true);
        target.canvas.destroy();
    }
    static BorrowedOwnerFixture terminalBorrowFixture(int retained) throws Exception {
        BorrowedOwnerFixture fixture=new BorrowedOwnerFixture();
        fixture.destroyedBefore=ContextWorkerProbe.terminalCounts()[1];
        EventQueue.invokeAndWait(() -> {
            GLCanvas canvas=new GLCanvas(new GLCapabilities(GLProfile.getMaxProgrammable(true)));
            View callback=new View(canvas,0.375f);
            canvas.addGLEventListener(callback);
            Frame frame=new Frame("Terminal borrowed-owner GC");
            try {
                frame.add(canvas); frame.setSize(160,120); frame.setVisible(true);
                canvas.display(); healthy();
                fixture.renderer=new java.lang.ref.WeakReference<>(callback.view);
                fixture.owners=new Object[]{callback.view.getLabelManager(),callback.view.terrain,
                        callback.view.getControl(RenderContextControl.class)};
                for(int index=0;index<fixture.owners.length;index++)
                    if(index!=retained) fixture.owners[index]=null;
                callback.terminal=true; destroyView(callback); healthy();
                // Do not keep the renderer alive through this test's listener.
                canvas.removeGLEventListener(callback);
            } finally { frame.dispose(); }
        });
        return fixture;
    }
    static void verifyRetainedBorrow(BorrowedOwnerFixture fixture,int retained) throws Exception {
            Object borrow=fixture.owners[retained];
            for(int cycle=0;cycle<3;cycle++) { System.gc(); Thread.sleep(25); }
            GLMapView owner=fixture.renderer.get();
            check(owner!=null,"Live borrowed wrapper lost native renderer owner");
            if(borrow instanceof GLLabelManager)
                check(((GLLabelManager)borrow).getPriorityLevel()!=null,"Borrowed label manager invalid after terminal release");
            if(borrow instanceof ElMgrTerrainRenderService)
                check(((ElMgrTerrainRenderService)borrow).owner==owner,"Terrain wrapper lost strong owner");
            if(borrow instanceof RenderContextControl)
                rejected(() -> ((RenderContextControl)borrow).setRenderContext(null));
            java.lang.ref.Reference.reachabilityFence(borrow);
    }
    static void terminalBorrowGc(int retained) throws Exception {
        BorrowedOwnerFixture fixture=terminalBorrowFixture(retained);
        verifyRetainedBorrow(fixture,retained);
        fixture.owners=null;
        // Bound the wait; failure to reclaim is a failed control, never a pass
        // inferred from Java reachability alone. No manual cleaner invocation.
        for(int attempt=0;attempt<100;attempt++) {
            System.gc(); System.runFinalization(); Thread.sleep(50);
            long[] counts=ContextWorkerProbe.terminalCounts();
            if(fixture.renderer.get()==null && counts[1]>fixture.destroyedBefore) {
                System.out.println("TERMINAL_GC renderer-collected native-destructor-observed");
                return;
            }
        }
        throw new AssertionError("Terminal renderer CPU destruction not observed within GC bound");
    }
    public static void main(String[] args) throws Exception {
        check(args.length==4,"Expected reviewed provider manifest, test helper, feature class root, frozen base class root");
        HeadedAdmission.checkOrigins();
        HeadedAdmission.verifyMaps("before-provider-loads",false);
        Path featureClasses=Path.of(args[2]).toRealPath(), baseClasses=Path.of(args[3]).toRealPath();
        for(String name:new String[]{
                "com.atakmap.map.layer.control.RenderContextControl","com.atakmap.map.opengl.RenderContextBinding",
                "com.atakmap.map.opengl.GLMapView","com.atakmap.map.opengl.GLRenderGlobals",
                "com.atakmap.android.maps.graphics.GLImageCache","com.atakmap.android.maps.graphics.GLImage",
                "com.atakmap.opengl.GLText","com.atakmap.opengl.Shader","com.atakmap.opengl.GLNinePatch",
                "com.atakmap.opengl.GLES20FixedPipeline","gov.tak.api.engine.Shader",
                "gov.tak.platform.engine.JOGLRenderContext","com.atakmap.map.layer.raster.tilereader.opengl.NodeCore",
                "com.atakmap.map.layer.raster.tilereader.opengl.NodeContextResources",
                "com.atakmap.map.layer.raster.tilereader.opengl.GLQuadTileNode4"}) classOrigin(name,featureClasses);
        for(String name:new String[]{"com.atakmap.map.Globe","gov.tak.api.engine.map.RenderContext",
                "com.atakmap.interop.Interop","gov.tak.platform.commons.opengl.JOGLGLES"}) classOrigin(name,baseClasses);
        for(String line:Files.readAllLines(Path.of(args[0]))) {
            if(line.isBlank()) continue;
            Path provider=Path.of(line);
            check(provider.isAbsolute() && Files.isRegularFile(provider),"Invalid real provider path");
            System.load(provider.toRealPath().toString());
        }
        System.load(Path.of(args[1]).toRealPath().toString());
        // Match application initialization before constructing the real view.
        // EngineLibrary owns shader context and protected application directories.
        com.atakmap.map.EngineLibrary.initialize();
        // Exercise supported JOGL caller-thread context movement deliberately.
        // This test mode is recorded; it is not a production runtime setting.
        System.out.println("JOGL threading before="+Threading.getMode());
        Threading.disableSingleThreading();
        check(!Threading.isSingleThreaded(),"JOGL did not enable caller-thread GL dispatch");
        Frame[] frames=new Frame[2]; View[] views=new View[2];
        try {
            EventQueue.invokeAndWait(() -> {
                for(int i=0;i<2;i++) {
                    GLCanvas canvas=new GLCanvas(new GLCapabilities(GLProfile.getMaxProgrammable(true)));
                    views[i]=new View(canvas,i==0?0.75f:0.125f);
                    canvas.addGLEventListener(views[i]);
                    Frame frame=new Frame("Kernel context lifecycle "+i);
                    frames[i]=frame; frame.add(canvas); frame.setSize(160,120);
                    frame.setLocation(30+i*180,30); frame.setVisible(true);
                }
            });
            for(View view:views) { view.canvas.display(); healthy(); check(view.initCount==1,"Initial callback order"); }
            for(View view:views) {
                for(int frame=0;frame<16 && view.managedBasemapDraws==0;frame++) {
                    view.canvas.display(); healthy(); Thread.sleep(16);
                }
                check(view.managedBasemapDraws>0,"Actual Kernel surface callback did not render within warmup bound");
            }
            HeadedAdmission.verifyMaps("initial-real-views",true);
            java.util.Map<Path,String> firstMaps=mappedElfs("initial-real-views");
            rejected(views[0].view::start); // main thread has no current GL context
            // Global font invalidation is legal off the GL thread and must queue
            // real GPU invalidation for BOTH owners without changing borrows.
            GLText.invalidate();
            for (View view:views) {
                GLText borrowed=view.text;
                view.canvas.display(); healthy();
                check(view.text==borrowed,"Global invalidation replaced borrowed CPU text");
            }
            for(int cycle=0;cycle<3;cycle++) {
                int liveDraws=views[1].drawCount;
                String previousRenderThread=views[0].lastDisplayThread;
                GLContext previousContext=views[0].canvas.getContext();
                Thread disposal=new Thread(() -> {
                    try {
                        destroyView(views[0]);
                    } catch(Throwable error) { failure.compareAndSet(null,error); }
                },"owned-context-dispose-"+cycle);
                disposal.start(); disposal.join(30000);
                check(!disposal.isAlive(),"Moved disposal thread exceeded deadline");
                healthy();
                check(disposal.getName().equals(views[0].lastDisposeThread),"Disposal did not run on selected moved thread: requested="+
                        disposal.getName()+" actual="+views[0].lastDisposeThread+" previousRender="+previousRenderThread);
                check(!disposal.getName().equals(previousRenderThread),"Disposal thread was not distinct from rendering");
                check(!previousContext.isCreated(),"Old actual GL context survived destruction");
                // A destroyed AWT GLCanvas needs a new peer/drawable. Real AWT
                // remove/add notifications recreate it; display() alone cannot.
                EventQueue.invokeAndWait(() -> {
                    frames[0].remove(views[0].canvas);
                    frames[0].add(views[0].canvas);
                    frames[0].validate();
                });
                views[0].canvas.addGLEventListener(views[0]);
                views[0].canvas.display(); healthy();
                check(views[0].canvas.getContext()!=previousContext,"Actual GL context was not recreated");
                views[1].canvas.display(); healthy();
                check(views[0].initCount==cycle+2 && views[0].releaseCount==cycle+1,"Recreation callback order: cycle="+
                        cycle+" init="+views[0].initCount+" release="+views[0].releaseCount);
                check(views[1].initCount==1 && views[1].drawCount>liveDraws,"Other live view disrupted");
            }
            views[0].terminal=true; destroyView(views[0]); healthy();
            check(views[0].releaseCount==4,"Terminal renderer cleanup callback missing");
            check(views[0].threads.size()>=2,"Real context thread movement was not exercised");
            EventQueue.invokeAndWait(frames[0]::dispose); frames[0]=null;
            java.util.Set<Long> contextIdentities=new java.util.HashSet<>();
            contextIdentities.add(views[0].view.ctxptr); contextIdentities.add(views[1].view.ctxptr);
            for(int freshIndex=0;freshIndex<3;freshIndex++) {
                Frame[] freshFrame={null}; View[] fresh={null};
                try {
                    EventQueue.invokeAndWait(() -> {
                        GLCanvas canvas=new GLCanvas(new GLCapabilities(GLProfile.getMaxProgrammable(true)));
                        fresh[0]=new View(canvas,0.375f); canvas.addGLEventListener(fresh[0]);
                        freshFrame[0]=new Frame("Fresh context identity"); freshFrame[0].add(canvas);
                        freshFrame[0].setSize(160,120); freshFrame[0].setLocation(30,180); freshFrame[0].setVisible(true);
                    });
                    fresh[0].canvas.display(); healthy();
                    check(contextIdentities.add(fresh[0].view.ctxptr),"Retired native context address was reused");
                    rejectAllTextGpuOverloads(views[0].text);
                    rejected(() -> Shader.get(views[0].view.getRenderContext()));
                    check(views[0].shader.handle==0,"Terminal shader retained a GPU handle");
                    GLText.invalidate(); // skip old tombstones, update BOTH live B/C
                    fresh[0].canvas.display(); views[1].canvas.display(); healthy();
                    fresh[0].terminal=true; destroyView(fresh[0]); healthy();
                } finally {
                    EventQueue.invokeAndWait(() -> { if(freshFrame[0]!=null) freshFrame[0].dispose(); });
                }
            }
            views[1].terminal=true; destroyView(views[1]); healthy();
            for(int borrow=0;borrow<3;borrow++) terminalBorrowGc(borrow);
            HeadedAdmission.verifyMaps("after-all-controls",true);
            java.util.Map<Path,String> finalMaps=mappedElfs("after-all-controls");
            for(java.util.Map.Entry<Path,String> entry:firstMaps.entrySet())
                check(entry.getValue().equals(finalMaps.get(entry.getKey())),"Mapped provider disappeared or changed");
            System.out.println("headed lifecycle PASS cycles=3 live-views=2 fresh-identities=3 retained-text/shader old-workers retired");
        } finally {
            EventQueue.invokeAndWait(() -> { for(Frame frame:frames) if(frame!=null) frame.dispose(); });
        }
        healthy();
    }
}
