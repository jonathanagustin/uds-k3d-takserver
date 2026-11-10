// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import java.io.*;
import java.net.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;

/** Fresh application-data probe; a successful TCP connect alone never passes. */
public final class ProtocolProbe {
    private static byte[] readExact(DataInputStream input, int length) throws IOException {
        byte[] bytes = new byte[length];
        int offset = 0;
        try {
            while (offset < length) {
                int count = input.read(bytes, offset, length - offset);
                if (count < 0) throw new EOFException();
                offset += count;
            }
        } catch (IOException error) {
            if (offset != 0) throw new IllegalStateException("partial application response", error);
            throw error;
        }
        return bytes;
    }

    private static String readGreeting(DataInputStream input) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try {
            while (bytes.size() <= 16384) {
                int value = input.read();
                if (value < 0) throw new EOFException();
                if (value == '\n') return bytes.toString(StandardCharsets.US_ASCII).trim();
                bytes.write(value);
            }
            throw new IllegalStateException("oversize application greeting");
        } catch (IOException error) {
            if (bytes.size() != 0) throw new IllegalStateException("partial application greeting", error);
            throw error;
        }
    }

    public static void main(String[] args) {
        try {
            if (args.length == 1 && args[0].equals("dns")) {
                InetAddress.getByName("kubernetes.default.svc.cluster.local");
                System.out.println("DNS_RESPONSE");
                return;
            }
            if (args.length != 3) throw new IllegalArgumentException("protocol, IP, port required");
            try (Socket socket = new Socket()) {
                socket.connect(new InetSocketAddress(args[1], Integer.parseInt(args[2])), 3000);
                socket.setSoTimeout(3000);
                DataInputStream input = new DataInputStream(socket.getInputStream());
                switch (args[0]) {
                    case "ignite": {
                        // Apache Ignite2.17.0 NodeIdMessage: little-endian short(-1), UUID16bytes.
                        byte[] reply = readExact(input, 18);
                        if (reply.length != 18) throw new EOFException();
                        if (reply[0] != (byte)255 || reply[1] != (byte)255)
                            throw new IllegalStateException("unexpected Ignite message");
                        boolean nonzero = false;
                        for (int i = 2; i < reply.length; i++) nonzero |= reply[i] != 0;
                        if (!nonzero) throw new IllegalStateException("nil Ignite node identity");
                        break;
                    }
                    case "postgres": {
                        // PostgreSQL protocol SSLRequest, not authentication or a database write.
                        socket.getOutputStream().write(ByteBuffer.allocate(8).putInt(8).putInt(80877103).array());
                        int reply = input.read();
                        if (reply < 0) throw new EOFException();
                        if (reply != 'S' && reply != 'N') throw new IllegalStateException("unexpected PostgreSQL reply");
                        break;
                    }
                    case "nats": {
                        String greeting = readGreeting(input);
                        if (!greeting.startsWith("INFO {") || !greeting.endsWith("}")
                                || !greeting.contains("\"server_id\"") || !greeting.contains("\"version\""))
                            throw new IllegalStateException("unexpected NATS greeting");
                        break;
                    }
                    default: throw new IllegalArgumentException("unknown protocol");
                }
                System.out.println("APPLICATION_RESPONSE");
            }
        } catch (IOException error) {
            // Negative evidence requires a separate DNS control and positive before/after.
            System.out.println("TRANSPORT_REJECTED");
            System.exit(10);
        } catch (Exception error) {
            // Wrong service/protocol, malformed data or local execution failure is NOT a denial.
            System.err.println("PROBE_INVALID");
            System.exit(20);
        }
    }
}
