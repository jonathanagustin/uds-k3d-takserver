// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.geom.AffineTransform;
import java.awt.geom.Point2D;
import java.awt.image.BufferedImage;
import java.util.Arrays;
import java.util.Random;

public final class MatrixCompatibilityTest {
    private static int checks;
    private static void check(boolean condition) {
        checks++; if (!condition) throw new AssertionError("Matrix check " + checks);
    }
    private static void close(double actual,double expected) { check(Math.abs(actual-expected)<0.002); }
    private static float[] values(Matrix matrix) {
        float[] result=new float[9]; matrix.getValues(result); return result;
    }
    private static void vector(Matrix matrix,float... expected) { check(Arrays.equals(values(matrix),expected)); }
    private static void fails(Class<? extends Throwable> type,Runnable run) {
        try { run.run(); } catch(Throwable failure) { check(type.isInstance(failure)); return; }
        throw new AssertionError("expected "+type.getName());
    }
    private static void sourceVectors() {
        Matrix matrix=new Matrix(); check(matrix.isIdentity());
        // Exact numeric vectors from AOSP CTS MatrixTest testSetScale/testSetScale2.
        matrix.setScale(1,2); vector(matrix,1,0,0,0,2,0,0,0,1);
        matrix.setScale(1,2,3,4); vector(matrix,1,0,0,0,2,-4,0,0,1);
        matrix.reset(); matrix.postTranslate(1,2); vector(matrix,1,0,1,0,1,2,0,0,1);
        matrix.setScale(2,3); matrix.preTranslate(5,7); vector(matrix,2,0,10,0,3,21,0,0,1);
        matrix.setScale(2,3); matrix.postTranslate(5,7); vector(matrix,2,0,5,0,3,7,0,0,1);
        Matrix copy=new Matrix(matrix); matrix.reset(); check(!copy.isIdentity());
        copy.set(null); check(copy.isIdentity()); check(new Matrix(null).isIdentity());
        float[] returned=values(matrix); returned[0]=99; check(matrix.isIdentity());
        matrix.setScale(1,-1); float[] points={0,0,2,3}; matrix.mapPoints(points);
        check(Arrays.equals(points,new float[]{0,0,2,-3}));
        RectF rectangle=new RectF(0,0,2,3); check(matrix.mapRect(rectangle));
        close(rectangle.left,0);close(rectangle.top,-3);close(rectangle.right,2);close(rectangle.bottom,0);
        float[] overlap={1,2,3,4,5,6}; matrix.mapPoints(overlap,2,overlap,0,2);
        check(Arrays.equals(overlap,new float[]{1,2,1,-2,3,-4}));
        float[] odd={1,2,77}; matrix.mapPoints(odd); check(odd[2]==77);
        Matrix destination=new Matrix(); destination.setTranslate(4,5);
        matrix.setScale(0,1); check(!matrix.invert(destination)); vector(destination,1,0,4,0,1,5,0,0,1);
        matrix.setValues(new float[]{0,-1,0,1,0,0,0,0,1}); check(matrix.rectStaysRect());
        matrix.setValues(new float[]{1,1,0,0,1,0,0,0,1}); check(!matrix.mapRect(new RectF(0,0,1,1)));
        fails(ArrayIndexOutOfBoundsException.class,()->matrix.mapPoints(new float[2],0,new float[2],0,Integer.MAX_VALUE));
        fails(ArrayIndexOutOfBoundsException.class,()->matrix.getValues(new float[8]));
        fails(IllegalArgumentException.class,()->matrix.mapPoints(new float[2],new float[4]));
        fails(NullPointerException.class,()->matrix.invert(null));
        float[] before=values(matrix);
        fails(UnsupportedOperationException.class,()->matrix.setValues(new float[]{1,0,0,0,1,0,0.1f,0,1}));
        check(Arrays.equals(before,values(matrix)));
        fails(UnsupportedOperationException.class,()->matrix.setScale(Float.NaN,1));
        check(Arrays.equals(before,values(matrix)));
    }
    private static void independentMath() throws Exception {
        Random random=new Random(62101);
        for(int i=0;i<200;i++) {
            float a=random.nextFloat()*4+1,b=random.nextFloat(),c=random.nextFloat()*10;
            float d=random.nextFloat(),e=random.nextFloat()*4+1,f=random.nextFloat()*10;
            Matrix matrix=new Matrix(); matrix.setValues(new float[]{a,b,c,d,e,f,0,0,1});
            AffineTransform oracle=new AffineTransform(a,d,b,e,c,f);
            float[] point={random.nextFloat()*10,random.nextFloat()*10};
            Point2D expected=oracle.transform(new Point2D.Float(point[0],point[1]),null);
            float[] mapped=point.clone(); matrix.mapPoints(mapped);
            close(mapped[0],expected.getX()); close(mapped[1],expected.getY());
            Matrix inverse=new Matrix(); check(matrix.invert(inverse)); inverse.mapPoints(mapped);
            close(mapped[0],point[0]);close(mapped[1],point[1]);
            check(matrix.invert(matrix));
            AffineTransform expectedInverse=oracle.createInverse();
            double[] actual=new double[6];matrix.toAffineTransform().getMatrix(actual);
            double[] reference=new double[6];expectedInverse.getMatrix(reference);
            for(int j=0;j<6;j++) close(actual[j],reference[j]);
            matrix.setScale(2,3); matrix.preScale(4,5,1,2); vector(matrix,8,0,-6,0,15,-24,0,0,1);
            matrix.setScale(2,3); matrix.postScale(4,5,1,2); vector(matrix,8,0,-3,0,15,-8,0,0,1);
        }
    }
    private static void realPixels() {
        BufferedImage source=new BufferedImage(2,3,BufferedImage.TYPE_INT_ARGB);
        for(int y=0;y<3;y++) for(int x=0;x<2;x++) source.setRGB(x,y,0xff000000|((y*2+x+1)*0x112233));
        Matrix flip=new Matrix(); flip.reset(); flip.setScale(1,-1);
        BufferedImage target=new BufferedImage(2,3,BufferedImage.TYPE_INT_ARGB);
        Graphics2D graphics=target.createGraphics();
        graphics.translate(0,3);graphics.transform(flip.toAffineTransform());graphics.drawImage(source,0,0,null);graphics.dispose();
        for(int y=0;y<3;y++) for(int x=0;x<2;x++) check(target.getRGB(x,y)==source.getRGB(x,2-y));
        Matrix scale=new Matrix();scale.setScale(2,2);
        target=new BufferedImage(4,6,BufferedImage.TYPE_INT_ARGB);graphics=target.createGraphics();
        graphics.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_NEAREST_NEIGHBOR);
        graphics.transform(scale.toAffineTransform());graphics.drawImage(source,0,0,null);graphics.dispose();
        for(int y=0;y<6;y++) for(int x=0;x<4;x++) check(target.getRGB(x,y)==source.getRGB(x/2,y/2));
        AffineTransform bridge=scale.toAffineTransform();bridge.setToIdentity();check(!scale.isIdentity());
    }
    public static void main(String[] args) throws Exception {
        sourceVectors();independentMath();realPixels();
        System.out.println("PASS finite affine Matrix and real transformed pixels: "+checks+" checks");
    }
}
