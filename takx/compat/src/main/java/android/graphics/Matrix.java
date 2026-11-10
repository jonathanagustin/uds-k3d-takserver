// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

import java.awt.geom.AffineTransform;
import java.util.Objects;

/** Finite 2D affine subset with Android row-major/pre/post conventions. */
public class Matrix {
    public static final int MSCALE_X=0, MSKEW_X=1, MTRANS_X=2,
        MSKEW_Y=3, MSCALE_Y=4, MTRANS_Y=5, MPERSP_0=6, MPERSP_1=7, MPERSP_2=8;
    private final float[] values = new float[9];

    public Matrix() { reset(); }
    public Matrix(Matrix source) { set(source); }
    public void reset() { setScale(1, 1); }
    public void set(Matrix source) {
        if (source == null) reset();
        else System.arraycopy(source.values, 0, values, 0, 9);
    }
    public boolean isIdentity() {
        for (int i=0; i<9; i++) if (values[i] != (i==0 || i==4 || i==8 ? 1 : 0)) return false;
        return true;
    }
    public boolean isAffine() { return true; } // Invariant enforced at every mutation.
    public boolean rectStaysRect() {
        return (values[1]==0 && values[3]==0) || (values[0]==0 && values[4]==0);
    }
    public void getValues(float[] destination) {
        if (destination.length < 9) throw new ArrayIndexOutOfBoundsException("nine values required");
        System.arraycopy(values, 0, destination, 0, 9);
    }
    public void setValues(float[] source) {
        if (source.length < 9) throw new ArrayIndexOutOfBoundsException("nine values required");
        for (int i=0; i<9; i++) if (!Float.isFinite(source[i]))
            throw new UnsupportedOperationException("non-finite Matrix is unsupported");
        if (source[6]!=0 || source[7]!=0 || source[8]!=1)
            throw new UnsupportedOperationException("perspective Matrix is unsupported");
        System.arraycopy(source, 0, values, 0, 9);
    }
    public void setScale(float sx, float sy) { setScale(sx, sy, 0, 0); }
    public void setScale(float sx, float sy, float px, float py) {
        setValues(new float[] {sx,0,px-sx*px, 0,sy,py-sy*py, 0,0,1});
    }
    public void setTranslate(float dx, float dy) {
        setValues(new float[] {1,0,dx, 0,1,dy, 0,0,1});
    }
    public boolean setConcat(Matrix a, Matrix b) {
        float[] result = new float[9];
        for (int row=0; row<3; row++) for (int column=0; column<3; column++) {
            double sum=0;
            for (int k=0; k<3; k++) sum += (double)a.values[row*3+k]*b.values[k*3+column];
            result[row*3+column]=(float)sum;
        }
        setValues(result);
        return true;
    }
    /** Android pre-concat: M' = M * other. */
    public boolean preConcat(Matrix other) { return setConcat(this, other); }
    /** Android post-concat: M' = other * M. */
    public boolean postConcat(Matrix other) { return setConcat(other, this); }
    public boolean preTranslate(float dx, float dy) {
        Matrix translation=new Matrix(); translation.setTranslate(dx,dy); return preConcat(translation);
    }
    public boolean postTranslate(float dx, float dy) {
        Matrix translation=new Matrix(); translation.setTranslate(dx,dy); return postConcat(translation);
    }
    public boolean preScale(float sx, float sy) { return preScale(sx,sy,0,0); }
    public boolean preScale(float sx, float sy, float px, float py) {
        Matrix scale=new Matrix(); scale.setScale(sx,sy,px,py); return preConcat(scale);
    }
    public boolean postScale(float sx, float sy) { return postScale(sx,sy,0,0); }
    public boolean postScale(float sx, float sy, float px, float py) {
        Matrix scale=new Matrix(); scale.setScale(sx,sy,px,py); return postConcat(scale);
    }
    public boolean invert(Matrix inverse) {
        Objects.requireNonNull(inverse);
        double a=values[0], b=values[1], c=values[2], d=values[3], e=values[4], f=values[5];
        double determinant=a*e-b*d;
        if (determinant==0) return false;
        float[] result={(float)(e/determinant),(float)(-b/determinant),(float)((b*f-e*c)/determinant),
                        (float)(-d/determinant),(float)(a/determinant),(float)((d*c-a*f)/determinant),0,0,1};
        for (float value:result) if (!Float.isFinite(value)) return false;
        inverse.setValues(result);
        return true;
    }
    public void mapPoints(float[] points) { mapPoints(points,0,points,0,points.length/2); }
    public void mapPoints(float[] destination, float[] source) {
        if (destination.length != source.length) throw new IllegalArgumentException("point array sizes differ");
        mapPoints(destination,0,source,0,source.length/2);
    }
    public void mapPoints(float[] destination, int destinationIndex, float[] source, int sourceIndex, int count) {
        Objects.requireNonNull(destination); Objects.requireNonNull(source);
        if (count<0 || sourceIndex<0 || destinationIndex<0 ||
            (long)sourceIndex+2L*count>source.length || (long)destinationIndex+2L*count>destination.length)
            throw new ArrayIndexOutOfBoundsException("point range");
        float[] input=new float[count*2];
        System.arraycopy(source,sourceIndex,input,0,input.length);
        for (int i=0;i<count;i++) {
            float x=input[2*i], y=input[2*i+1];
            destination[destinationIndex+2*i]=values[0]*x+values[1]*y+values[2];
            destination[destinationIndex+2*i+1]=values[3]*x+values[4]*y+values[5];
        }
    }
    public boolean mapRect(RectF rectangle) { return mapRect(rectangle,rectangle); }
    public boolean mapRect(RectF destination, RectF source) {
        float[] corners={source.left,source.top,source.right,source.top,source.right,source.bottom,source.left,source.bottom};
        mapPoints(corners);
        float left=corners[0], right=left, top=corners[1], bottom=top;
        for (int i=2;i<8;i+=2) {
            left=Math.min(left,corners[i]); right=Math.max(right,corners[i]);
            top=Math.min(top,corners[i+1]); bottom=Math.max(bottom,corners[i+1]);
        }
        destination.set(left,top,right,bottom);
        return rectStaysRect();
    }
    /** Independent Java2D transform; perspective is rejected by setValues. */
    AffineTransform toAffineTransform() {
        return new AffineTransform(values[0],values[3],values[1],values[4],values[2],values[5]);
    }
}
