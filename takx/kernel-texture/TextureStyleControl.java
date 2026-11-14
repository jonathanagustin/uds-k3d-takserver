// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.map.layer.feature.style.*;
import com.atakmap.map.layer.feature.ogr.style.FeatureStyleParser;
import java.nio.file.*;
import java.security.MessageDigest;

/** Actual JNI style ownership/serialization control, run only against reviewed native manifests. */
public final class TextureStyleControl {
  static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
  static String digest(Path file)throws Exception{
    MessageDigest md=MessageDigest.getInstance("SHA-256");
    try(var input=Files.newInputStream(file)){byte[] block=new byte[65536];for(int n;(n=input.read(block))!=-1;)md.update(block,0,n);}
    var value=new StringBuilder();for(byte b:md.digest())value.append(String.format("%02x",b));return value.toString();
  }
  static void fields(TextureFillStyle texture){
    check(texture.getUri().equals("file:///owned/texture;with,delimiters.png"),"URI");
    check(texture.getColor()==0x80abcdef,"ARGB");check(texture.getRepeatTypeX()==0&&texture.getRepeatTypeY()==1,"repeat/stretch");
    check(texture.getWidth()==32&&texture.getHeight()==48&&texture.getRotation()==-45.25f&&texture.isAbsolute(),"dimensions/rotation/anchor");
  }
  public static void main(String[] args)throws Exception{
    check(args.length==1,"native manifest required");
    for(String row:Files.readAllLines(Path.of(args[0]))){if(row.isBlank()||row.startsWith("#"))continue;String[] parts=row.split(" ",2);check(parts.length==2&&parts[0].matches("[0-9a-f]{64}"),"native manifest");Path file=Path.of(parts[1]);check(file.isAbsolute()&&!Files.isSymbolicLink(file)&&Files.isRegularFile(file)&&digest(file).equals(parts[0]),"native identity");System.load(file.toString());}
    for(int repeat=0;repeat<50;repeat++){
      TextureFillStyle texture=new TextureFillStyle("file:///owned/texture;with,delimiters.png",0x80abcdef,0,1,32,48,-45.25f,true);
      BasicFillStyle base=new BasicFillStyle(0xff123456);Style clone=texture.clone();CompositeStyle composite=new CompositeStyle(new Style[]{base,texture});Style compositeClone=composite.clone();
      try{
        fields(texture);check(clone instanceof TextureFillStyle&&clone.equals(texture),"real clone/class/equality");fields((TextureFillStyle)clone);
        check(compositeClone instanceof CompositeStyle&&composite.equals(compositeClone),"composite native clone/equality");
        Style child=((CompositeStyle)compositeClone).getStyle(1);
        try{check(child instanceof TextureFillStyle,"native composite class dispatch");fields((TextureFillStyle)child);}finally{child.dispose();}
        String packed=FeatureStyleParser.pack(composite);check(packed.contains("uds-tak-texture-v1:"),"explicit project serialization");
        // parse2 retains and returns the same cached style. Dispose our clone,
        // never the cache-owned object requested again by the next iteration.
        Style cached=FeatureStyleParser.parse2(packed);check(cached!=null,"native parser result");
        Style restored=cached.clone();
        try{
          check(restored instanceof CompositeStyle,"native parser composite class");
          CompositeStyle parsed=(CompositeStyle)restored;
          check(parsed.getNumStyles()==2,"native parser child count");
          // JNI getStyle returns an owned native clone; dispose each wrapper.
          Style parsedBase=parsed.getStyle(0),parsedTexture=parsed.getStyle(1);
          try{check(parsedBase instanceof BasicFillStyle&&parsedBase.equals(base),"native parser first child/value");
          check(parsedTexture instanceof TextureFillStyle&&parsedTexture.equals(texture),"native parser second child/value");
          fields((TextureFillStyle)parsedTexture);
          }finally{parsedTexture.dispose();parsedBase.dispose();}
        }finally{if(restored!=null)restored.dispose();}
      }finally{clone.dispose();compositeClone.dispose();composite.dispose();base.dispose();texture.dispose();}
    }
    for(int mode=0;mode<5;mode++){
      boolean refused=false;
      try{new TextureFillStyle(mode==0?null:"file:///owned/texture.png",0xffffffff,mode==1?2:0,0,mode==2?0:32,mode==3?-1:32,mode==4?Float.NaN:0,true);}catch(IllegalArgumentException expected){refused=true;}
      check(refused,"invalid style must refuse");
    }
    System.out.println("PASS_REAL_TEXTURE_STYLE_JNI_COMPOSITE_CLONE_SERIALIZATION_LIFECYCLE");
  }
}
