// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import android.util.Xml;
import com.atakmap.coremap.xml.XMLUtils;
import java.io.StringReader;
import java.net.URL;
import java.net.URLConnection;
import java.net.URLStreamHandler;
import java.nio.file.Files;
import java.nio.file.Path;
import org.xmlpull.v1.XmlPullParser;
import org.xmlpull.v1.XmlPullParserException;

public final class XmlCompatibilityTest {
    private static int checks;
    private static int externalRequests;
    private static void check(boolean result) {
        checks++;
        if (!result) throw new AssertionError("XML parser check " + checks);
    }
    private static String text(XmlPullParser parser, String xml) throws Exception {
        parser.setInput(new StringReader(xml));
        StringBuilder result = new StringBuilder();
        int events = 0;
        while (parser.next() != XmlPullParser.END_DOCUMENT) {
            if (++events > 100) throw new AssertionError("Unbounded fixture parsing");
            if (parser.getEventType() == XmlPullParser.TEXT) result.append(parser.getText());
        }
        return result.toString();
    }
    public static void main(String[] args) throws Exception {
        URL.setURLStreamHandlerFactory(protocol -> "http".equals(protocol) ? new URLStreamHandler() {
            protected URLConnection openConnection(URL url) {
                externalRequests++;
                throw new AssertionError("External XML network access attempted");
            }
        } : null);
        XmlPullParser parser = Xml.newPullParser();
        check(parser.getFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES));
        check(!parser.getFeature(Xml.FEATURE_RELAXED));
        check(!parser.getFeature(XmlPullParser.FEATURE_PROCESS_DOCDECL));
        for (boolean setting : new boolean[]{false, true}) {
            try { parser.setFeature(XmlPullParser.FEATURE_PROCESS_DOCDECL, setting);
                  throw new AssertionError("Unsupported DTD feature accepted"); }
            catch (XmlPullParserException expected) { checks++; }
        }
        parser.setInput(new StringReader("<p:r xmlns:p='urn:test' p:a='v'>text&amp;more</p:r>"));
        check(parser.nextTag() == XmlPullParser.START_TAG);
        check("r".equals(parser.getName()) && "urn:test".equals(parser.getNamespace()));
        check("v".equals(parser.getAttributeValue("urn:test", "a")));
        check("text&more".equals(parser.nextText()));
        parser = XMLUtils.getXmlPullParser(); // Actual unchanged pinned consumer.
        check(!parser.getFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES));
        check(parser.getFeature(Xml.FEATURE_RELAXED));
        parser.setInput(new StringReader("<r unquoted=value >body</r>"));
        check(parser.nextTag() == XmlPullParser.START_TAG);
        check("value".equals(parser.getAttributeValue(null, "unquoted")));
        String actual = parser.nextText();
        check("ERR: attr value delimiter missing!body".equals(actual));
        try { text(Xml.newPullParser(), "<r unquoted=value/>");
              throw new AssertionError("Strict parser accepted unquoted attribute"); }
        catch (XmlPullParserException expected) { checks++; }
        String internal = "<!DOCTYPE r [<!ENTITY e 'EXPANDED'>]><r>&e;</r>";
        try { text(Xml.newPullParser(), internal); throw new AssertionError("Undeclared entity accepted"); }
        catch (XmlPullParserException expected) { checks++; }
        // Real upstream relaxed mode drops unresolved entity text; it does not expand a DTD.
        check("".equals(text(XMLUtils.getXmlPullParser(), internal)));
        check("safe".equals(text(XMLUtils.getXmlPullParser(),
            "<!DOCTYPE r SYSTEM 'http://127.0.0.1:9/never.dtd'><r>safe</r>")));
        check("".equals(text(XMLUtils.getXmlPullParser(),
            "<!DOCTYPE r [<!ENTITY e SYSTEM 'http://127.0.0.1:9/never'>]><r>&e;</r>")));
        Path secret = Files.createTempFile("xml-entity-", ".txt");
        try {
            Files.writeString(secret, "PRIVATE_ENTITY_MARKER");
            check("".equals(text(XMLUtils.getXmlPullParser(),
                "<!DOCTYPE r [<!ENTITY e SYSTEM '" + secret.toUri() + "'>]><r>&e;</r>")));
        } finally { Files.delete(secret); }
        check(externalRequests == 0);
        check("<>&\"'".equals(text(Xml.newPullParser(), "<r>&lt;&gt;&amp;&quot;&apos;</r>")));
        System.out.println(checks + " real kXML2/unchanged XMLUtils checks passed; no external resolution");
    }
}
