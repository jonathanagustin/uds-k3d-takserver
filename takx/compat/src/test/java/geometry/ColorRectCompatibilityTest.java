// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package geometry;

import android.graphics.Color;
import android.graphics.Rect;
import java.util.Locale;
import java.util.Random;

public final class ColorRectCompatibilityTest {
    private static int checks;
    private static void check(boolean value) {
        checks++;
        if (!value) throw new AssertionError("color/rect check " + checks);
    }
    private static void same(Rect a, gov.tak.platform.graphics.Rect b) {
        check(a.left == b.left && a.top == b.top && a.right == b.right && a.bottom == b.bottom);
        check(a.width() == b.width() && a.height() == b.height());
        check(a.centerX() == b.centerX() && a.centerY() == b.centerY());
        check(a.exactCenterX() == b.exactCenterX() && a.exactCenterY() == b.exactCenterY());
        check(a.isEmpty() == b.isEmpty());
        check(a.hashCode() == b.hashCode());
    }
    private static Object parse(boolean oracle, String text) {
        try { return oracle ? gov.tak.platform.graphics.Color.parseColor(text) : Color.parseColor(text); }
        catch (RuntimeException e) { return e.getClass(); }
    }
    public static void main(String[] args) {
        Random random = new Random(0x524742);
        for (int i = 0; i < 1000; i++) {
            int packed = random.nextInt();
            check(Color.alpha(packed) == gov.tak.platform.graphics.Color.alpha(packed));
            check(Color.red(packed) == gov.tak.platform.graphics.Color.red(packed));
            check(Color.green(packed) == gov.tak.platform.graphics.Color.green(packed));
            check(Color.blue(packed) == gov.tak.platform.graphics.Color.blue(packed));
            check(Color.argb(Color.alpha(packed), Color.red(packed), Color.green(packed), Color.blue(packed)) == packed);
            check(Color.rgb(Color.red(packed), Color.green(packed), Color.blue(packed)) == (packed | 0xff000000));
            int a = random.nextInt(), r = random.nextInt(), g = random.nextInt(), b = random.nextInt();
            check(Color.argb(a, r, g, b) == ((a << 24) | (r << 16) | (g << 8) | b));
        }
        check(Color.argb(0, 0, 0, -1) == -1); // documented raw shifts, no silent clamping
        check(Color.argb(256, 256, 256, 256) == 0x01010100);
        String[] inputs = {"black", "DARKGRAY", "gray", "lightgray", "white", "red", "green", "blue",
            "yellow", "cyan", "magenta", "aqua", "fuchsia", "darkgrey", "grey", "lightgrey", "lime",
            "maroon", "navy", "olive", "purple", "silver", "teal", "#000000", "#ffffff", "#123456",
            "#80123456", "#FFFFFFFF", "#00000000", "", null, "#", "#fff", "#ffff", "#1234567",
            "#123456789", "#GG0000", " red", "red ", "transparent", "unknown", "#+12345", "#-12345"};
        Locale previous = Locale.getDefault();
        try {
            Locale.setDefault(Locale.forLanguageTag("tr-TR"));
            for (String input : inputs) check(parse(false, input).equals(parse(true, input)));
            check(Color.parseColor("WHITE") == Color.WHITE);
            check(Color.parseColor("#123456") == 0xff123456);
            check(Color.parseColor("#80123456") == 0x80123456);
        } finally { Locale.setDefault(previous); }
        check(Color.TRANSPARENT == 0 && Color.BLACK == 0xff000000 && Color.WHITE == -1);

        for (int i = 0; i < 500; i++) {
            int l=random.nextInt(), t=random.nextInt(), r=random.nextInt(), b=random.nextInt();
            Rect x=new Rect(l,t,r,b);
            gov.tak.platform.graphics.Rect y=new gov.tak.platform.graphics.Rect(l,t,r,b);
            same(x,y); check(x.equals(new Rect(x))); check(!x.equals(y)); check(!x.equals(null));
            x.sort(); y.sort(); same(x,y);
            check(x.contains(l,t) == y.contains(l,t)); check(x.contains(l,t,r,b) == y.contains(l,t,r,b));
            check(x.intersect(l,t,r,b) == y.intersect(l,t,r,b)); same(x,y);
            x.offset(l,t); y.offset(l,t); same(x,y);
            x.offsetTo(r,b); y.offsetTo(r,b); same(x,y);
            x.inset(l,t); y.inset(l,t); same(x,y);
            x.inset(l,t,r,b); y.inset(l,t,r,b); same(x,y);
            x.union(l,t,r,b); y.union(l,t,r,b); same(x,y);
            x.union(r,b); y.union(r,b); same(x,y);
            check(x.intersects(l,t,r,b) == y.intersects(l,t,r,b));
            x.setEmpty(); y.setEmpty(); same(x,y);
            x.set(l,t,r,b); y.set(l,t,r,b); same(x,y);
        }
        Rect x=new Rect(-2,-3,8,7), copy=new Rect(x);
        x.offset(1,1); check(copy.left == -2); x.set(copy); check(x.equals(copy));
        check(x.contains(-2,-3)); check(!x.contains(8,0) && !x.contains(0,7));
        check(!x.intersect(new Rect(8,-3,10,7))); check(x.equals(copy));
        check(x.intersect(new Rect(0,0,10,10))); check(x.equals(new Rect(0,0,8,7)));
        check(!x.setIntersect(new Rect(0,0,1,1),new Rect(2,2,3,3))); check(x.equals(new Rect(0,0,8,7)));
        check(x.setIntersect(new Rect(0,0,3,3),new Rect(1,1,4,4))); check(x.equals(new Rect(1,1,3,3)));
        check(x.contains(new Rect(1,1,2,2))); check(Rect.intersects(x,new Rect(2,2,5,5)));
        x.union(new Rect(-5,-5,0,0)); check(x.equals(new Rect(-5,-5,3,3)));
        check(new Rect((Rect)null).isEmpty());
        Rect extreme=new Rect(Integer.MIN_VALUE,0,Integer.MAX_VALUE,1);
        check(extreme.width() == -1); check(extreme.centerX() == -1); check(extreme.exactCenterX() == -.5f);
        Rect negative=new Rect(-4,-5,-1,-2); check(negative.centerX() == -3 && negative.centerY() == -4);
        System.out.println("Color/Rect compatibility: " + checks + " checks passed");
    }
}
