// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package com.atakmap.map.opengl;
import java.nio.file.*;
import java.util.*;

/** Proposed strict test admission; not compiled or executed. */
final class HeadedAdmission {
    static Map<Path,String> hashes(String property) throws Exception {
        Map<Path,String> result=new TreeMap<>();
        for(String line:Files.readAllLines(Path.of(System.getProperty(property)))) {
            if(line.isBlank()||line.startsWith("#"))continue;
            String[] f=line.split(" ",2);
            ContextRecreationProbe.check(f.length==2&&f[0].matches("[0-9a-f]{64}"),"Invalid hash manifest");
            Path p=Path.of(f[1]);
            ContextRecreationProbe.check(p.isAbsolute()&&!Files.isSymbolicLink(p)&&Files.isRegularFile(p),"Regular pinned provider required");
            p=p.toRealPath();ContextRecreationProbe.check(result.put(p,f[0])==null,"Duplicate provider");
            ContextRecreationProbe.check(ContextRecreationProbe.sha256(p).equals(f[0]),"Provider hash drift: "+p);
        }
        ContextRecreationProbe.check(!result.isEmpty(),"Empty provider manifest");return result;
    }
    static void checkOrigins() throws Exception {
        for(String line:Files.readAllLines(Path.of(System.getProperty("context.probe.origins")))) {
            String[] f=line.split("\t");
            Class<?> type=Class.forName(f[0],false,HeadedAdmission.class.getClassLoader());
            Path origin=Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath();
            ContextRecreationProbe.check(origin.equals(Path.of(f[1]).toRealPath()),"Wrong headed class origin: "+f[0]);
            System.out.println("ADMITTED_CLASS_ORIGIN\t"+f[0]+"\t"+origin);
        }
    }
    static void verifyMaps(String phase,boolean requireProviders) throws Exception {
        Map<Path,String> allowed=hashes("context.probe.allowedElfs"), providers=hashes("context.probe.providers");
        Map<Path,String> mapped=ContextRecreationProbe.mappedElfs("admission-"+phase);
        for(Map.Entry<Path,String> entry:mapped.entrySet()) {
            Path p=entry.getKey();String name=p.getFileName().toString();
            ContextRecreationProbe.check(entry.getValue().equals(allowed.get(p)),"Unapproved mapped ELF: "+p);
            ContextRecreationProbe.check(!name.startsWith("libcrypto.so")&&!name.startsWith("libssl.so")&&!name.startsWith("libsqlite3.so"),"Forbidden shared backend: "+p);
            if(name.startsWith("libtakengine")||name.startsWith("libGLESv2.so")||name.startsWith("libGLdispatch.so"))
                ContextRecreationProbe.check(providers.containsKey(p),"Wrong Core/JNI/GLES/dispatch identity: "+p);
        }
        if(requireProviders)for(Map.Entry<Path,String> entry:providers.entrySet())
            ContextRecreationProbe.check(entry.getValue().equals(mapped.get(entry.getKey())),"Missing exact requested headed provider: "+entry.getKey());
    }
}
