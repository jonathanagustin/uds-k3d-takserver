// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import gov.tak.api.cot.detail.ICotDetailHandler;
import gov.tak.api.cot.detail.VehicleModelDetailHandler;
import gov.tak.api.cot.event.CotDetail;
import gov.tak.api.cot.event.CotEvent;
import java.nio.file.*;

public final class VehicleModelControls {
    static int checks;
    static void check(boolean value, String message) { checks++; if (!value) throw new AssertionError(message); }
    static final class Item { String category, name; boolean outline, denied; int color = -1, writes; }
    static final class Adapter implements VehicleModelDetailHandler.Interop<Item> {
        RuntimeException failure;
        public boolean isVehicleModel(Item item) { return item.name != null; }
        public boolean setVehicleInfo(Item item, String category, String name) {
            if (failure != null) throw failure;
            if (item.denied) return false;
            item.category = category; item.name = name; item.writes++; return true;
        }
        public String getVehicleName(Item item) { return item.name; }
        public String getVehicleCategory(Item item) { return item.category; }
        public void setShowOutline(Item item, boolean enabled) { item.outline = enabled; item.writes++; }
        public boolean getShowOutline(Item item) { return item.outline; }
        public void setColor(Item item, int color) { item.color = color; item.writes++; }
        public int getColor(Item item) { return item.color; }
    }
    static CotDetail model(String category, String name) {
        CotDetail result = new CotDetail("model"); result.setAttribute("type", "vehicle");
        if (category != null) result.setAttribute("category", category);
        if (name != null) result.setAttribute("name", name);
        result.setAttribute("outline", "true"); return result;
    }
    static CotDetail color(String tag, String value) {
        CotDetail result = new CotDetail(tag); if (value != null) result.setAttribute("value", value); return result;
    }
    static CotEvent event(CotDetail... children) {
        CotEvent result = new CotEvent(); CotDetail root = new CotDetail("detail");
        for (CotDetail child : children) root.addChild(child); result.setDetail(root); return result;
    }
    public static void main(String[] args) throws Exception {
        Adapter adapter = new Adapter(); VehicleModelDetailHandler<Item> handler = new VehicleModelDetailHandler<>(adapter);
        check(handler.getDetailNames().size() == 3, "detail names");
        try { handler.getDetailNames().add("foreign"); throw new AssertionError("mutable detail names"); }
        catch (UnsupportedOperationException expected) { checks++; }
        Item item = new Item();
        check(handler.toItemMetadata(null, null, null, model("Air", "HH-60")) == ICotDetailHandler.ImportResult.IGNORE, "null target");
        CotDetail wrong = model("Air", "HH-60"); wrong.setAttribute("type", "other");
        check(handler.toItemMetadata(item, null, null, wrong) == ICotDetailHandler.ImportResult.IGNORE && item.writes == 0, "other model type");
        check(!handler.isSupported(item, null, null, wrong), "unsupported foreign model");
        for (String bad : new String[]{null, "", "  "}) {
            check(handler.toItemMetadata(item, null, null, model(bad, "HH-60")) == ICotDetailHandler.ImportResult.FAILURE && item.writes == 0, "bad category");
            check(handler.toItemMetadata(item, null, null, model("Air", bad)) == ICotDetailHandler.ImportResult.FAILURE && item.writes == 0, "bad name");
        }
        item.denied = true;
        check(handler.toItemMetadata(item, null, null, model("Air", "HH-60")) == ICotDetailHandler.ImportResult.FAILURE && item.writes == 0, "asset refusal");
        item.denied = false;
        CotDetail good = model("Air", "HH-60"); CotEvent incoming = event(color("strokeColor", "-16777216"), good, color("fillColor", "0xFF123456"));
        check(handler.toItemMetadata(item, null, incoming, incoming.getDetail().getFirstChildByName("strokeColor")) == ICotDetailHandler.ImportResult.SUCCESS && item.color == 0xFF123456, "color before model and fill precedence");
        check(handler.toItemMetadata(item, null, incoming, good) == ICotDetailHandler.ImportResult.SUCCESS, "valid model");
        check(item.name.equals("HH-60") && item.category.equals("Air") && item.outline && item.color == 0xFF123456, "actual metadata");
        CotDetail exported = new CotDetail("detail"); check(handler.toCotDetail(item, null, null, exported), "export");
        check("vehicle".equals(exported.getFirstChildByName("model").getAttribute("type")), "wire type");
        check("HH-60".equals(exported.getFirstChildByName("model").getAttribute("name")), "wire name");
        check("Air".equals(exported.getFirstChildByName("model").getAttribute("category")), "wire category");
        check("true".equals(exported.getFirstChildByName("model").getAttribute("outline")), "wire outline");
        check(Integer.toString(item.color).equals(exported.getFirstChildByName("fillColor").getAttribute("value")), "wire color");
        Item roundtrip = new Item(); CotEvent roundEvent = new CotEvent(); roundEvent.setDetail(exported);
        check(handler.toItemMetadata(roundtrip, null, roundEvent, exported.getFirstChildByName("model")) == ICotDetailHandler.ImportResult.SUCCESS && roundtrip.color == item.color && roundtrip.name.equals(item.name), "round trip");
        for (String bad : new String[]{null, "", "NaN", "4294967296", "-2147483649", "0xFFFFFFFFF", "1.5"}) {
            int before = item.writes;
            check(handler.toItemMetadata(item, null, null, color("fillColor", bad)) == ICotDetailHandler.ImportResult.FAILURE && item.writes == before, "bad color mutation");
        }
        for (String valid : new String[]{"4294967295", "-1", "0xFFFFFFFF"}) {
            check(handler.toItemMetadata(item, null, null, color("fillColor", valid)) == ICotDetailHandler.ImportResult.SUCCESS && item.color == -1, "ARGB representations");
        }
        RuntimeException primary = new IllegalStateException("owned adapter refusal"); adapter.failure = primary;
        try { handler.toItemMetadata(item, null, null, good); throw new AssertionError("missing adapter error"); }
        catch (RuntimeException caught) { check(caught == primary, "primary preserved"); }
        String maps = Files.readString(Path.of("/proc/self/maps"));
        check(!maps.contains("libtakengine") && !maps.contains("libgdalalljni"), "metadata controls load no SDK native libraries");
        System.out.println("VEHICLE_MODEL_CONTROLS_PASS checks=" + checks);
    }
}
