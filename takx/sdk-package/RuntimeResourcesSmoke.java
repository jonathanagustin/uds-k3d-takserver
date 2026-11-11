// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import android.content.Context;
import android.content.res.AssetManager;
import android.content.res.Resources;
import com.atakmap.opengl.GLSLUtil;
import com.atakmap.util.ConfigOptions;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.jar.*;

/** Genuine packaged byte consumers after stock initialization; no GL realization. */
public final class RuntimeResourcesSmoke {
  private static void check(boolean value,String message) {if(!value)throw new AssertionError(message);}
  private static String hash(byte[] bytes)throws Exception {return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}
  public static void run(Path jar,Path expected)throws Exception {
    for(Class<?> type:List.of(Context.class,Resources.class,AssetManager.class,GLSLUtil.class))
      check(Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath().equals(jar),"resource consumer origin");
    check(ConfigOptions.getOption("glslutil.additional-shader-source-paths",null)==null,"no filesystem shader override");
    Context context=new Context();check(context.getPackageName().equals("gov.tak.desktop"),"catalog owner");
    Resources resources=context.getResources();int count=0,assets=0,raw=0,drawable=0,values=0,shaders=0;
    Properties catalog=new Properties();Set<String> wantedCatalog=new TreeSet<>();Set<String> seen=new HashSet<>();
    try(JarFile archive=new JarFile(jar.toFile());InputStream input=archive.getInputStream(archive.getJarEntry(Resources.CATALOG))) {
      catalog.load(new InputStreamReader(input,StandardCharsets.UTF_8));
      for(String row:Files.readAllLines(expected,StandardCharsets.UTF_8)) {
        String[] fields=row.split(" ",3);check(fields.length==3,"expected resource record");
        String sha=fields[0],kind=fields[1],name=fields[2];check(seen.add(name),"duplicate expected resource");
        JarEntry entry=archive.getJarEntry(name);check(entry!=null,"missing genuine resource: "+name);
        byte[] bytes;try(InputStream stream=archive.getInputStream(entry)){bytes=stream.readAllBytes();}
        check(hash(bytes).equals(sha),"genuine resource hash: "+name);count++;
        if(kind.equals("asset")) {
          try(InputStream stream=context.getAssets().open(name.substring("assets/".length()))) {check(Arrays.equals(bytes,stream.readAllBytes()),"asset byte consumer");}assets++;
        } else if(kind.equals("raw")||kind.equals("drawable")) {
          String leaf=name.substring(name.lastIndexOf('/')+1),key="gov.tak.desktop/"+kind+"/"+leaf;wantedCatalog.add(key);
          check(name.equals(catalog.getProperty(key)),"exact catalog destination");
          int id=resources.getIdentifier(leaf,kind,"gov.tak.desktop");check(id>0,"catalog identity");
          check(resources.getIdentifier(leaf,kind,"other.owner")==0,"catalog owner isolation");
          boolean wrongOwnerRejected=false;try{resources.openRawResourceForPackage("other.owner",id);}catch(Resources.NotFoundException good){wrongOwnerRejected=true;}check(wrongOwnerRejected,"package raw API owner/type isolation");
          try(InputStream stream=resources.openRawResource(id)){check(Arrays.equals(bytes,stream.readAllBytes()),"catalog byte consumer");}
          if(kind.equals("raw")) {
            raw++;try(InputStream stream=resources.openRawResourceForPackage("gov.tak.desktop",id)){check(Arrays.equals(bytes,stream.readAllBytes()),"raw owner byte consumer");}
            if(leaf.startsWith("gl20fp_")) {
              check(!Files.exists(Path.of(leaf)),"no CWD shader source");
              check(GLSLUtil.loadShaderSource(leaf).equals(new String(bytes,StandardCharsets.UTF_8)),"genuine stock-context GLSL lookup");shaders++;
            }
          } else {
            drawable++;boolean rejected=false;try{resources.openRawResourceForPackage("gov.tak.desktop",id);}catch(Resources.NotFoundException good){rejected=true;}check(rejected,"drawable excluded from raw URI owner API");
          }
        } else {check(kind.equals("values"),"unsupported expected type");values++;check(resources.getIdentifier(name.substring(name.lastIndexOf('/')+1),"values","gov.tak.desktop")==0,"values remain unindexed");}
      }
      check(catalog.stringPropertyNames().equals(wantedCatalog),"exact catalog allowlist");
      Set<String> actual=new HashSet<>();for(JarEntry entry:Collections.list(archive.entries()))if(entry.getName().startsWith("resources/")||entry.getName().startsWith("assets/"))actual.add(entry.getName());
      check(actual.equals(seen),"complete resource JAR allowlist");
    }
    check(count==118&&assets==91&&raw==20&&drawable==5&&values==2&&shaders==15,"genuine complete resource counts");
    System.out.println("PASS_GENUINE_118_RESOURCES_91_ASSETS_25_CATALOG_15_STOCK_GLSL");
  }
  public static void main(String[] args)throws Exception {
    check(args.length==1,"negative-only expected JAR");
    check(Path.of(Resources.class.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath().equals(Path.of(args[0]).toRealPath()),"negative Resources origin");
    boolean rejected=false;try{new Context().getResources();}catch(Resources.NotFoundException good){rejected=true;}
    check(rejected,"catalog referencing omitted genuine shader must fail");
    System.out.println("PASS_GENUINE_MISSING_SHADER_CATALOG_REJECTION");
  }
}
