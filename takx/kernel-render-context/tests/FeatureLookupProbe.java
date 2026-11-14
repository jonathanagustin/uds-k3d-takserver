// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Owned source-contract/typed JNI CPU control; no renderer qualification.
import java.nio.file.*;
public final class FeatureLookupProbe {
    static native void lookup(String type,String name,String descriptor,int kind);
    static native long[] marshalOptions(com.atakmap.map.layer.feature.FeatureLayer3.Options options);
    static native com.atakmap.map.layer.feature.geometry.Envelope envelope();
    public static void main(String[] args) throws Exception {
        for(int i=1;i<args.length;i++) System.load(args[i]);
        int checked=0,bad=0;
        for(String line:Files.readAllLines(Path.of(args[0]))) {
            String[] parts=line.split("\t",-1);
            try {lookup(parts[0],parts[1],parts[2],Integer.parseInt(parts[3]));}
            catch(LinkageError error) {bad++;System.out.println("LOOKUP_FAILED "+line);error.printStackTrace();}
            checked++;
        }
        System.out.println("LOOKUP_RESULT checked="+checked+" bad="+bad);
        if(bad!=0) throw new AssertionError("Source member lookups failed");
        var options = new com.atakmap.map.layer.feature.FeatureLayer3.Options();
        long[] normal=marshalOptions(options);
        if(normal[0]!=1 || normal[1]!=options.labelHints || normal[1]!=normal[3] || normal[2]!=0) throw new AssertionError("Default native options differ");
        options.labelsEnabled=false;
        options.labelHints |= com.atakmap.map.opengl.GLLabelManager.HINT_XRAY;
        options.filter=new com.atakmap.map.layer.feature.FeatureDataStore2.FeatureQueryParameters();
        options.filter.ids=java.util.Set.of(123L);
        long[] changed=marshalOptions(options);
        if(changed[0]!=0 || changed[1]!=options.labelHints || changed[2]!=1) throw new AssertionError("Requested options differ");
        var bounds=envelope();
        if(bounds.minX!=1 || bounds.minY!=2 || bounds.minZ!=3 || bounds.maxX!=4 || bounds.maxY!=5 || bounds.maxZ!=6)
            throw new AssertionError("Envelope marshal differs");
        try {marshalOptions(null);throw new AssertionError("Null options accepted");} catch(IllegalArgumentException expected) {}
        System.out.println("TYPED_OPTIONS_ENVELOPE_COMPLETED defaults/filter/label-flags/null-refusal");
    }
}
