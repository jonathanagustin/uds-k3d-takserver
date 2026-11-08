// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import com.atakmap.commoncommo.Commo;
import java.io.ByteArrayInputStream;
import java.security.KeyStore;
import java.util.UUID;

/** Exercises the actual auto-initializing JAR/JNI pair; configures no network interface. */
public final class CommonCommoSmoke {
    public static void main(String[] args) throws Exception {
        Commo commo = new Commo((level, type, message, detail) -> {}, "source-build-smoke", "SOURCE BUILD SMOKE");
        try {
            String password = UUID.randomUUID().toString();
            byte[] certificate = commo.generateSelfSignedCert(password);
            KeyStore store = KeyStore.getInstance("PKCS12");
            store.load(new ByteArrayInputStream(certificate), password.toCharArray());
            if (store.size() == 0) throw new AssertionError("Native-generated PKCS12 is empty");
            System.out.println("PASS native initialization, Commo construction and PKCS12 generation/parsing");
        } finally {
            commo.shutdown();
        }
        System.out.println("PASS native shutdown; no network interfaces configured");
    }
}
