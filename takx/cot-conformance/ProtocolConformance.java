// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import com.atakmap.commoncommo.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import javax.xml.parsers.*;
import org.w3c.dom.*;
import org.xml.sax.InputSource;

/** Tests the actual CommonCommo codec and streaming state machine; no replacement codec. */
public final class ProtocolConformance {
    static int assertions;
    static void require(boolean value, String message) {
        assertions++;
        if (!value) throw new AssertionError(message);
    }
    interface Checked { void run() throws Exception; }
    static void reject(Checked action, String message) throws Exception {
        try { action.run(); } catch (CommoException expected) { assertions++; return; }
        throw new AssertionError(message);
    }
    static Document xml(String value) throws Exception {
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        f.setFeature("http://xml.org/sax/features/external-general-entities", false);
        f.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
        f.setXIncludeAware(false); f.setExpandEntityReferences(false);
        return f.newDocumentBuilder().parse(new InputSource(new StringReader(value)));
    }
    // Semantic XML comparison: attribute order/quote/empty-element formatting may change.
    static String tree(Node n) {
        if (n.getNodeType() == Node.TEXT_NODE) return n.getTextContent().trim();
        if (n.getNodeType() != Node.ELEMENT_NODE) return "";
        TreeMap<String,String> attrs = new TreeMap<>();
        for (int i=0; i<n.getAttributes().getLength(); i++) {
            Node a=n.getAttributes().item(i); attrs.put(a.getNodeName(),a.getNodeValue());
        }
        StringBuilder s=new StringBuilder(n.getNodeName()+attrs+"[");
        for (Node c=n.getFirstChild();c!=null;c=c.getNextSibling()) s.append(tree(c));
        return s.append(']').toString();
    }
    static String event(String uid, String type, String detail) {
        return "<?xml version='1.0' encoding='UTF-8'?><event version='2.0' uid='"+uid+"' type='"+type+"' time='2026-01-01T00:00:00Z' start='2026-01-01T00:00:00Z' stale='2099-01-01T00:00:00Z' how='m-g'><point lat='0' lon='0' hae='0' ce='1' le='1'/><detail>"+detail+"</detail></event>";
    }
    static byte[] payload(Commo c,String value) throws Exception {
        byte[] b=c.cotXmlToTakproto(value,1);
        require(b.length>3 && b[0]==(byte)0xbf && b[1]==1 && b[2]==(byte)0xbf,"actual broadcast framing");
        return Arrays.copyOfRange(b,3,b.length);
    }
    // Only test-peer transport framing, as specified in official README; payload is genuine codec output.
    static byte[] frame(byte[] p) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream(); out.write(0xbf);
        int n=p.length;
        do { int b=n&127; n>>>=7; out.write(b|(n==0?0:128)); } while(n!=0);
        out.write(p); return out.toByteArray();
    }
    static String readXml(InputStream in) throws IOException {
        ByteArrayOutputStream b=new ByteArrayOutputStream();
        while(b.size()<65536) {
            int x=in.read(); if(x<0) throw new EOFException(); b.write(x);
            String s=b.toString(StandardCharsets.UTF_8);
            if(s.endsWith("</event>")) return s;
        }
        throw new IOException("oversize XML peer response");
    }
    static void streaming(Commo c, boolean accept) throws Exception {
        BlockingQueue<String> received=new LinkedBlockingQueue<>();
        CoTMessageListener listener=(message,endpoint)->received.add(message);
        c.addCoTMessageListener(listener);
        StreamingNetInterface iface=null;
        try(ServerSocket server=new ServerSocket(0,1,InetAddress.getByName("127.0.0.1"))) {
            server.setSoTimeout(5000);
            iface=c.addStreamingInterface(StreamingTransport.TCP,"127.0.0.1",server.getLocalPort(),new CoTMessageType[]{CoTMessageType.SITUATIONAL_AWARENESS},null,null,null,null,null,null);
            try(Socket socket=server.accept()) {
                socket.setSoTimeout(5000);
                OutputStream out=socket.getOutputStream();
                out.write(event("support","t-x-takp-v","<TakControl><TakProtocolSupport version='1'/></TakControl>").getBytes(StandardCharsets.UTF_8)); out.flush();
                String request=readXml(socket.getInputStream());
                Element r=(Element)xml(request).getElementsByTagName("TakRequest").item(0);
                require(r!=null && r.getAttribute("version").equals("1"),"real client requested version1");
                out.write(event("support","t-x-takp-r","<TakControl><TakResponse status='"+accept+"'/></TakControl>").getBytes(StandardCharsets.UTF_8)); out.flush();
                String first=event("incoming-first","a-f-G-U-C","<unregistered><value>first</value></unregistered>");
                String second=event("incoming-second","a-f-G-U-C","<remarks>second</remarks>");
                if(accept) {
                    byte[] a=frame(payload(c,first)), b=frame(payload(c,second));
                    // Deterministic fragmentation, followed by coalescing two messages in one write.
                    out.write(a,0,1);out.flush();out.write(a,1,1);out.flush();
                    ByteArrayOutputStream joined=new ByteArrayOutputStream(); joined.write(a,2,a.length-2);joined.write(b);out.write(joined.toByteArray());out.flush();
                } else { out.write((first+second).getBytes(StandardCharsets.UTF_8));out.flush(); }
                String a=received.poll(5,TimeUnit.SECONDS),b=received.poll(5,TimeUnit.SECONDS);
                require(a!=null && b!=null,"both framed events delivered");
                Map<String,String> events=new HashMap<>();
                events.put(xml(a).getDocumentElement().getAttribute("uid"),a);
                events.put(xml(b).getDocumentElement().getAttribute("uid"),b);
                require(events.keySet().equals(Set.of("incoming-first","incoming-second")),"exact event set; no FIFO claim");
                require(tree(xml(events.get("incoming-first")).getElementsByTagName("unregistered").item(0)).contains("first"),"stream unknown detail preserved");
                System.out.println("OBSERVED callback order "+xml(a).getDocumentElement().getAttribute("uid")+","+xml(b).getDocumentElement().getAttribute("uid"));
                require(received.isEmpty(),"control messages not delivered as application events");
                System.out.println("PASS negotiation "+(accept?"accept-v1 fragmented/coalesced stream":"deny-v1 XML fallback"));
            }
        } finally { if(iface!=null)c.removeStreamingInterface(iface);c.removeCoTMessageListener(listener); }
    }
    public static void main(String[] args) throws Exception {
        require(Path.of(Commo.class.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath().equals(Path.of(args[1]).toRealPath()),"accepted JAR class origin");
        Commo c=new Commo((level,type,message,detail)->System.out.println("NATIVE "+level+" "+message),"protocol-conformance","SYNTHETIC");
        try {
            String source=Files.readString(Path.of(args[0],"fixtures/unknown.cot"));
            byte[] b=c.cotXmlToTakproto(source,1); payload(c,source);
            String round=c.takprotoToCotXml(b);
            Document before=xml(source),after=xml(round);
            for(String name:List.of("unregistered","remarks","contact"))
                require(tree(before.getElementsByTagName(name).item(0)).equals(tree(after.getElementsByTagName(name).item(0))),"round-trip "+name);
            require(after.getDocumentElement().getAttribute("uid").equals("synthetic-conformance"),"event UID");
            for(String variant:List.of(source.replace("callsign=\"SYNTHETIC\"", "extra=\"unknown\" callsign=\"SYNTHETIC\""), source.replace("</detail>","<contact callsign='SECOND'/></detail>"))) {
                Document original=xml(variant), restored=xml(c.takprotoToCotXml(c.cotXmlToTakproto(variant,1)));
                NodeList x=original.getElementsByTagName("contact"), y=restored.getElementsByTagName("contact");
                require(x.getLength()==y.getLength(),"duplicate typed details retained");
                for(int i=0;i<x.getLength();i++) require(tree(x.item(i)).equals(tree(y.item(i))),"whole-element fallback preserves unmapped typed fields");
            }
            String official=Files.readString(Path.of(args[0],"official/takcot/examples/Marker - Spot.cot"));
            String officialRound=c.takprotoToCotXml(c.cotXmlToTakproto(official,1));
            require(xml(official).getDocumentElement().getAttribute("uid").equals(xml(officialRound).getDocumentElement().getAttribute("uid")),"unchanged official fixture UID");
            require(xml(officialRound).getElementsByTagName("archive").getLength()==2,"official duplicate details preserved");
            reject(()->c.cotXmlToTakproto(source,0),"version0 encoded");
            reject(()->c.cotXmlToTakproto(source,99),"unsupported version encoded");
            reject(()->c.cotXmlToTakproto("<event/>",1),"missing required fields accepted");
            reject(()->c.cotXmlToTakproto(source.substring(0,source.length()/2),1),"malformed XML accepted");
            reject(()->c.takprotoToCotXml(new byte[0]),"empty binary accepted");
            reject(()->c.takprotoToCotXml(new byte[]{(byte)0xbf,99,(byte)0xbf,0}),"unsupported header accepted");
            reject(()->c.takprotoToCotXml(new byte[]{(byte)0xbf,1,(byte)0xbf,(byte)0x80}),"truncated varint accepted");
            byte[] corrupt=b.clone();corrupt[0]=0;reject(()->c.takprotoToCotXml(corrupt),"bad magic accepted");
            streaming(c,true);streaming(c,false);
            Files.writeString(Path.of(args[2]),Files.readString(Path.of("/proc/self/maps")));
        } finally {c.shutdown();}
        System.out.println("PASS "+assertions+" assertions; actual shutdown returned");
    }
}
