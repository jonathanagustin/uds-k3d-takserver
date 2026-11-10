// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database;
/** Real positioning and lifecycle shared by materialized desktop cursors. */
public abstract class AbstractCursor implements Cursor {
    protected int mPos=-1;
    private boolean closed;
    protected final void checkOpen(){
        if(closed)throw new IllegalStateException("cursor closed");
    }
    protected final void checkPosition(){
        checkOpen();
        if(mPos<0||mPos>=getCount())throw new IndexOutOfBoundsException("cursor position "+mPos);
    }
    public boolean onMove(int oldPosition,int newPosition){
        return true;
    }
    @Override public final boolean moveToPosition(int position){
        checkOpen();
        int count=getCount();
        if(position>=count){
            mPos=count;
            return false;
        }
        if(position<0){
            mPos=-1;
            return false;
        }
        if(position==mPos)return true;
        boolean moved=onMove(mPos,position);
        mPos=moved?position:-1;
        return moved;
    }
    @Override public int getPosition(){
        checkOpen();
        return mPos;
    }
    @Override public boolean move(int offset){
        return moveToPosition(mPos+offset);
    }
    @Override public boolean moveToFirst(){
        return moveToPosition(0);
    }
    @Override public boolean moveToLast(){
        return moveToPosition(getCount()-1);
    }
    @Override public boolean moveToNext(){
        return moveToPosition(mPos+1);
    }
    @Override public boolean moveToPrevious(){
        return moveToPosition(mPos-1);
    }
    @Override public boolean isFirst(){
        return mPos==0&&getCount()!=0;
    }
    @Override public boolean isLast(){
        return mPos==getCount()-1&&getCount()!=0;
    }
    @Override public boolean isBeforeFirst(){
        return getCount()==0||mPos==-1;
    }
    @Override public boolean isAfterLast(){
        return getCount()==0||mPos==getCount();
    }
    @Override public int getColumnCount(){
        return getColumnNames().length;
    }
    @Override public String getColumnName(int column){
        return getColumnNames()[column];
    }
    @Override public int getColumnIndex(String name){
        String[] names=getColumnNames();
        int dot=name.lastIndexOf('.');
        if(dot>=0)name=name.substring(dot+1);
        for(int i=0;i<names.length;i++)if(names[i].equalsIgnoreCase(name))return i;
        return -1;
    }
    @Override public int getColumnIndexOrThrow(String name){
        int column=getColumnIndex(name);
        if(column<0)throw new IllegalArgumentException("unknown column "+name);
        return column;
    }
    @Override public short getShort(int column){
        return (short)getLong(column);
    }
    @Override public int getInt(int column){
        return (int)getLong(column);
    }
    @Override public float getFloat(int column){
        return (float)getDouble(column);
    }
    @Override public boolean isNull(int column){
        return getType(column)==FIELD_TYPE_NULL;
    }
    @Override public boolean isClosed(){
        return closed;
    }
    @Override public void close(){
        closed=true;
        mPos=-1;
    }
}
