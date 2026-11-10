// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;

/** JDK-only classloader proof. No GDAL, Kernel, client or native class is loaded. */
public final class ResourceLookupProbe {
    public static void main(String[] args) throws Exception {
        int count = 0;
        for (String line : Files.readAllLines(Path.of(args[0]))) {
            String[] fields = line.split("\t", -1);
            try (InputStream stream = ResourceLookupProbe.class.getClassLoader()
                    .getResourceAsStream("gdal/data/" + fields[0])) {
                if (stream == null) throw new AssertionError("Missing resource: " + fields[0]);
                byte[] digest = MessageDigest.getInstance("SHA-256").digest(stream.readAllBytes());
                StringBuilder hex = new StringBuilder();
                for (byte value : digest) hex.append(String.format("%02x", value & 255));
                if (!hex.toString().equals(fields[1])) throw new AssertionError("Wrong resource bytes: " + fields[0]);
                count++;
            }
        }
        if (count != 93) throw new AssertionError("Expected 93 resources");
        System.out.println("PASS 93 JDK classloader resource lookups");
    }
}
