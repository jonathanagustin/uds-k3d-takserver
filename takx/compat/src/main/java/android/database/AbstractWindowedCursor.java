// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database;
public abstract class AbstractWindowedCursor extends AbstractCursor {
    protected CursorWindow mWindow;
    public void setWindow(CursorWindow window){
        if(mWindow!=null&&mWindow!=window)mWindow.close();
        mWindow=window;
    }
    public CursorWindow getWindow(){
        return mWindow;
    }
    @Override public byte[] getBlob(int c){
        checkPosition();
        return mWindow.getBlob(mPos,c);
    }
    @Override public String getString(int c){
        checkPosition();
        return mWindow.getString(mPos,c);
    }
    @Override public long getLong(int c){
        checkPosition();
        return mWindow.getLong(mPos,c);
    }
    @Override public double getDouble(int c){
        checkPosition();
        return mWindow.getDouble(mPos,c);
    }
    @Override public int getType(int c){
        checkPosition();
        return mWindow.getType(mPos,c);
    }
    @Override public void close(){
        super.close();
        if(mWindow!=null){
            mWindow.close();
            mWindow=null;
        }
    }
}
