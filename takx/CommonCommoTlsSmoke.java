// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import com.atakmap.commoncommo.*;
import javax.net.ssl.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.UUID;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

/** Real chain-verified loopback mutual TLS; upstream does not check hostnames. */
public final class CommonCommoTlsSmoke {
    private static final String EVENT = "<event version='2.0' uid='%s' type='a-f-G-U-C' time='2026-01-01T00:00:00Z' start='2026-01-01T00:00:00Z' stale='2099-01-01T00:00:00Z' how='m-g'><point lat='0' lon='0' hae='0' ce='1' le='1'/><detail><contact callsign='TLS peer' endpoint='*:-1:stcp'/></detail></event>";
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static X509Certificate certificate(Path path) throws Exception {
        try (InputStream input = Files.newInputStream(path)) {
            return (X509Certificate) CertificateFactory.getInstance("X.509").generateCertificate(input);
        }
    }
    private static SSLContext context(Path directory, char[] password, String trustedCa) throws Exception {
        KeyStore identity = KeyStore.getInstance("PKCS12");
        try (InputStream input = Files.newInputStream(directory.resolve("server.p12"))) { identity.load(input, password); }
        KeyManagerFactory keys = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        keys.init(identity, password);
        KeyStore trust = KeyStore.getInstance("PKCS12"); trust.load(null, null);
        trust.setCertificateEntry("ca", certificate(directory.resolve(trustedCa)));
        TrustManagerFactory managers = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        managers.init(trust);
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(keys.getKeyManagers(), managers.getTrustManagers(), new SecureRandom());
        return context;
    }
    private static final class Peer implements AutoCloseable {
        final SSLServerSocket server;
        final CountDownLatch handshake = new CountDownLatch(1);
        final CountDownLatch rejected = new CountDownLatch(1);
        final StringBuffer received = new StringBuffer();
        final AtomicReference<Throwable> failure = new AtomicReference<>();
        volatile SSLSocket socket;
        volatile X509Certificate client;
        final Thread thread;
        volatile boolean closing;
        Peer(SSLContext context) throws IOException {
            server = (SSLServerSocket) context.getServerSocketFactory().createServerSocket(0, 1, InetAddress.getByName("127.0.0.1"));
            server.setNeedClientAuth(true);
            server.setSoTimeout(12000);
            thread = new Thread(() -> {
                try {
                    socket = (SSLSocket) server.accept(); socket.setSoTimeout(10000);
                    socket.startHandshake();
                    client = (X509Certificate) socket.getSession().getPeerCertificates()[0];
                    handshake.countDown();
                    byte[] bytes = new byte[8192]; int n;
                    while ((n = socket.getInputStream().read(bytes)) != -1) received.append(new String(bytes, 0, n, StandardCharsets.UTF_8));
                } catch (SSLHandshakeException expectedRejection) { rejected.countDown(); }
                catch (Throwable error) { if (!closing) failure.set(error); }
            }, "mutual-tls-peer");
            thread.setDaemon(true); thread.start();
        }
        void event(String uid) throws IOException {
            socket.getOutputStream().write(String.format(EVENT, uid).getBytes(StandardCharsets.UTF_8));
            socket.getOutputStream().flush();
        }
        public void close() throws Exception {
            closing = true; server.close(); if (socket != null) socket.close();
            thread.join(2000); require(!thread.isAlive(), "TLS peer thread did not stop");
        }
    }
    private static StreamingNetInterface connect(Commo commo, Peer peer, Path directory, String trust, String client, String password) throws Exception {
        return commo.addStreamingInterface(StreamingTransport.SSL, "127.0.0.1", peer.server.getLocalPort(),
            new CoTMessageType[] {CoTMessageType.SITUATIONAL_AWARENESS}, Files.readAllBytes(directory.resolve(client)),
            Files.readAllBytes(directory.resolve(trust)), password, password, null, null);
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 1, "ephemeral credential directory required");
        Path directory = Path.of(args[0]);
        String password = System.getenv("TAKX_TLS_PASSWORD");
        require(password != null && !password.isEmpty(), "ephemeral certificate password required");
        Commo commo = new Commo((level, type, message, detail) -> {}, "tls-" + UUID.randomUUID(), "TLS SMOKE");
        try {
            String incoming = "tls-peer-" + UUID.randomUUID();
            CountDownLatch discovered = new CountDownLatch(1);
            AtomicReference<Contact> contact = new AtomicReference<>();
            commo.addContactPresenceListener(new ContactPresenceListener() {
                public void contactAdded(Contact value) { if (incoming.equals(value.contactUID)) { contact.set(value); discovered.countDown(); } }
                public void contactRemoved(Contact value) { }
            });
            try (Peer peer = new Peer(context(directory, password.toCharArray(), "ca.crt"))) {
                StreamingNetInterface stream = connect(commo, peer, directory, "trust.p12", "client.p12", password);
                try {
                    require(peer.handshake.await(10, TimeUnit.SECONDS), "trusted mutual TLS did not complete");
                    require(peer.client.equals(certificate(directory.resolve("client.crt"))), "server did not authenticate the exact client certificate");
                    peer.event(incoming);
                    require(discovered.await(10, TimeUnit.SECONDS), "real TLS CoT contact was not discovered");
                    String outgoing = "tls-send-" + UUID.randomUUID();
                    commo.sendCoT(contact.get(), String.format(EVENT, outgoing));
                    long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
                    while (!peer.received.toString().contains(outgoing) && System.nanoTime() < deadline) Thread.sleep(20);
                    require(peer.received.toString().contains(outgoing), "CoT did not traverse the authenticated TLS stream");
                    require(peer.failure.get() == null, "TLS peer failed unexpectedly");
                    System.out.println("PASS trusted mutual TLS authenticates exact client and carries received/discovered/routed CoT");
                } finally { commo.removeStreamingInterface(stream); }
            }
            CountDownLatch untrusted = new CountDownLatch(1);
            CountDownLatch incorrectlyUp = new CountDownLatch(1);
            commo.addInterfaceStatusListener(new InterfaceStatusListener() {
                public void interfaceUp(NetInterface iface) { incorrectlyUp.countDown(); }
                public void interfaceDown(NetInterface iface) { }
                public void interfaceError(NetInterface iface, NetInterfaceErrorCode code) {
                    if (code == NetInterfaceErrorCode.CONN_SSL_PEER_CERT_NOT_TRUSTED) untrusted.countDown();
                }
            });
            try (Peer peer = new Peer(context(directory, password.toCharArray(), "ca.crt"))) {
                StreamingNetInterface stream = connect(commo, peer, directory, "wrong-trust.p12", "client.p12", password);
                try {
                    commo.broadcastCoT(String.format(EVENT, "wrong-server-trust-" + UUID.randomUUID()));
                    require(untrusted.await(10, TimeUnit.SECONDS), "wrong trust did not produce native certificate rejection");
                    require(incorrectlyUp.getCount() == 1, "untrusted server interface became usable");
                    require(peer.received.length() == 0, "CoT leaked after server trust rejection");
                    System.out.println("PASS native wrong-CA rejection; interface never becomes Up and no CoT is sent");
                } finally { commo.removeStreamingInterface(stream); }
            }
            try (Peer peer = new Peer(context(directory, password.toCharArray(), "wrong-ca.crt"))) {
                StreamingNetInterface stream = connect(commo, peer, directory, "trust.p12", "client.p12", password);
                try {
                    commo.broadcastCoT(String.format(EVENT, "wrong-client-trust-" + UUID.randomUUID()));
                    require(peer.rejected.await(10, TimeUnit.SECONDS), "server did not reject an untrusted client certificate");
                    require(peer.handshake.getCount() == 1, "untrusted client completed server authentication");
                    require(peer.received.length() == 0, "CoT leaked after client trust rejection");
                    System.out.println("PASS required-client-auth server rejects untrusted client; no application data");
                } finally { commo.removeStreamingInterface(stream); }
            }
        } finally { commo.shutdown(); }
        System.out.println("PASS bounded native shutdown; hostname validation and TAK Server interoperability are not established");
    }
}
