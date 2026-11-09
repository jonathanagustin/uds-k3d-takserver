// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: Apache-2.0
package android.util;

import org.kxml2.io.KXmlParser;
import org.xmlpull.v1.XmlPullParser;
import org.xmlpull.v1.XmlPullParserException;

/** Real desktop pull parsing. Android's DTD-processing default is not supplied. */
public final class Xml {
    public static String FEATURE_RELAXED = "http://xmlpull.org/v1/doc/features.html#relaxed";
    private Xml() {}

    /**
     * Namespace-aware kXML2 parser. DTD processing is unsupported and disabled;
     * requesting that feature still throws instead of silently changing behavior.
     */
    public static XmlPullParser newPullParser() {
        KXmlParser parser = new KXmlParser();
        try {
            parser.setFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES, true);
        } catch (XmlPullParserException error) {
            throw new IllegalStateException("Required namespace support unavailable", error);
        }
        return parser;
    }
}
