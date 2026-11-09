// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import android.util.Pair;
import java.lang.reflect.Modifier;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;

public final class PairCompatibilityTest {
    private static int checks;
    private static void check(boolean value) {
        checks++;
        if (!value) throw new AssertionError("Pair contract check " + checks);
    }
    public static void main(String[] args) throws Exception {
        Object[] values = {null, "alpha", "beta", 1, 2, new int[]{1}, new Object()};
        for (Object first : values) for (Object second : values) {
            Pair<Object, Object> pair = Pair.create(first, second);
            check(pair.first == first && pair.second == second);
            check(pair.toString().equals("Pair{" + first + " " + second + "}"));
            check(pair.hashCode() == (Objects.hashCode(first) ^ Objects.hashCode(second)));
            check(!pair.equals(null) && !pair.equals("unrelated"));
            for (Object otherFirst : values) for (Object otherSecond : values) {
                Pair<Object, Object> other = new Pair<>(otherFirst, otherSecond);
                boolean expected = Objects.equals(otherFirst, first) && Objects.equals(otherSecond, second);
                check(pair.equals(other) == expected);
                if (expected) check(pair.hashCode() == other.hashCode());
            }
            Map<Pair<Object, Object>, String> map = new HashMap<>();
            map.put(pair, "present");
            check("present".equals(map.get(new Pair<>(first, second))));
        }
        Pair<Number, CharSequence> typed = Pair.create(42, "value");
        check(typed.first.intValue() == 42 && typed.second.length() == 5);
        Pair<String, Integer> ordered = Pair.create("key", 4);
        check(!ordered.equals(Pair.create(4, "key")));
        check(ordered.hashCode() == Pair.create(4, "key").hashCode());
        check(ordered.equals(new Pair<String, Integer>("key", 4) {}));
        check(Modifier.isFinal(Pair.class.getField("first").getModifiers()));
        check(Modifier.isFinal(Pair.class.getField("second").getModifiers()));
        check(!Modifier.isFinal(Pair.class.getModifiers()));
        System.out.println(checks + " AOSP Pair contract checks passed");
    }
}
