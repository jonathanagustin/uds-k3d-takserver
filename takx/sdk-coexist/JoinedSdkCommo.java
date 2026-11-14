// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.commoncommo.Commo;
import java.io.InputStream;
import java.nio.file.*;
import java.util.*;

/** Owned control orchestrator; production SDK and Commo classes stay in their JARs. */
public final class JoinedSdkCommo {
  static void check(boolean value,String message) {if(!value)throw new AssertionError(message);}
  static Set<Path> maps() throws Exception {
    Set<Path> result=new TreeSet<>();
    for(String line:Files.readAllLines(Path.of("/proc/self/maps"))) {
      String[] fields=line.trim().split("\\s+",6);
      if(fields.length!=6||!fields[5].startsWith("/"))continue;
      Path file=Path.of(fields[5]);
      if(!Files.isRegularFile(file))continue;
      try(InputStream input=Files.newInputStream(file)) {
        if(Arrays.equals(input.readNBytes(4),new byte[]{127,69,76,70}))result.add(file.toRealPath());
      }
    }
    return result;
  }
  static void group(Set<Path> actual,Set<String> core,boolean coreExpected,boolean commonExpected)throws Exception {
    Set<String> names=new HashSet<>();for(Path path:actual)names.add(path.getFileName().toString());
    if(coreExpected)check(names.containsAll(core),"complete stock SDK group absent");
    else for(String name:core)check(!names.contains(name),"SDK loaded before selected order");
    check(names.contains("libcommoncommojni.so")==commonExpected,"CommonCommo load order differs");
  }
  public static void main(String[] args)throws Exception {
    check(args.length==5&&(args[0].equals("sdk-first")||args[0].equals("common-first")),"explicit order and proof files required");
    Set<String> core=new HashSet<>();
    for(String line:Files.readAllLines(Path.of(args[3])))core.add(line.split(" ",2)[1]);
    check(core.size()==9,"exact nine SDK native resources required");
    group(maps(),core,false,false);
    if(args[0].equals("sdk-first")) {
      KernelRuntimeSmoke.initializeStrict();group(maps(),core,true,false);
      System.out.println("PASS_JOINED_FIRST_GROUP_SDK");
      Class.forName("com.atakmap.commoncommo.Commo");
    } else {
      Class.forName("com.atakmap.commoncommo.Commo");group(maps(),core,false,true);
      System.out.println("PASS_JOINED_FIRST_GROUP_COMMONCOMMO");
      KernelRuntimeSmoke.initializeStrict();
    }
    group(maps(),core,true,true);
    check(Path.of(Commo.class.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath().equals(Path.of(args[2]).toRealPath()),"Commo must originate in verified producer JAR");
    StockLoaderSmoke.main(new String[]{args[1],"database",args[3],args[4]});
    CommonCommoSmoke.main(new String[0]);
    CommonCommoSignalSmoke.main(new String[0]);
    CommonCommoRoutingSmoke.main(new String[0]);
    CommonCommoThrowingLogger.main(new String[0]);
    System.out.println("PASS_JOINED_COMMON_CONSTRUCTOR_PKCS12_SIGNAL_ROUTING_LOGGER");
    KernelRuntimeSmoke.basic();
    NativeDatabaseCandidate.run(Path.of(System.getProperty("TAK_APP_DATA_PATH")));
    KernelThrowingLoggerCandidate.run(Path.of(System.getProperty("TAK_APP_DATA_PATH")));
    RuntimeResourcesSmoke.run(Path.of(args[1]),Path.of(args[4]));
    System.out.println("PASS_JOINED_KERNEL_CONTROLS_AFTER_COMMON");
    group(maps(),core,true,true);
    for(Path path:maps())System.out.println("JOINED_ELF "+KernelRuntimeSmoke.hash(path)+" "+path);
    System.out.println("PASS_JOINED_STOCK_SDK_COMMONCOMMO "+args[0]);
  }
}
