// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package sparse;

import android.util.SparseArray;
import android.util.SparseBooleanArray;
import java.util.Objects;
import java.util.Random;
import java.util.TreeMap;

public final class SparseCompatibilityTest {
    static int checks;
    static void check(boolean value) { checks++; if (!value) throw new AssertionError("check " + checks); }
    static void invalid(Runnable action) {
        try { action.run(); throw new AssertionError("missing bounds failure"); }
        catch (ArrayIndexOutOfBoundsException expected) { checks++; }
    }
    static void verify(SparseArray<String> actual, TreeMap<Integer, String> expected) {
        check(actual.size() == expected.size());
        int index = 0;
        for (var item : expected.entrySet()) {
            check(actual.keyAt(index) == item.getKey());
            check(Objects.equals(actual.valueAt(index), item.getValue()));
            check(actual.contains(item.getKey()));
            check(actual.indexOfKey(item.getKey()) == index);
            check(Objects.equals(actual.get(item.getKey(), "missing"), item.getValue()));
            index++;
        }
        check(actual.contentEquals(actual.clone()));
        check(actual.contentHashCode() == actual.clone().contentHashCode());
        check(actual.toString().equals(expected.toString()));
    }
    static void verify(SparseBooleanArray actual, TreeMap<Integer, Boolean> expected) {
        check(actual.size() == expected.size());
        int index = 0;
        for (var item : expected.entrySet()) {
            check(actual.keyAt(index) == item.getKey());
            check(actual.valueAt(index) == item.getValue());
            check(actual.indexOfKey(item.getKey()) == index);
            check(actual.get(item.getKey(), !item.getValue()) == item.getValue());
            index++;
        }
        check(actual.equals(actual.clone()));
        check(actual.hashCode() == actual.clone().hashCode());
        check(actual.toString().equals(expected.toString()));
    }
    public static void main(String[] args) {
        SparseArray<String> array = new SparseArray<>(0);
        SparseBooleanArray bool = new SparseBooleanArray(0);
        TreeMap<Integer, String> model = new TreeMap<>();
        TreeMap<Integer, Boolean> bits = new TreeMap<>();
        Random random = new Random(0x535041525345L);
        for (int step = 0; step < 600; step++) {
            int key = random.nextInt(41) - 20;
            String value = step % 7 == 0 ? null : "v" + step;
            boolean bit = random.nextBoolean();
            switch (random.nextInt(6)) {
                case 0: array.put(key, value); model.put(key, value); bool.put(key, bit); bits.put(key, bit); break;
                case 1: array.append(key, value); model.put(key, value); bool.append(key, bit); bits.put(key, bit); break;
                case 2: array.delete(key); model.remove(key); bool.delete(key); bits.remove(key); break;
                case 3:
                    check(Objects.equals(array.removeReturnOld(key), model.remove(key)));
                    bool.delete(key); bits.remove(key); break;
                case 4:
                    if (!model.isEmpty()) { int i = random.nextInt(array.size()); model.remove(array.keyAt(i)); array.removeAt(i); }
                    if (!bits.isEmpty()) { int i = random.nextInt(bool.size()); bits.remove(bool.keyAt(i)); bool.removeAt(i); }
                    break;
                default:
                    if (!model.isEmpty()) { int i = random.nextInt(array.size()); model.put(array.keyAt(i), value); array.setValueAt(i, value); }
                    if (!bits.isEmpty()) { int i = random.nextInt(bool.size()); bits.put(bool.keyAt(i), bit); bool.setValueAt(i, bit); }
            }
            verify(array, model); verify(bool, bits);
        }
        SparseArray<String> clone = array.clone();
        clone.set(Integer.MIN_VALUE, "clone"); check(!array.contains(Integer.MIN_VALUE));
        array.put(Integer.MAX_VALUE, null); check(array.contains(Integer.MAX_VALUE)); check(array.get(Integer.MAX_VALUE, "default") == null);
        check(array.get(Integer.MIN_VALUE, "default").equals("default"));
        SparseArray<String> identity = new SparseArray<>();
        String first = new String("same"), equal = new String("same");
        identity.put(10, first); check(identity.indexOfValue(equal) < 0); check(identity.indexOfValue(first) == 0);
        check(identity.indexOfValueByValue(equal) == 0);
        identity.put(20, null); check(identity.indexOfValue(null) == 1);
        identity.append(30, "end"); identity.removeAtRange(0, 2); check(identity.size() == 1 && identity.keyAt(0) == 30);
        identity.clear(); check(identity.size() == 0 && identity.toString().equals("{}"));
        SparseArray<Object> self = new SparseArray<>(); self.put(1, self); check(self.toString().equals("{1=(this Map)}"));
        SparseBooleanArray ordered = new SparseBooleanArray(); ordered.put(1, true); ordered.put(5, false); ordered.setKeyAt(1, 6);
        check(ordered.keyAt(1) == 6 && !ordered.valueAt(1)); check(ordered.indexOfValue(false) == 1);
        check(!ordered.get(99));
        ordered.clear(); check(ordered.size() == 0); check(ordered.get(1, true)); check(!ordered.get(1));
        invalid(() -> identity.keyAt(0)); invalid(() -> identity.valueAt(0)); invalid(() -> identity.setValueAt(0, "x")); invalid(() -> identity.removeAt(0));
        invalid(() -> ordered.keyAt(0)); invalid(() -> ordered.valueAt(0)); invalid(() -> ordered.setValueAt(0, true));
        SparseArray<String> holes = new SparseArray<>(2); holes.put(1, "one"); holes.put(3, "three"); holes.delete(1);
        SparseArray<String> dirtyClone = holes.clone(); dirtyClone.put(2, "two");
        check(holes.size() == 1 && holes.get(2) == null); check(dirtyClone.size() == 2);
        holes.put(1, "one"); check(holes.indexOfKey(2) == ~1); check(holes.indexOfKey(0) == ~0); check(holes.indexOfKey(4) == ~2);
        SparseBooleanArray boolClone = ordered.clone(); boolClone.put(Integer.MIN_VALUE, true);
        check(ordered.size() == 0 && boolClone.size() == 1); check(boolClone.indexOfKey(Integer.MAX_VALUE) == ~1);
        check(!array.contentEquals(null)); check(!ordered.equals(null)); check(!ordered.equals(new Object()));
        System.out.println("PASS sparse containers: " + checks + " checks");
    }
}
