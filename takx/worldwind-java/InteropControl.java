// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.nasa.worldwind.render;

import com.jogamp.opengl.*;
import gov.nasa.worldwind.View;
import gov.nasa.worldwind.geom.*;
import gov.nasa.worldwind.layers.*;
import gov.nasa.worldwind.util.tree.*;
import java.awt.*;
import java.lang.reflect.Proxy;
import java.nio.ByteBuffer;
import java.util.*;
import java.util.List;

/** Actual project classes with explicit view/DC/GL fixtures; no native context or graphics acceptance. */
public final class InteropControl {
    static void check(boolean ok, String why) { if (!ok) throw new AssertionError(why); }
    static Object zero(Class<?> c) { if(c==boolean.class)return false;if(c==int.class)return 0;if(c==long.class)return 0L;if(c==double.class)return 0d;return null; }
    static final Rectangle VIEWPORT = new Rectangle(0,0,800,600);
    static View view() {
        return (View)Proxy.newProxyInstance(View.class.getClassLoader(),new Class[]{View.class},(p,m,a)->{
            switch(m.getName()) {
                case "getViewport":return VIEWPORT;
                case "getFieldOfView":return Angle.fromDegrees(45);
                case "getNearClipDistance":return 1d;
                case "getFarClipDistance":return 1000d;
                case "getModelviewMatrix":return Matrix.IDENTITY;
                case "getEyePoint":return Vec4.ZERO;
                case "getHorizonDistance":return Double.MAX_VALUE;
                default:return zero(m.getReturnType());
            }
        });
    }
    // Explicit inert GLContext fixture; only getGL participates in tested pixel-read dispatch.
    static final class MockContext extends GLContext {
        final GL gl;MockContext(GL gl){this.gl=gl;}
        public com.jogamp.opengl.GLDrawable setGLDrawable(com.jogamp.opengl.GLDrawable p0, boolean p1){return null;}
        public com.jogamp.opengl.GLDrawable getGLDrawable(){return null;}
        public boolean isGLReadDrawableAvailable(){return false;}
        public com.jogamp.opengl.GLDrawable setGLReadDrawable(com.jogamp.opengl.GLDrawable p0){return null;}
        public com.jogamp.opengl.GLDrawable getGLReadDrawable(){return null;}
        public int makeCurrent(){return 0;}
        public void release(){}
        public void copy(com.jogamp.opengl.GLContext p0, int p1){}
        public void destroy(){}
        public com.jogamp.opengl.GL getRootGL(){return gl;}
        public com.jogamp.opengl.GL getGL(){return gl;}
        public com.jogamp.opengl.GL setGL(com.jogamp.opengl.GL p0){return null;}
        public boolean isFunctionAvailable(java.lang.String p0){return false;}
        public boolean isExtensionAvailable(java.lang.String p0){return false;}
        public int getPlatformExtensionCount(){return 0;}
        public java.lang.String getPlatformExtensionsString(){return null;}
        public int getGLExtensionCount(){return 0;}
        public java.lang.String getGLExtensionsString(){return null;}
        public int getContextCreationFlags(){return 0;}
        public void setContextCreationFlags(int p0){}
        public int getDefaultVAO(){return 0;}
        public int getBoundFramebuffer(int p0){return 0;}
        public int getDefaultDrawFramebuffer(){return 0;}
        public int getDefaultReadFramebuffer(){return 0;}
        public int getDefaultDrawBuffer(){return 0;}
        public int getDefaultReadBuffer(){return 0;}
        public int getDefaultPixelDataType(){return 0;}
        public int getDefaultPixelDataFormat(){return 0;}
        public java.lang.String getGLDebugMessageExtension(){return null;}
        public boolean isGLDebugSynchronous(){return false;}
        public void setGLDebugSynchronous(boolean p0){}
        public boolean isGLDebugMessageEnabled(){return false;}
        public void enableGLDebugMessage(boolean p0){}
        public void addGLDebugListener(com.jogamp.opengl.GLDebugListener p0){}
        public void removeGLDebugListener(com.jogamp.opengl.GLDebugListener p0){}
        public void glDebugMessageControl(int p0, int p1, int p2, int p3, java.nio.IntBuffer p4, boolean p5){}
        public void glDebugMessageControl(int p0, int p1, int p2, int p3, int[] p4, int p5, boolean p6){}
        public void glDebugMessageInsert(int p0, int p1, int p2, int p3, java.lang.String p4){}
    }
    static class Coordinates extends DrawContextImpl {
        double sx=1,sy=1;int calls;int[] read;
        final GL gl=(GL)Proxy.newProxyInstance(GL.class.getClassLoader(),new Class[]{GL.class},(p,m,a)->{
            if(m.getName().equals("getGL2"))return p;
            if(m.getName().equals("glReadPixels")) {
                read=new int[]{(int)a[0],(int)a[1],(int)a[2],(int)a[3]};
                ByteBuffer b=(ByteBuffer)a[6];for(int i=0;i<b.capacity();i++)b.put(i,(byte)1);
            }
            return zero(m.getReturnType());
        });
        Coordinates(){setView(view());setGLContext(new MockContext(gl));}
        @Override public int[] awtPointToGLpoint(Point p){calls++;return p==null?null:new int[]{(int)Math.floor(p.x*sx+.5),(int)Math.floor(p.y*sy+.5)};}
    }
    static class Mark extends PointPlacemark {
        boolean intersects=true;int bounds;Mark(){super(Position.ZERO);setClipToHorizon(false);}
        @Override protected void computePlacemarkPoints(DrawContext dc,OrderedPlacemark opm){
            this.placePoint=opm.placePoint=new Vec4(1,2,3);this.screenPoint=opm.screenPoint=new Vec4(40,50,0);
        }
        @Override protected void determineActiveAttributes(){this.activeAttributes.setUsePointAsDefaultImage(true);}
        @Override protected void computeImageOffset(DrawContext dc){}
        @Override protected void computeImageBounds(DrawContext dc,OrderedPlacemark opm){bounds++;opm.imageBounds=new Rectangle(40,50,64,48);}
        @Override protected boolean intersectsFrustum(DrawContext dc,OrderedPlacemark opm){return intersects;}
        @Override protected boolean isDrawLine(DrawContext dc,OrderedPlacemark opm){return false;}
        void dispatch(DrawContext dc){makeOrderedRenderable(dc);}
    }
    static class Grid extends GraticuleSupport {
        int calls;Collection<GeographicText> labels;
        @Override protected void renderText(DrawContext dc,Collection<GeographicText> text){calls++;labels=new ArrayList<>(text);}
    }
    public static void main(String[] args) {
        DrawContextImpl plain=new DrawContextImpl();check(plain.awtPointToGLpoint(null)==null,"null coordinate");check(Arrays.equals(plain.awtPointToGLpoint(new Point(12,34)),new int[]{12,34}),"default identity");
        Coordinates dc=new Coordinates();
        for(double[] scale:new double[][]{{1,1},{2,2},{1.5,2}}){
            dc.sx=scale[0];dc.sy=scale[1];dc.calls=0;dc.getPickColorAtPoint(new Point(10,20));
            check(Arrays.equals(dc.read,new int[]{(int)(10*scale[0]),599-(int)(20*scale[1]),1,1}),"one pixel inversion");check(dc.calls==1,"point hook count");
            dc.calls=0;dc.getPickColorsInRectangle(new Rectangle(10,100,20,10),null);
            check(Arrays.equals(dc.read,new int[]{(int)(10*scale[0]),599-(int)(100*scale[1]),(int)(20*scale[0]),(int)(10*scale[1])}),"rectangle dimensions scaled");check(dc.calls==2,"rectangle corner hook count");
            dc.getPickFrustums().clear();dc.setPickPoint(new Point(10,20));dc.addPickPointFrustum();
            Rectangle point=dc.getPickFrustums().get(0).getScreenRect();check(point.x==(int)(10*scale[0])-1&&point.y==600-(int)(20*scale[1])-1,"point frustum matches scaled pick");
            dc.getPickFrustums().clear();dc.setPickRectangle(new Rectangle(10,100,20,10));dc.addPickRectangleFrustum();
            Rectangle rect=dc.getPickFrustums().get(0).getScreenRect();check(rect.equals(new Rectangle((int)(10*scale[0]),600-(int)(100*scale[1]),(int)(20*scale[0]),(int)(10*scale[1]))),"rectangle frustum scaled once");
        }
        List<OrderedRenderable> queue=new ArrayList<>();boolean[] picking={false};
        DrawContext fixture=(DrawContext)Proxy.newProxyInstance(DrawContext.class.getClassLoader(),new Class[]{DrawContext.class},(p,m,a)->{
            if(m.getName().equals("addOrderedRenderable")){queue.add((OrderedRenderable)a[0]);return null;}
            if(m.getName().equals("getFrameTimeStamp"))return 10L;
            if(m.getName().equals("getSurfaceGeometry"))return new gov.nasa.worldwind.terrain.SectorGeometryList();
            if(m.getName().equals("isPickingMode"))return picking[0];
            if(m.getName().equals("getView"))return view();
            return zero(m.getReturnType());
        });
        Mark mark=new Mark();mark.render(fixture);check(queue.size()==1,"unset hook queues normally");queue.clear();
        int[] callbacks={0};Thread caller=Thread.currentThread();
        try {
            PointPlacemark.makeOrderedRenderableFactory=(p,d)->{callbacks[0]++;check(Thread.currentThread()==caller,"synchronous render thread");check(((PointPlacemark.OrderedPlacemark)p.getValue(PointPlacemark.OrderedPlacemark.class.getName())).getImageBounds().equals(new Rectangle(40,50,64,48)),"computed image bounds published");};
            mark.render(fixture);picking[0]=true;mark.render(fixture);check(callbacks[0]==2&&queue.isEmpty(),"exclusive hook in normal and pick calls");
            mark.setVisible(false);mark.render(fixture);check(callbacks[0]==2,"visibility gate");mark.setVisible(true);
            mark.intersects=false;mark.render(fixture);check(callbacks[0]==2,"frustum gate");
        } finally {PointPlacemark.makeOrderedRenderableFactory=null;}
        Grid grid=new Grid();GeographicText text=new UserFacingText("grid",Position.ZERO);
        GraticuleRenderingParams shown=new GraticuleRenderingParams();shown.setDrawLabels(true);shown.setLabelColor(new Color(20,40,60,200));shown.setLabelFont(new Font("Dialog",Font.BOLD,14));
        GraticuleRenderingParams hidden=new GraticuleRenderingParams();hidden.setDrawLabels(false);grid.setRenderingParams("shown",shown);grid.setRenderingParams("hidden",hidden);
        grid.addRenderable(text,"shown");grid.addRenderable(new UserFacingText("hidden",Position.ZERO),"hidden");grid.render(fixture,.5);
        check(grid.calls==1&&grid.labels.size()==1&&grid.labels.contains(text),"real graticule label selection dispatch");
        check(text.getColor().getAlpha()==100&&text.getFont().equals(shown.getLabelFont()),"font/color/opacity applied before hook");
        BasicTreeLayout layout=new BasicTreeLayout(new BasicTree());layout.setScreenLocation(new Point(20,45));
        for(int height:new int[]{600,900}) {java.awt.geom.Point2D offset=layout.getScreenLocation().computeOffset(800,height,1d,1d);check(offset.getX()==20&&offset.getY()==height-45,"upper-left inset survives resize");}
        System.out.println("PASS_REAL_WORLDWIND_INTEROP_DISPATCH_COORDINATES_LAYOUT_WITH_MOCK_DC_GL");
    }
}
