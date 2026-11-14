// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package gov.tak.api.cot.detail;

import java.util.Objects;
import java.util.Set;
import gov.tak.api.cot.event.CotDetail;
import gov.tak.api.cot.event.CotEvent;
import gov.tak.api.util.AttributeSet;

/**
 * Project vehicle metadata wire profile, derived from the public Android CoT
 * model detail and the pinned TAKX Interop caller. This does not create meshes
 * or reproduce a private Kernel implementation.
 */
public final class VehicleModelDetailHandler<T> implements ICotDetailHandler2 {
    public interface Interop<T> {
        boolean isVehicleModel(T item);
        boolean setVehicleInfo(T item, String category, String name);
        String getVehicleName(T item);
        String getVehicleCategory(T item);
        void setShowOutline(T item, boolean enabled);
        boolean getShowOutline(T item);
        void setColor(T item, int color);
        int getColor(T item);
    }

    private static final Set<String> NAMES = Set.of("model", "strokeColor", "fillColor");
    private final Interop<T> interop;

    public VehicleModelDetailHandler(Interop<T> interop) {
        this.interop = Objects.requireNonNull(interop, "interop");
    }

    private T item(Object value) { return (T) value; }

    @Override public Set<String> getDetailNames() { return NAMES; }

    private static boolean named(String value) {
        return value != null && !value.trim().isEmpty();
    }

    private static boolean vehicle(CotDetail detail) {
        return detail != null && "model".equals(detail.getElementName()) &&
                "vehicle".equalsIgnoreCase(detail.getAttribute("type"));
    }

    private static boolean validModel(CotDetail detail) {
        return vehicle(detail) && named(detail.getAttribute("category")) && named(detail.getAttribute("name"));
    }

    private static CotDetail incomingModel(CotEvent event) {
        return event == null || event.getDetail() == null ? null :
                event.getDetail().getFirstChildByName("model");
    }

    @Override public boolean isSupported(Object value, AttributeSet attrs, CotEvent event, CotDetail detail) {
        if (value == null) return false;
        if (detail != null && "model".equals(detail.getElementName())) return vehicle(detail);
        return (detail == null || NAMES.contains(detail.getElementName())) &&
                (interop.isVehicleModel(item(value)) || validModel(incomingModel(event)));
    }

    private static int color(CotDetail detail) {
        String value = detail.getAttribute("value");
        if (value == null || value.length() > 12) throw new IllegalArgumentException("invalid ARGB color");
        long parsed;
        if (value.matches("0[xX][0-9a-fA-F]{1,8}")) parsed = Long.parseLong(value.substring(2), 16);
        else if (value.matches("-?[0-9]{1,10}")) parsed = Long.parseLong(value, 10);
        else throw new IllegalArgumentException("invalid ARGB color");
        if (parsed < Integer.MIN_VALUE || parsed > 0xffffffffL) throw new IllegalArgumentException("ARGB color range");
        return (int) parsed;
    }

    /** A filled model has one color: fill takes precedence over stroke. */
    private static Integer incomingColor(CotEvent event) {
        if (event == null || event.getDetail() == null) return null;
        CotDetail root = event.getDetail();
        CotDetail detail = root.getFirstChildByName("fillColor");
        if (detail == null) detail = root.getFirstChildByName("strokeColor");
        return detail == null ? null : color(detail);
    }

    @Override public ICotDetailHandler.ImportResult toItemMetadata(Object value, AttributeSet attrs,
                                                                 CotEvent event, CotDetail detail) {
        if (value == null || detail == null || !NAMES.contains(detail.getElementName()))
            return ICotDetailHandler.ImportResult.IGNORE;
        T target = item(value);
        if ("model".equals(detail.getElementName())) {
            if (!vehicle(detail)) return ICotDetailHandler.ImportResult.IGNORE;
            if (!validModel(detail)) return ICotDetailHandler.ImportResult.FAILURE;
            final Integer incoming;
            try { incoming = incomingColor(event); }
            catch (IllegalArgumentException error) { return ICotDetailHandler.ImportResult.FAILURE; }
            if (!interop.setVehicleInfo(target, detail.getAttribute("category"), detail.getAttribute("name")))
                return ICotDetailHandler.ImportResult.FAILURE;
            interop.setShowOutline(target, Boolean.parseBoolean(detail.getAttribute("outline")));
            if (incoming != null) interop.setColor(target, incoming);
            return ICotDetailHandler.ImportResult.SUCCESS;
        }
        if (!interop.isVehicleModel(target) && !validModel(incomingModel(event)))
            return ICotDetailHandler.ImportResult.IGNORE;
        final int incoming;
        try {
            Integer preferred = incomingColor(event);
            incoming = preferred == null ? color(detail) : preferred;
        } catch (IllegalArgumentException error) { return ICotDetailHandler.ImportResult.FAILURE; }
        interop.setColor(target, incoming);
        return ICotDetailHandler.ImportResult.SUCCESS;
    }

    @Override public boolean toCotDetail(Object value, AttributeSet attrs, CotEvent event, CotDetail root) {
        if (value == null || !interop.isVehicleModel(item(value))) return false;
        T target = item(value);
        String category = interop.getVehicleCategory(target), name = interop.getVehicleName(target);
        if (!named(category) || !named(name)) return false;
        CotDetail model = new CotDetail("model");
        model.setAttribute("type", "vehicle");
        model.setAttribute("category", category);
        model.setAttribute("name", name);
        model.setAttribute("outline", Boolean.toString(interop.getShowOutline(target)));
        String argb = Integer.toString(interop.getColor(target));
        CotDetail stroke = new CotDetail("strokeColor"), fill = new CotDetail("fillColor");
        stroke.setAttribute("value", argb); fill.setAttribute("value", argb);
        root.addChild(model); root.addChild(stroke); root.addChild(fill);
        return true;
    }
}
