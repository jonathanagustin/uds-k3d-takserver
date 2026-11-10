// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import com.atakmap.commoncommo.Commo;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

/** Linux-only, read-only signal observation: never installs a signal handler. */
public final class CommonCommoSignalSmoke {
    private static Map<String, Boolean> disposition() throws Exception {
        Map<String, Boolean> state = new LinkedHashMap<>();
        for (String line : Files.readAllLines(Path.of("/proc/self/status"))) {
            String[] fields = line.trim().split("\\s+");
            if (fields[0].equals("SigBlk:") || fields[0].equals("SigIgn:") || fields[0].equals("SigCgt:")) {
                state.put(fields[0], (Long.parseUnsignedLong(fields[1], 16) & (1L << 12)) != 0);
            }
        }
        if (state.size() != 3) throw new AssertionError("Linux SIGPIPE disposition is unavailable");
        return state;
    }

    private static void unchanged(Map<String, Boolean> expected, String stage) throws Exception {
        if (!expected.equals(disposition())) throw new AssertionError("SIGPIPE disposition changed at " + stage);
    }

    public static void main(String[] args) throws Exception {
        Map<String, Boolean> expected = disposition();
        if (!expected.get("SigCgt:") || expected.get("SigIgn:") || expected.get("SigBlk:")) {
            throw new AssertionError("Expected the ordinary JVM caught/unblocked SIGPIPE disposition");
        }
        Class.forName("com.atakmap.commoncommo.Commo");
        unchanged(expected, "native initialization");
        for (int i = 0; i < 3; i++) {
            Commo commo = new Commo((level, type, message, detail) -> {}, "signal-probe-" + i, "SIGNAL PROBE");
            unchanged(expected, "construction");
            commo.shutdown();
            unchanged(expected, "shutdown");
        }
        // A real reset peer after native cleanup must yield a Java exception,
        // not terminate this JVM. No process-wide signal policy is changed.
        try (ServerSocket server = new ServerSocket(0, 1, InetAddress.getLoopbackAddress());
                Socket writer = new Socket(server.getInetAddress(), server.getLocalPort());
                Socket peer = server.accept()) {
            peer.setSoLinger(true, 0);
            peer.close();
            boolean failed = false;
            for (int i = 0; i < 10 && !failed; i++) {
                try { writer.getOutputStream().write(new byte[4096]); }
                catch (SocketException expectedFailure) { failed = true; }
                if (!failed) Thread.sleep(20);
            }
            if (!failed) throw new AssertionError("Reset-peer write did not fail within its bound");
        }
        unchanged(expected, "ordinary Java reset-peer write");
        System.out.println("PASS SIGPIPE disposition preserved through native initialization, three shutdowns and reset-peer Java write");
    }
}
