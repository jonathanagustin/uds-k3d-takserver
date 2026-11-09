// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: Apache-2.0
package android.os;

import java.util.HashMap;
import java.util.Map;

/** In-memory int/byte-array values only. No Bundle serialization or IPC. */
public final class Bundle {
    private final Map<String, Object> values = new HashMap<>();
    public void putInt(String key, int value) { values.put(key, value); }
    public int getInt(String key) { return getInt(key, 0); }
    public int getInt(String key, int fallback) {
        Object value = values.get(key);
        return value instanceof Integer ? (Integer) value : fallback;
    }
    public void putByteArray(String key, byte[] value) { values.put(key, value); }
    public byte[] getByteArray(String key) {
        Object value = values.get(key);
        return value instanceof byte[] ? (byte[]) value : null;
    }
}
