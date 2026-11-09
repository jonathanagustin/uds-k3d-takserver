// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: Apache-2.0
// AOSP Android 14: IP_ADDRESS fields only; no pattern algorithm changes.
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
package android.util;

import java.util.regex.Pattern;

/** Legacy AOSP IPv4 matching only; this is not the complete Android Patterns API. */
public final class Patterns {
    private Patterns() {}
    private static final String IP_ADDRESS_STRING =
            "((25[0-5]|2[0-4][0-9]|[0-1][0-9]{2}|[1-9][0-9]|[1-9])\\.(25[0-5]|2[0-4]"
            + "[0-9]|[0-1][0-9]{2}|[1-9][0-9]|[1-9]|0)\\.(25[0-5]|2[0-4][0-9]|[0-1]"
            + "[0-9]{2}|[1-9][0-9]|[1-9]|0)\\.(25[0-5]|2[0-4][0-9]|[0-1][0-9]{2}"
            + "|[1-9][0-9]|[0-9]))";

    /**
     * Kept for backward compatibility reasons. It does not match IPv6 addresses.
     *
     * @deprecated Please use {@link android.net.InetAddresses#isNumericAddress(String)} instead.
     */
    @Deprecated
    public static final Pattern IP_ADDRESS = Pattern.compile(IP_ADDRESS_STRING);

}
