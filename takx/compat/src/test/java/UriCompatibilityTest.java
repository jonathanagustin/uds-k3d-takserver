// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: Apache-2.0
// Test bodies from pinned AOSP UriTest.java; standalone assertion runner replaces JUnit.
/*
 * Copyright (C) 2007 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package android.net;
import java.io.File;
import java.util.*;
public final class UriCompatibilityTest {
 private static int checks;
 private static void assertEquals(Object expected, Object actual) { checks++; if (!Objects.equals(expected,actual)) throw new AssertionError(expected+" != "+actual); }
 private static void assertTrue(boolean value) { checks++; if(!value) throw new AssertionError(); }
 private static void assertFalse(boolean value) { assertTrue(!value); }
 private static void assertNull(Object value) { assertEquals(null,value); }
 private static void assertNotNull(Object value) { assertTrue(value!=null); }
 private static void fail() { throw new AssertionError(); }
 public static void main(String[] args) throws Exception {
  UriCompatibilityTest test=new UriCompatibilityTest();
  test.testToStringWithPathOnly();
  test.testBuildUponOpaqueStringUri();
  test.testStringUri();
  test.testStringUriIsHierarchical();
  test.testNullUriString();
  test.testNullFile();
  test.testCompareTo();
  test.testEqualsAndHashCode();
  test.testAuthorityParsing();
  test.testBuildUponOpaqueUri();
  test.testBuildUponEncodedOpaqueUri();
  test.testPathSegmentDecoding();
  test.testSms();
  test.testEncodeWithAllowedChars();
  test.testEncodeDecode();
  test.testFile();
  test.testQueryParameters();
  test.testHostWithTrailingDot();
  test.testSchemeOnly();
  test.testEmptyPath();
  test.testGetQueryParameter();
  test.testGetQueryParameterWorkaround();
  test.testGetQueryParameterEdgeCases();
  test.testGetQueryParameterEmptyKey();
  test.testGetQueryParameterEmptyKey2();
  test.testGetQueryParameterEmptyKey3();
  test.testGetQueryParameterEmptyKey4();
  test.testGetQueryParametersEmptyKey();
  test.testGetQueryParametersEmptyKey2();
  test.testGetQueryParametersEmptyKey3();
  test.testGetQueryParameterNames();
  test.testGetQueryParameterNamesEmptyKey();
  test.testGetQueryParameterNamesEmptyKey2();
  test.testGetQueryParameterNamesEmptyValues();
  test.testGetQueryParameterNamesEdgeCases();
  test.testGetQueryParameterNamesEscapedKeys();
  test.testGetQueryParameterEscapedKeys();
  test.testClearQueryParameters();
  test.testGetQueryParametersEmptyValue();
  test.testPlusCharacterInQuery();
  test.desktopBoundaryCases();
  System.out.println(checks+" assertions in 40 pinned AOSP URI cases plus desktop boundary checks passed");
 }
    public void testToStringWithPathOnly() {
        Uri.Builder builder = new Uri.Builder();

        // Not a valid path, but this came from a user's test case.
        builder.path("//foo");
        Uri uri = builder.build();
        assertEquals("//foo", uri.toString());
    }

    public void testBuildUponOpaqueStringUri() {
        Uri u = Uri.parse("bob:lee").buildUpon().scheme("robert").build();
        assertEquals("robert", u.getScheme());
        assertEquals("lee", u.getEncodedSchemeSpecificPart());
        assertEquals("lee", u.getSchemeSpecificPart());
        assertNull(u.getQuery());
        assertNull(u.getPath());
        assertNull(u.getAuthority());
        assertNull(u.getHost());
    }

    public void testStringUri() {
        assertEquals("bob lee",
                Uri.parse("foo:bob%20lee").getSchemeSpecificPart());
        assertEquals("bob%20lee",
                Uri.parse("foo:bob%20lee").getEncodedSchemeSpecificPart());
        assertEquals("/bob%20lee",
                Uri.parse("foo:/bob%20lee").getEncodedPath());
        assertNull(Uri.parse("foo:bob%20lee").getPath());
        assertEquals("bob%20lee",
                Uri.parse("foo:?bob%20lee").getEncodedQuery());
        assertNull(Uri.parse("foo:bar#?bob%20lee").getQuery());
        assertEquals("bob%20lee",
                Uri.parse("foo:#bob%20lee").getEncodedFragment());
    }

    public void testStringUriIsHierarchical() {
        assertTrue(Uri.parse("bob").isHierarchical());
        assertFalse(Uri.parse("bob:").isHierarchical());
    }

    public void testNullUriString() {
        try {
            Uri.parse(null);
            fail();
        } catch (NullPointerException e) {}
    }

    public void testNullFile() {
        try {
            Uri.fromFile(null);
            fail();
        } catch (NullPointerException e) {}
    }

    public void testCompareTo() {
        Uri a = Uri.parse("foo:a");
        Uri b = Uri.parse("foo:b");
        Uri b2 = Uri.parse("foo:b");

        assertTrue(a.compareTo(b) < 0);
        assertTrue(b.compareTo(a) > 0);
        assertEquals(0, b.compareTo(b2));
    }

    public void testEqualsAndHashCode() {

        Uri a = Uri.parse("http://crazybob.org/test/?foo=bar#tee");

        Uri b = new Uri.Builder()
                .scheme("http")
                .authority("crazybob.org")
                .path("/test/")
                .encodedQuery("foo=bar")
                .fragment("tee")
                .build();

        // Try alternate builder methods.
        Uri c = new Uri.Builder()
                .scheme("http")
                .encodedAuthority("crazybob.org")
                .encodedPath("/test/")
                .encodedQuery("foo=bar")
                .encodedFragment("tee")
                .build();

        assertFalse(Uri.EMPTY.equals(null));

        assertEquals(a, b);
        assertEquals(b, c);
        assertEquals(c, a);

        assertEquals(a.hashCode(), b.hashCode());
        assertEquals(b.hashCode(), c.hashCode());
    }

    public void testAuthorityParsing() {
        Uri uri = Uri.parse("http://localhost:42");
        assertEquals("localhost", uri.getHost());
        assertEquals(42, uri.getPort());

        uri = Uri.parse("http://bob@localhost:42");
        assertEquals("bob", uri.getUserInfo());
        assertEquals("localhost", uri.getHost());
        assertEquals(42, uri.getPort());

        uri = Uri.parse("http://bob%20lee@localhost:42");
        assertEquals("bob lee", uri.getUserInfo());
        assertEquals("bob%20lee", uri.getEncodedUserInfo());

        uri = Uri.parse("http://bob%40lee%3ajr@local%68ost:4%32");
        assertEquals("bob@lee:jr", uri.getUserInfo());
        assertEquals("localhost:42", uri.getHost());

        uri = Uri.parse("http://localhost");
        assertEquals("localhost", uri.getHost());
        assertEquals(-1, uri.getPort());

        uri = Uri.parse("http://a:a@example.com:a@example2.com/path");
        assertEquals("a:a@example.com:a@example2.com", uri.getAuthority());
        assertEquals("example2.com", uri.getHost());
        assertEquals(-1, uri.getPort());
        assertEquals("/path", uri.getPath());

        uri = Uri.parse("http://a.foo.com\\.example.com/path");
        assertEquals("a.foo.com", uri.getHost());
        assertEquals(-1, uri.getPort());
        assertEquals("\\.example.com/path", uri.getPath());
    }

    public void testBuildUponOpaqueUri() {
        Uri a = Uri.fromParts("foo", "bar", "tee");
        Uri b = a.buildUpon().fragment("new").build();
        assertEquals("new", b.getFragment());
        assertEquals("bar", b.getSchemeSpecificPart());
        assertEquals("foo", b.getScheme());
    }

    public void testBuildUponEncodedOpaqueUri() {
        Uri a = new Uri.Builder()
                .scheme("foo")
                .encodedOpaquePart("bar")
                .fragment("tee")
                .build();
        Uri b = a.buildUpon().fragment("new").build();
        assertEquals("new", b.getFragment());
        assertEquals("bar", b.getSchemeSpecificPart());
        assertEquals("foo", b.getScheme());
    }

    public void testPathSegmentDecoding() {
        Uri uri = Uri.parse("foo://bar/a%20a/b%20b");
        assertEquals("a a", uri.getPathSegments().get(0));
        assertEquals("b b", uri.getPathSegments().get(1));
    }

    public void testSms() {
        Uri base = Uri.parse("content://sms");
        Uri appended = base.buildUpon()
                .appendEncodedPath("conversations/addr=555-1212")
                .build();
        assertEquals("content://sms/conversations/addr=555-1212",
                appended.toString());
        assertEquals(2, appended.getPathSegments().size());
        assertEquals("conversations", appended.getPathSegments().get(0));
        assertEquals("addr=555-1212", appended.getPathSegments().get(1));
    }

    public void testEncodeWithAllowedChars() {
        String encoded = Uri.encode("Bob:/", "/");
        assertEquals(-1, encoded.indexOf(':'));
        assertTrue(encoded.indexOf('/') > -1);
    }

    public void testEncodeDecode() {
        code(null);
        code("");
        code("Bob");
        code(":Bob");
        code("::Bob");
        code("Bob::Lee");
        code("Bob:Lee");
        code("Bob::");
        code("Bob:");
        code("::Bob::");
    }

    private void code(String s) {
        assertEquals(s, Uri.decode(Uri.encode(s, null)));
    }

    public void testFile() {
        File f = new File("/tmp/bob");

        Uri uri = Uri.fromFile(f);

        assertEquals("file:///tmp/bob", uri.toString());
    }

    public void testQueryParameters() {
        Uri uri = Uri.parse("content://user");

        assertEquals(null, uri.getQueryParameter("a"));

        uri = uri.buildUpon().appendQueryParameter("a", "b").build();

        assertEquals("b", uri.getQueryParameter("a"));

        uri = uri.buildUpon().appendQueryParameter("a", "b2").build();

        assertEquals(Arrays.asList("b", "b2"), uri.getQueryParameters("a"));

        uri = uri.buildUpon().appendQueryParameter("c", "d").build();

        assertEquals(Arrays.asList("b", "b2"), uri.getQueryParameters("a"));
        assertEquals("d", uri.getQueryParameter("c"));
    }

    public void testHostWithTrailingDot() {
        Uri uri = Uri.parse("http://google.com./b/c/g");
        assertEquals("google.com.", uri.getHost());
        assertEquals("/b/c/g", uri.getPath());
    }

    public void testSchemeOnly() {
        Uri uri = Uri.parse("empty:");
        assertEquals("empty", uri.getScheme());
        assertTrue(uri.isAbsolute());
        assertNull(uri.getPath());
    }

    public void testEmptyPath() {
        Uri uri = Uri.parse("content://user");
        assertEquals(0, uri.getPathSegments().size());
    }

    public void testGetQueryParameter() {
        String nestedUrl = "http://crazybob.org/?a=1&b=2";
        Uri uri = Uri.parse("http://test/").buildUpon()
                .appendQueryParameter("foo", "bar")
                .appendQueryParameter("nested", nestedUrl).build();
        assertEquals(nestedUrl, uri.getQueryParameter("nested"));
        assertEquals(nestedUrl, uri.getQueryParameters("nested").get(0));
    }

    public void testGetQueryParameterWorkaround() {
        // This was a workaround for a bug where getQueryParameter called
        // getQuery() instead of getEncodedQuery().
        String nestedUrl = "http://crazybob.org/?a=1&b=2";
        Uri uri = Uri.parse("http://test/").buildUpon()
                .appendQueryParameter("foo", "bar")
                .appendQueryParameter("nested", Uri.encode(nestedUrl)).build();
        assertEquals(nestedUrl, Uri.decode(uri.getQueryParameter("nested")));
        assertEquals(nestedUrl,
                Uri.decode(uri.getQueryParameters("nested").get(0)));
    }

    public void testGetQueryParameterEdgeCases() {
        Uri uri;

        // key at beginning of URL
        uri = Uri.parse("http://test/").buildUpon()
            .appendQueryParameter("key", "a b")
            .appendQueryParameter("keya", "c d")
            .appendQueryParameter("bkey", "e f")
            .build();
        assertEquals("a b", uri.getQueryParameter("key"));

        // key in middle of URL
        uri = Uri.parse("http://test/").buildUpon()
            .appendQueryParameter("akeyb", "a b")
            .appendQueryParameter("keya", "c d")
            .appendQueryParameter("key", "e f")
            .appendQueryParameter("bkey", "g h")
            .build();
        assertEquals("e f", uri.getQueryParameter("key"));

        // key at end of URL
        uri = Uri.parse("http://test/").buildUpon()
            .appendQueryParameter("akeyb", "a b")
            .appendQueryParameter("keya", "c d")
            .appendQueryParameter("key", "y z")
            .build();
        assertEquals("y z", uri.getQueryParameter("key"));

        // key is a substring of parameters, but not present
        uri = Uri.parse("http://test/").buildUpon()
            .appendQueryParameter("akeyb", "a b")
            .appendQueryParameter("keya", "c d")
            .appendQueryParameter("bkey", "e f")
            .build();
        assertNull(uri.getQueryParameter("key"));

        // key is a prefix or suffix of the query
        uri = Uri.parse("http://test/?qq=foo");
        assertNull(uri.getQueryParameter("q"));
        assertNull(uri.getQueryParameter("oo"));

        // escaped keys
        uri = Uri.parse("http://www.google.com/?a%20b=foo&c%20d=");
        assertEquals("foo", uri.getQueryParameter("a b"));
        assertEquals("", uri.getQueryParameter("c d"));
        assertNull(uri.getQueryParameter("e f"));
        assertNull(uri.getQueryParameter("b"));
        assertNull(uri.getQueryParameter("c"));
        assertNull(uri.getQueryParameter(" d"));

        // empty values
        uri = Uri.parse("http://www.google.com/?a=&b=&&c=");
        assertEquals("", uri.getQueryParameter("a"));
        assertEquals("", uri.getQueryParameter("b"));
        assertEquals("", uri.getQueryParameter("c"));
    }

    public void testGetQueryParameterEmptyKey() {
        Uri uri = Uri.parse("http://www.google.com/?=b");
        assertEquals("b", uri.getQueryParameter(""));
    }

    public void testGetQueryParameterEmptyKey2() {
      Uri uri = Uri.parse("http://www.google.com/?a=b&&c=d");
      assertEquals("", uri.getQueryParameter(""));
    }

    public void testGetQueryParameterEmptyKey3() {
      Uri uri = Uri.parse("http://www.google.com?");
      assertEquals("", uri.getQueryParameter(""));
    }

    public void testGetQueryParameterEmptyKey4() {
      Uri uri = Uri.parse("http://www.google.com?a=b&");
      assertEquals("", uri.getQueryParameter(""));
    }

    public void testGetQueryParametersEmptyKey() {
        Uri uri = Uri.parse("http://www.google.com/?=b&");
        List<String> values = uri.getQueryParameters("");
        assertEquals(2, values.size());
        assertEquals("b", values.get(0));
        assertEquals("", values.get(1));
    }

    public void testGetQueryParametersEmptyKey2() {
        Uri uri = Uri.parse("http://www.google.com?");
        List<String> values = uri.getQueryParameters("");
        assertEquals(1, values.size());
        assertEquals("", values.get(0));
    }

    public void testGetQueryParametersEmptyKey3() {
      Uri uri = Uri.parse("http://www.google.com/?a=b&&c=d");
      List<String> values = uri.getQueryParameters("");
      assertEquals(1, values.size());
      assertEquals("", values.get(0));
    }

    public void testGetQueryParameterNames() {
        Uri uri = Uri.parse("http://test?a=1");
        Set<String> names = uri.getQueryParameterNames();
        assertEquals(1, names.size());
        assertEquals("a", names.iterator().next());
    }

    public void testGetQueryParameterNamesEmptyKey() {
        Uri uri = Uri.parse("http://www.google.com/?a=x&&c=z");
        Set<String> names = uri.getQueryParameterNames();
        Iterator<String> iter = names.iterator();
        assertEquals(3, names.size());
        assertEquals("a", iter.next());
        assertEquals("", iter.next());
        assertEquals("c", iter.next());
    }

    public void testGetQueryParameterNamesEmptyKey2() {
        Uri uri = Uri.parse("http://www.google.com/?a=x&=d&c=z");
        Set<String> names = uri.getQueryParameterNames();
        Iterator<String> iter = names.iterator();
        assertEquals(3, names.size());
        assertEquals("a", iter.next());
        assertEquals("", iter.next());
        assertEquals("c", iter.next());
    }

    public void testGetQueryParameterNamesEmptyValues() {
        Uri uri = Uri.parse("http://www.google.com/?a=foo&b=&c=");
        Set<String> names = uri.getQueryParameterNames();
        Iterator<String> iter = names.iterator();
        assertEquals(3, names.size());
        assertEquals("a", iter.next());
        assertEquals("b", iter.next());
        assertEquals("c", iter.next());
    }

    public void testGetQueryParameterNamesEdgeCases() {
        Uri uri = Uri.parse("http://foo?a=bar&b=bar&c=&&d=baz&e&f&g=buzz&&&a&b=bar&h");
        Set<String> names = uri.getQueryParameterNames();
        Iterator<String> iter = names.iterator();
        assertEquals(9, names.size());
        assertEquals("a", iter.next());
        assertEquals("b", iter.next());
        assertEquals("c", iter.next());
        assertEquals("", iter.next());
        assertEquals("d", iter.next());
        assertEquals("e", iter.next());
        assertEquals("f", iter.next());
        assertEquals("g", iter.next());
        assertEquals("h", iter.next());
    }

    public void testGetQueryParameterNamesEscapedKeys() {
        Uri uri = Uri.parse("http://www.google.com/?a%20b=foo&c%20d=");
        Set<String> names = uri.getQueryParameterNames();
        assertEquals(2, names.size());
        Iterator<String> iter = names.iterator();
        assertEquals("a b", iter.next());
        assertEquals("c d", iter.next());
    }

    public void testGetQueryParameterEscapedKeys() {
        Uri uri = Uri.parse("http://www.google.com/?a%20b=foo&c%20d=");
        String value = uri.getQueryParameter("a b");
        assertEquals("foo", value);
    }

    public void testClearQueryParameters() {
        Uri uri = Uri.parse("http://www.google.com/?a=x&b=y&c=z").buildUpon()
            .clearQuery().appendQueryParameter("foo", "bar").build();
        Set<String> names = uri.getQueryParameterNames();
        assertEquals(1, names.size());
        assertEquals("foo", names.iterator().next());
    }

    public void testGetQueryParametersEmptyValue() {
        assertEquals(Arrays.asList(""),
                Uri.parse("http://foo/path?abc").getQueryParameters("abc"));
        assertEquals(Arrays.asList(""),
                Uri.parse("http://foo/path?foo=bar&abc").getQueryParameters("abc"));
        assertEquals(Arrays.asList(""),
                Uri.parse("http://foo/path?abcd=abc&abc").getQueryParameters("abc"));
        assertEquals(Arrays.asList("a", "", ""),
                Uri.parse("http://foo/path?abc=a&abc=&abc").getQueryParameters("abc"));
        assertEquals(Arrays.asList("a", "", ""),
                Uri.parse("http://foo/path?abc=a&abc=&abc=").getQueryParameters("abc"));
    }

    public void testPlusCharacterInQuery() {
        assertEquals("d e", Uri.parse("http://a/b?c=d%20e").getQueryParameter("c"));
        assertEquals("d e", Uri.parse("http://a/b?c=d+e").getQueryParameter("c"));
    }
    // Additional desktop boundary fixtures; original AOSP cases above are unchanged.
    private void desktopBoundaryCases() {
        assertEquals("snowman%E2%98%83%20%2F%3F", Uri.encode("snowman☃ /?"));
        assertEquals("snowman☃ /?", Uri.decode("snowman%E2%98%83%20%2F%3F"));
        assertEquals("file:///tmp/a%20b%23c", Uri.fromFile(new File("/tmp/a b#c")).toString());
        assertEquals("/a/b", Uri.parse("relative:/a%2Fb").getPath());
        assertEquals(Arrays.asList("a/b"), Uri.parse("relative:/a%2Fb").getPathSegments());
        assertEquals("+", Uri.parse("https://host/?q=%2B").getQueryParameter("q"));
        assertEquals(" ", Uri.parse("https://host/?q=+").getQueryParameter("q"));
        assertEquals("https://host/a%2Fb?x=a%26b", new Uri.Builder().scheme("https")
                     .authority("host").appendPath("a/b").appendQueryParameter("x", "a&b").build().toString());
        assertEquals("relative path", Uri.parse("relative path").getPath());
    }
}
