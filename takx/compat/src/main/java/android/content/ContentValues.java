// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.content;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
/** Actual typed value storage; no Android Parcel contract. */
public final class ContentValues {
    private final Map<String,Object> values;
    public ContentValues() {
        values=new HashMap<>();
    }
    public ContentValues(int size) {
        values=new HashMap<>(size);
    }
    public ContentValues(ContentValues source) {
        values=new HashMap<>(source.values);
    }
    public void put(String key,String value){
        values.put(key,value);
    }
    public void put(String key,Byte value){
        values.put(key,value);
    }
    public void put(String key,Short value){
        values.put(key,value);
    }
    public void put(String key,Integer value){
        values.put(key,value);
    }
    public void put(String key,Long value){
        values.put(key,value);
    }
    public void put(String key,Float value){
        values.put(key,value);
    }
    public void put(String key,Double value){
        values.put(key,value);
    }
    public void put(String key,Boolean value){
        values.put(key,value);
    }
    public void put(String key,byte[] value){
        values.put(key,value);
    }
    public void putNull(String key){
        values.put(key,null);
    }
    public Object get(String key){
        return values.get(key);
    }
    public int size(){
        return values.size();
    }
    public Set<String> keySet(){
        return values.keySet();
    }
    public Set<Map.Entry<String,Object>> valueSet(){
        return values.entrySet();
    }
    public void remove(String key){
        values.remove(key);
    }
    public void clear(){
        values.clear();
    }
    public boolean containsKey(String key){
        return values.containsKey(key);
    }
    public void putAll(ContentValues other){
        values.putAll(other.values);
    }
    public String getAsString(String key){
        Object value=get(key);
        return value==null?null:value.toString();
    }
    public byte[] getAsByteArray(String key){
        Object value=get(key);
        return value instanceof byte[]?(byte[])value:null;
    }
    @Override public boolean equals(Object other){
        return other instanceof ContentValues && values.equals(((ContentValues)other).values);
    }
    @Override public int hashCode(){
        return values.hashCode();
    }
}
