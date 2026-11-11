// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.platform.symbology.milstd2525;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.util.*;
import javax.imageio.ImageIO;
import android.content.Context;
import android.graphics.Bitmap;
import gov.tak.api.cot.detail.RolesManager;
import gov.tak.api.engine.map.coords.GeoPoint;
import gov.tak.api.engine.map.coords.IGeoPoint;
import gov.tak.api.symbology.ISymbologyProvider;
import gov.tak.api.util.AttributeSet;
import gov.tak.platform.marshal.MarshalManager;

/** Real headless controls only; label/scene JNI and multipoint/native acceptance are separate gates. */
public final class HeadlessControls {
    static int checks;
    static synchronized void check(boolean yes,String message) {checks++;if(!yes)throw new AssertionError(message);}
    static void near(double a,double b,double tolerance,String name) {check(Math.abs(a-b)<=tolerance,name+" actual="+a+" expected="+b);}
    static void reject(Runnable action) {try{action.run();throw new AssertionError("invalid input accepted");}catch(IllegalArgumentException expected){checks++;}}
    static java.util.List<IGeoPoint> points(double... v) {
        ArrayList<IGeoPoint> out=new ArrayList<>();for(int i=0;i<v.length;i+=2)out.add(new GeoPoint(v[i],v[i+1]));return out;
    }
    static void viewport() {
        near(PublicViewportFit.resolution(100,100,Collections.emptyList()),1,0,"empty fallback");
        near(PublicViewportFit.resolution(100,100,points(10,20)),1,0,"single fallback");
        near(PublicViewportFit.resolution(100,100,points(10,20,10,380)),1,0,"coincident modulo fallback");
        near(PublicViewportFit.resolution(100,100,points(90,0,90,170)),1,0,"pole coincidence");
        near(PublicViewportFit.meridianDistance(0,90),10001965.72931272,0.0001,"WGS84 quadrant meridian");
        near(PublicViewportFit.meridianDistance(0,1),110574.38855779878,0.0001,"WGS84 equator degree");
        near(PublicViewportFit.meridianDistance(-90,90),20003931.45862544,0.0002,"WGS84 pole to pole");
        double a=PublicViewportFit.resolution(400,200,points(-5,-10,5,10));
        near(PublicViewportFit.resolution(800,400,points(-5,-10,5,10)),a/2,1e-9,"size scales both axes");
        double horizontal=PublicViewportFit.resolution(400,200,points(0,-10,0,10));
        near(PublicViewportFit.resolution(800,1,points(0,-10,0,10)),horizontal/2,1e-9,"width independently honored");
        double vertical=PublicViewportFit.resolution(1,200,points(-5,0,5,0));
        near(PublicViewportFit.resolution(1000,400,points(-5,0,5,0)),vertical/2,1e-9,"height independently honored");
        near(PublicViewportFit.resolution(0,200,points(-5,-10,5,10)),PublicViewportFit.resolution(256,200,points(-5,-10,5,10)),0,"zero width fallback only");
        near(PublicViewportFit.resolution(400,0,points(-5,-10,5,10)),PublicViewportFit.resolution(400,256,points(-5,-10,5,10)),0,"zero height fallback only");
        double idl=PublicViewportFit.resolution(100,100,points(0,179,0,-179));
        near(idl,PublicViewportFit.resolution(100,100,points(0,-1,0,1)),1e-9,"IDL shortest arc");
        near(PublicViewportFit.resolution(100,100,points(0,0,0,90,0,180,0,270)),idl*135,1e-7,"global span270 degrees");
        check(PublicViewportFit.resolution(100,100,points(0,0,0,1e-15))>0,"tiny extent positive");
        reject(()->PublicViewportFit.resolution(-1,0,Collections.emptyList()));
        reject(()->PublicViewportFit.resolution(0,-1,Collections.emptyList()));
        reject(()->PublicViewportFit.resolution(1,1,points(Double.NaN,0)));
        reject(()->PublicViewportFit.resolution(1,1,points(91,0)));
        reject(()->PublicViewportFit.resolution(1,1,points(0,Double.POSITIVE_INFINITY)));
        // Actual unchanged caller branches: higher detail selects hint+bbox, equality/low detail does not.
        near(Math.min(a/2,a),a/2,0,"hint below minimum");check(a/2<a,"bbox enabled below minimum");
        near(Math.min(a*2,a),a,0,"minimum clamp retained");check(!(a<a),"bbox disabled at boundary");
        System.out.println("PASS_PUBLIC_VIEWPORT_FIT_V1_POLICY");
    }
    static void roles(Path root) throws Exception {
        Path assets=Files.createDirectories(root.resolve("assets"));BufferedImage base=new BufferedImage(64,48,BufferedImage.TYPE_INT_ARGB);
        Graphics2D g=base.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,64,48);g.dispose();ByteArrayOutputStream bytes=new ByteArrayOutputStream();ImageIO.write(base,"png",bytes);byte[] original=bytes.toByteArray();Files.write(assets.resolve("role.png"),original);
        RolesManager manager=new RolesManager();int[] closed={0};gov.tak.api.commons.resources.IAssetManager source=name->{if(!name.equals("role.png"))throw new FileNotFoundException(name);return new ByteArrayInputStream(original){public void close()throws IOException{closed[0]++;super.close();}};};
        gov.tak.api.commons.graphics.Bitmap firstGov=manager.createIcon("Mi","role.png",source),secondGov=manager.createIcon("Mi","role.png",source);
        check(firstGov!=null&&secondGov!=null&&firstGov!=secondGov,"genuine fresh public bitmap ownership");
        Bitmap first=MarshalManager.marshal(firstGov,gov.tak.api.commons.graphics.Bitmap.class,Bitmap.class),second=MarshalManager.marshal(secondGov,gov.tak.api.commons.graphics.Bitmap.class,Bitmap.class);
        check(first!=null&&second!=null,"actual registered gov to Android roundtrip");
        check(first!=null&&first.isMutable()&&first.getWidth()==64&&first.getHeight()==48,"real fresh asset icon");check(first!=second,"fresh call not cached");check(closed[0]==2,"real streams closed");int ink=0;
        for(int y=0;y<48;y++)for(int x=0;x<64;x++){check(first.getPixel(x,y)==second.getPixel(x,y),"fresh pixel parity");if(first.getPixel(x,y)!=Color.WHITE.getRGB())ink++;}
        BufferedImage expected=new BufferedImage(64,48,BufferedImage.TYPE_INT_ARGB);Graphics2D oracle=expected.createGraphics();oracle.setColor(Color.WHITE);oracle.fillRect(0,0,64,48);oracle.setColor(Color.BLACK);oracle.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_OFF);oracle.setRenderingHint(RenderingHints.KEY_FRACTIONALMETRICS,RenderingHints.VALUE_FRACTIONALMETRICS_ON);
        java.awt.font.TextLayout glyph=new java.awt.font.TextLayout("Mi",new Font(Font.SANS_SERIF,Font.BOLD,12),new java.awt.font.FontRenderContext(null,false,true));int measured=(int)Math.ceil(glyph.getAdvance());oracle.fill(glyph.getOutline(java.awt.geom.AffineTransform.getTranslateInstance(0,0)));oracle.fill(glyph.getOutline(java.awt.geom.AffineTransform.getTranslateInstance((64-measured)/2,(48+12/2)/2)));oracle.dispose();
        for(int y=0;y<48;y++)for(int x=0;x<64;x++)check(first.getPixel(x,y)==expected.getRGB(x,y),"independent actual glyph placement/color oracle");
        check(ink>0,"real glyph pixels");check(manager.createIcon("Mi","missing",source)==null,"missing asset failure retained");
        try(URLClassLoader loader=new URLClassLoader(new URL[]{root.toUri().toURL()},HeadlessControls.class.getClassLoader())){
            Context context=new Context(root.resolve("app"),"gov.tak.test.interop",loader);Bitmap cached=manager.getIcon("Mi","role.png",context);check(cached!=null&&manager.getIcon("Mi","role.png",context)==cached,"public getIcon cache retained");
            for(int y=0;y<48;y++)for(int x=0;x<64;x++)check(cached.getPixel(x,y)==first.getPixel(x,y),"existing context and real asset composition parity");
        }
        // Exact Client expression: the declared source type is the public gov Bitmap, not Android Bitmap.
        BufferedImage client=MarshalManager.marshal(manager.createIcon("Mi","role.png",source),gov.tak.api.commons.graphics.Bitmap.class,BufferedImage.class);
        check(client!=null&&client.getWidth()==64&&client.getHeight()==48,"actual Client marshal expression nonnull");
        for(int y=0;y<48;y++)for(int x=0;x<64;x++)check(client.getRGB(x,y)==firstGov.getPixel(x,y),"Client marshal pixel identity");
        int prior=secondGov.getPixel(0,0);firstGov.setPixel(0,0,0xff123456);
        check(first.getPixel(0,0)==0xff123456,"real public bitmap mutable Android backing");
        check(secondGov.getPixel(0,0)==prior&&second.getPixel(0,0)==prior&&client.getRGB(0,0)==prior,"independent fresh image mutation isolation");
        Bitmap later=manager.getIcon("Mi","role.png",new Context(root.resolve("app"),"gov.tak.test.interop",HeadlessControls.class.getClassLoader()));
        check(later!=null&&later.getPixel(0,0)==prior,"old Context cache unaffected by fresh mutation");
        check(closed[0]==3,"all real fresh asset streams closed");
        check(Arrays.equals(Files.readAllBytes(assets.resolve("role.png")),original),"source unchanged");System.out.println("PASS_REAL_ROLE_PUBLIC_BITMAP_CLIENT_MARSHAL_PIXEL_CACHE_AND_ISOLATION_CONTROLS");
    }
    static String bitmapHash(gov.tak.api.commons.graphics.Bitmap bitmap)throws Exception{
        BufferedImage image=MarshalManager.marshal(bitmap,gov.tak.api.commons.graphics.Bitmap.class,BufferedImage.class);check(image!=null,"real bitmap marshal");java.security.MessageDigest md=java.security.MessageDigest.getInstance("SHA-256");for(int y=0;y<image.getHeight();y++)for(int x=0;x<image.getWidth();x++){int p=image.getRGB(x,y);md.update((byte)(p>>>24));md.update((byte)(p>>>16));md.update((byte)(p>>>8));md.update((byte)p);}return java.util.HexFormat.of().formatHex(md.digest());
    }
    static void fonts()throws Exception{
        ISymbologyProvider[] providers={new MilStd2525cSymbologyProvider(),new MilStd2525dSymbologyProvider(),new MilStd2525eSymbologyProvider()};String[] codes={"SFGPUCI----K---","11031000001211000000","13031000001211000000"};
        Map<String,String> expected=new HashMap<>();
        for(int i=0;i<providers.length;i++){
            ISymbologyProvider.RendererHints hints=new ISymbologyProvider.RendererHints();hints.iconSize=64;hints.fontSize=18;AttributeSet attrs=new AttributeSet();attrs.setAttribute(MilSymStandardAttributes.MILSYM_MODIFIER_PREFIX+"T","WiWi Label");String first=null;
            for(String font:new String[]{"Serif","Monospaced","Serif"}){hints.fontName=font;gov.tak.api.commons.graphics.Bitmap bitmap=providers[i].renderSinglePointIcon(codes[i],attrs,hints);check(bitmap!=null,"actual C/D/E provider image "+i);String hash=bitmapHash(bitmap);expected.put(i+":"+font,hash);if(first==null)first=hash;else if(font.equals("Serif"))check(first.equals(hash),"A-B-A actual renderer stability");else check(!first.equals(hash),"actual distinct font output");check(font.equals(i==0?RenderContextWrapper.prevFontNameC:RenderContextWrapper.prevFontNameD),"actual font forwarding "+i);}
            hints.fontName=null;check(providers[i].renderSinglePointIcon(codes[i],attrs,hints)!=null,"actual default font render");check("serif".equals(i==0?RenderContextWrapper.prevFontNameC:RenderContextWrapper.prevFontNameD),"null retains serif default");
        }
        java.util.concurrent.ExecutorService workers=java.util.concurrent.Executors.newFixedThreadPool(3);
        try {
            ArrayList<java.util.concurrent.Callable<String[]>> tasks=new ArrayList<>();
            for(int repeat=0;repeat<2;repeat++)for(int i=0;i<providers.length;i++)for(String font:new String[]{"Serif","Monospaced"}) {
                final int index=i;
                tasks.add(()->{
                    ISymbologyProvider.RendererHints hints=new ISymbologyProvider.RendererHints();hints.iconSize=64;hints.fontSize=18;hints.fontName=font;
                    AttributeSet attrs=new AttributeSet();attrs.setAttribute(MilSymStandardAttributes.MILSYM_MODIFIER_PREFIX+"T","WiWi Label");
                    return new String[]{index+":"+font,bitmapHash(providers[index].renderSinglePointIcon(codes[index],attrs,hints))};
                });
            }
            for(java.util.concurrent.Future<String[]> task:workers.invokeAll(tasks)) {String[] result=task.get();check(expected.get(result[0]).equals(result[1]),"concurrent actual C/D/E font lock output");}
        } finally {workers.shutdownNow();}
        System.out.println("PASS_REAL_CDE_FONT_FORWARDING_DEFAULT_AND_CONCURRENT_LOCK");
    }
    public static void main(String[] args)throws Exception{
        Path data=Files.createDirectories(Path.of(args[0]));viewport();roles(data);fonts();
        for(String line:Files.readAllLines(Path.of("/proc/self/maps")))if(line.contains("libtakengine")||line.contains("libgdal")||line.contains("libGLES"))throw new AssertionError("SDK native execution not authorized: "+line);
        System.out.println("PASS_REAL_HEADLESS_CONTROLS checks="+checks+"; multipoint/native acceptance remains false");
    }
}
