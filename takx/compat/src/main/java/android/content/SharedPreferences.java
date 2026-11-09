// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.content;

import java.util.Map;
import java.util.Set;

/** Limited desktop preference contract; apply is synchronous and durable. */
public interface SharedPreferences {
    Map<String, ?> getAll();
    String getString(String key, String fallback);
    Set<String> getStringSet(String key, Set<String> fallback);
    int getInt(String key, int fallback);
    long getLong(String key, long fallback);
    float getFloat(String key, float fallback);
    boolean getBoolean(String key, boolean fallback);
    boolean contains(String key);
    Editor edit();
    void registerOnSharedPreferenceChangeListener(OnSharedPreferenceChangeListener listener);
    void unregisterOnSharedPreferenceChangeListener(OnSharedPreferenceChangeListener listener);
    interface OnSharedPreferenceChangeListener {
        void onSharedPreferenceChanged(SharedPreferences preferences, String key);
    }
    interface Editor {
        Editor putString(String key, String value);
        Editor putStringSet(String key, Set<String> values);
        Editor putInt(String key, int value);
        Editor putLong(String key, long value);
        Editor putFloat(String key, float value);
        Editor putBoolean(String key, boolean value);
        Editor remove(String key);
        Editor clear();
        boolean commit();
        void apply();
    }
}
