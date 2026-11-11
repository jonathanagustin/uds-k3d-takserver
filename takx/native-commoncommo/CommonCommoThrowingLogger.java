// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.commoncommo.Commo;
import java.io.ByteArrayInputStream;
import java.security.KeyStore;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

/** Real user-logger exceptions must not poison constructor/API/native lifecycle. */
public final class CommonCommoThrowingLogger {
    public static void main(String[] args) throws Exception {
        AtomicInteger calls = new AtomicInteger();
        for (int repeat = 0; repeat < 3; repeat++) {
            int before = calls.get();
            Commo commo = new Commo((level, type, message, detail) -> {
                calls.incrementAndGet();
                throw new IllegalStateException("intentional logger callback failure");
            }, "throwing-logger-" + repeat, "THROWING LOGGER");
            try {
                if (calls.get() <= before) throw new AssertionError("throwing logger not exercised");
                commo.setCallsign("USABLE AFTER THROWING LOGGER");
                String password = UUID.randomUUID().toString();
                byte[] certificate = commo.generateSelfSignedCert(password);
                KeyStore store = KeyStore.getInstance("PKCS12");
                store.load(new ByteArrayInputStream(certificate), password.toCharArray());
                if (store.size() == 0) throw new AssertionError("native API not usable after logger exception");
            } finally {
                commo.shutdown();
            }
        }
        if (calls.get() < 3) throw new AssertionError("logger exceptions not exercised repeatedly");
        System.out.println("PASS real throwing logger isolated; constructor, callsign, native PKCS12 and repeated shutdown usable");
    }
}
