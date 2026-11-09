// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import com.atakmap.commoncommo.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.io.*;
import java.util.UUID;
import java.util.concurrent.*;

/** Actual loopback TCP routing through the source-built Java/JNI/core stack. */
public final class CommonCommoRoutingSmoke {
    private static final String PEER = "route-peer";
    private static final String EVENT = "<event version='2.0' uid='%s' type='a-f-G-U-C' time='2026-01-01T00:00:00Z' start='2026-01-01T00:00:00Z' stale='2099-01-01T00:00:00Z' how='m-g'><point lat='0' lon='0' hae='0' ce='1' le='1'/><detail><contact callsign='%s' endpoint='*:-1:stcp'/></detail></event>";
    private static final class Peer implements AutoCloseable {
        final ServerSocket server = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"));
        final CountDownLatch accepted = new CountDownLatch(1);
        final StringBuffer received = new StringBuffer();
        volatile Socket socket;
        Peer() throws IOException {
            Thread reader = new Thread(() -> {
                try {
                    socket = server.accept(); accepted.countDown();
                    byte[] bytes = new byte[8192]; int n;
                    while ((n = socket.getInputStream().read(bytes)) != -1)
                        received.append(new String(bytes, 0, n, StandardCharsets.UTF_8));
                } catch (IOException expectedOnClose) { }
            });
            reader.setDaemon(true); reader.start();
        }
        void ready() throws Exception { require(accepted.await(10, TimeUnit.SECONDS), "stream did not connect"); }
        void discover(String barrierUid) throws Exception {
            // Both events use one ordered TCP stream. The sentinel's contact
            // callback comes from ContactManager after it processes PEER.
            String events = String.format(EVENT, PEER, "Discovered")
                    + String.format(EVENT, barrierUid, "Discovery barrier");
            socket.getOutputStream().write(events.getBytes(StandardCharsets.UTF_8));
            socket.getOutputStream().flush();
        }
        public void close() throws IOException { server.close(); if (socket != null) socket.close(); }
    }
    private static void require(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
    private static void arrives(Commo commo, Contact contact, Peer expected, Peer other, String phase) throws Exception {
        String marker = "routing-" + phase + "-" + UUID.randomUUID();
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
        do {
            try { commo.sendCoT(contact, String.format(EVENT, marker, "Sender")); }
            catch (CommoException connecting) { }
            Thread.sleep(50);
        } while (!expected.received.toString().contains(marker) && System.nanoTime() < deadline);
        require(expected.received.toString().contains(marker), phase + ": expected stream received no CoT");
        require(!other.received.toString().contains(marker), phase + ": CoT leaked to the wrong stream");
        String wire = expected.received.toString();
        int start = wire.lastIndexOf("<event", wire.indexOf(marker));
        int end = wire.indexOf("</event>", wire.indexOf(marker));
        require(end >= 0, phase + ": incomplete CoT");
        String sent = wire.substring(start, end);
        String callsign = phase.equals("discovery-wins") || phase.equals("remove-keeps-discovery") ? "Discovered" : "Configured";
        require(sent.contains("callsign=\"" + callsign + "\""), phase + ": wrong TAK server recipient callsign");
    }
    private static void awaitDiscovery(Commo commo, Peer server) throws Exception {
        String barrierUid = "discovery-barrier-" + UUID.randomUUID();
        CountDownLatch processed = new CountDownLatch(1);
        ContactPresenceListener listener = new ContactPresenceListener() {
            public void contactAdded(Contact contact) {
                if (barrierUid.equals(contact.contactUID)) processed.countDown();
            }
            public void contactRemoved(Contact contact) { }
        };
        commo.addContactPresenceListener(listener);
        try {
            server.discover(barrierUid);
            require(processed.await(10, TimeUnit.SECONDS), "native contact discovery did not complete");
        } finally { commo.removeContactPresenceListener(listener); }
    }
    public static void main(String[] args) throws Exception {
        Commo commo = new Commo((level, type, message, detail) -> {}, "routing-smoke", "Routing smoke");
        try (Peer a = new Peer(); Peer b = new Peer(); Peer control = new Peer()) {
            CoTMessageType[] types = { CoTMessageType.SITUATIONAL_AWARENESS };
            StreamingNetInterface ia = commo.addStreamingInterface(StreamingTransport.TCP, "127.0.0.1", a.server.getLocalPort(), types, null, null, null, null, null, null);
            StreamingNetInterface ib = commo.addStreamingInterface(StreamingTransport.TCP, "127.0.0.1", b.server.getLocalPort(), types, null, null, null, null, null, null);
            StreamingNetInterface ic = commo.addStreamingInterface(StreamingTransport.TCP, "127.0.0.1", control.server.getLocalPort(), types, null, null, null, null, null, null);
            a.ready(); b.ready(); control.ready();
            Contact peer = commo.configKnownEndpointForContact(PEER, "Configured", ia.streamId);
            try { commo.configKnownEndpointForContact(PEER, "Wrong", "not-a-stream"); throw new AssertionError("unknown stream accepted"); }
            catch (CommoException expected) { }
            arrives(commo, peer, a, b, "fallback-a");
            java.util.Vector<Contact> unavailable = new java.util.Vector<>(java.util.List.of(peer));
            String pointOnly = "point-only-" + UUID.randomUUID();
            commo.sendCoT(unavailable, String.format(EVENT, pointOnly, "Sender"), CoTSendMethod.POINT_TO_POINT);
            require(unavailable.size() == 1 && unavailable.firstElement() == peer,
                    "stream fallback ignored POINT_TO_POINT restriction");
            require(!a.received.toString().contains(pointOnly) && !b.received.toString().contains(pointOnly),
                    "point-only CoT leaked into a stream");
            try {
                commo.configKnownEndpointForContact(PEER, null, ia.streamId);
                throw new AssertionError("partial removal accepted");
            } catch (CommoException expected) { }

            // A configured TCP fallback must not hijack an existing UDP route.
            try (DatagramSocket udp = new DatagramSocket(0, InetAddress.getByName("127.0.0.1"))) {
                udp.setSoTimeout(5000);
                Contact direct = commo.configKnownEndpointContact("direct-peer", "Direct", "127.0.0.1", udp.getLocalPort());
                commo.configKnownEndpointForContact("direct-peer", "Configured", ia.streamId);
                String marker = "udp-" + UUID.randomUUID();
                commo.sendCoT(direct, String.format(EVENT, marker, "Sender"));
                DatagramPacket packet = new DatagramPacket(new byte[16384], 16384);
                udp.receive(packet);
                require(new String(packet.getData(), 0, packet.getLength(), StandardCharsets.UTF_8).contains(marker), "UDP route was not retained");
                require(!a.received.toString().contains(marker) && !b.received.toString().contains(marker), "UDP traffic leaked into fallback stream");
                commo.configKnownEndpointForContact("direct-peer", null, null);
                commo.configKnownEndpointContact("direct-peer", null, null, 0);
            }
            commo.configKnownEndpointForContact(PEER, "Configured", ib.streamId);
            arrives(commo, peer, b, a, "replaced-b");
            awaitDiscovery(commo, a);
            arrives(commo, peer, a, b, "discovery-wins");
            commo.configKnownEndpointForContact(PEER, null, null);
            arrives(commo, peer, a, b, "remove-keeps-discovery");
            commo.configKnownEndpointForContact(PEER, "Configured", ib.streamId);
            commo.removeStreamingInterface(ia); a.close();
            arrives(commo, peer, b, a, "lost-discovery-falls-back");
            // Removing the configured interface does not silently retarget its
            // contact to a different live stream. The stored config remains
            // until explicitly cleared, but sends through the removed ID fail.
            commo.removeStreamingInterface(ib);
            String removedMarker = "removed-stream-" + UUID.randomUUID();
            try { commo.sendCoT(peer, String.format(EVENT, removedMarker, "Sender")); throw new AssertionError("removed interface still routes"); }
            catch (CommoException expected) { }
            Contact controlPeer = commo.configKnownEndpointForContact("control-peer", "Configured", ic.streamId);
            arrives(commo, controlPeer, control, b, "control-barrier");
            require(!control.received.toString().contains(removedMarker), "removed interface leaked CoT to another stream");
            commo.configKnownEndpointForContact(PEER, null, null);
            try { commo.sendCoT(peer, String.format(EVENT, "removed", "Sender")); throw new AssertionError("removed fallback still routes"); }
            catch (CommoException expected) { }
            // A second clear is rejected like the existing fixed-endpoint API;
            // it must not recreate a contact or any route.
            try { commo.configKnownEndpointForContact(PEER, null, null); throw new AssertionError("absent contact clear accepted"); }
            catch (CommoException expected) { }
            try { commo.configKnownEndpointForContact(PEER, "Wrong", ib.streamId); throw new AssertionError("removed stream accepted"); }
            catch (CommoException expected) { }
            commo.removeStreamingInterface(ic);
            System.out.println("PASS real TCP fallback, recipient callsigns, UDP priority, replacement, discovery priority, removal, disconnect fallback, removed-interface isolation and unknown-stream rejection");
        } finally { commo.shutdown(); }
    }
}
