// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.database;
import java.util.ArrayList;
import java.util.List;
/** Actual bounded typed row window. The explicit 16MiB limit fails closed. */
public final class CursorWindow implements AutoCloseable {
    private final List<Object[]> rows=new ArrayList<>();
    private int columns,start;
    private long bytes;
    private boolean closed;
    private static final long LIMIT=16L*1024*1024;
    public CursorWindow(boolean localWindow){
    }
    public CursorWindow(String name){
    }
    private void open(){
        if(closed)throw new IllegalStateException("window closed");
    }
    public boolean setNumColumns(int count){
        open();
        if(count<0)throw new IllegalArgumentException("negative columns");
        if(!rows.isEmpty()&&count!=columns)return false;
        columns=count;
        return true;
    }
    public void clear(){
        open();
        rows.clear();
        bytes=0;
        start=0;
    }
    public void setStartPosition(int position){
        open();
        if(position<0)throw new IllegalArgumentException("negative start");
        start=position;
    }
    public int getStartPosition(){
        open();
        return start;
    }
    public int getNumRows(){
        open();
        return rows.size();
    }
    public boolean allocRow(){
        open();
        long extra=16L+8L*columns;
        if(bytes+extra>LIMIT)throw new android.database.sqlite.SQLiteException("desktop cursor window exceeds 16MiB");
        rows.add(new Object[columns]);
        bytes+=extra;
        return true;
    }
    private Object[] row(int index,int column){
        open();
        if(column<0||column>=columns)throw new IndexOutOfBoundsException("column");
        return rows.get(index-start);
    }
    private static long size(Object value){
        return value instanceof byte[]?((byte[])value).length:value instanceof String?2L*((String)value).length():8;
    }
    private boolean put(Object value,int row,int column){
        Object[] values=row(row,column);
        long updated=bytes-size(values[column])+size(value);
        if(updated>LIMIT)throw new android.database.sqlite.SQLiteException("desktop cursor window exceeds 16MiB");
        values[column]=value instanceof byte[]?((byte[])value).clone():value;
        bytes=updated;
        return true;
    }
    public boolean putNull(int row,int column){
        return put(null,row,column);
    }
    public boolean putLong(long value,int row,int column){
        return put(value,row,column);
    }
    public boolean putDouble(double value,int row,int column){
        return put(value,row,column);
    }
    public boolean putString(String value,int row,int column){
        return put(value,row,column);
    }
    public boolean putBlob(byte[] value,int row,int column){
        return put(value,row,column);
    }
    private Object value(int row,int column){
        return row(row,column)[column];
    }
    public int getType(int row,int column){
        Object v=value(row,column);
        return v==null?Cursor.FIELD_TYPE_NULL:v instanceof byte[]?Cursor.FIELD_TYPE_BLOB:v instanceof Float||v instanceof Double?Cursor.FIELD_TYPE_FLOAT:v instanceof Number||v instanceof Boolean?Cursor.FIELD_TYPE_INTEGER:Cursor.FIELD_TYPE_STRING;
    }
    public String getString(int row,int column){
        Object v=value(row,column);
        if(v instanceof byte[])throw new android.database.sqlite.SQLiteException("cannot convert BLOB to string");
        if(v==null)return null;
        if(v instanceof Double||v instanceof Float){
            double number=((Number)v).doubleValue();
            if(Double.isNaN(number))return "nan";
            if(Double.isInfinite(number))return number<0?"-inf":"inf";
            String formatted=String.format(java.util.Locale.ROOT,"%.6g",number);
            int exponent=formatted.indexOf('e');
            String suffix=exponent<0?"":formatted.substring(exponent);
            String base=exponent<0?formatted:formatted.substring(0,exponent);
            if(base.indexOf('.')>=0)base=base.replaceFirst("0+$", "").replaceFirst("\\.$", "");
            return base+suffix;
        }
        return v.toString();
    }
    public byte[] getBlob(int row,int column){
        Object v=value(row,column);
        if(v==null)return null;
        if(v instanceof String)return (((String)v)+"\0").getBytes(java.nio.charset.StandardCharsets.UTF_8);
        if(!(v instanceof byte[]))throw new android.database.sqlite.SQLiteException("value is not BLOB");
        return ((byte[])v).clone();
    }
    public long getLong(int row,int column){
        Object v=value(row,column);
        if(v==null)return 0;
        if(v instanceof Number)return ((Number)v).longValue();
        if(v instanceof byte[])throw new android.database.sqlite.SQLiteException("cannot convert BLOB to long");
        java.util.regex.Matcher match=java.util.regex.Pattern.compile("^\\s*([+-]?)(?:(0[xX][0-9a-fA-F]+)|(0[0-7]*)|([1-9][0-9]*))").matcher(v.toString());
        if(!match.find())return 0;
        int radix=match.group(2)!=null?16:match.group(3)!=null?8:10;
        String digits=radix==16?match.group(2).substring(2):radix==8?match.group(3):match.group(4);
        java.math.BigInteger integer=new java.math.BigInteger(match.group(1)+digits,radix);
        return integer.max(java.math.BigInteger.valueOf(Long.MIN_VALUE)).min(java.math.BigInteger.valueOf(Long.MAX_VALUE)).longValue();
    }
    public double getDouble(int row,int column){
        Object v=value(row,column);
        if(v==null)return 0;
        if(v instanceof Number)return ((Number)v).doubleValue();
        if(v instanceof byte[])throw new android.database.sqlite.SQLiteException("cannot convert BLOB to double");
        String text=v.toString().replaceFirst("^\\s+", "");
        String lower=text.toLowerCase(java.util.Locale.ROOT);
        if(lower.matches("^[+-]?inf(?:inity)?.*"))return lower.startsWith("-")?Double.NEGATIVE_INFINITY:Double.POSITIVE_INFINITY;
        if(lower.matches("^[+-]?nan.*"))return Double.NaN;
        java.util.regex.Matcher hex=java.util.regex.Pattern.compile("^[+-]?0[xX](?:[0-9a-fA-F]+(?:\\.[0-9a-fA-F]*)?|\\.[0-9a-fA-F]+)(?:[pP][+-]?\\d+)?").matcher(text);
        if(hex.find()){
            String number=hex.group();
            if(number.indexOf('p')<0&&number.indexOf('P')<0)number+="p0";
            return Double.parseDouble(number);
        }
        java.util.regex.Matcher match=java.util.regex.Pattern.compile("^[+-]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][+-]?\\d+)?").matcher(text);
        return match.find()?Double.parseDouble(match.group()):0;
    }
    @Override public void close(){
        closed=true;
        rows.clear();
        bytes=0;
    }
}
