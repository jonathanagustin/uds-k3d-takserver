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
import java.util.List;
import java.util.UUID;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

/** Real loopback JNI/mTLS with configured DNS/IP identity and SNI checks. */
public final class CommonCommoTlsSmoke {
    private static final String EVENT = "<event version='2.0' uid='%s' type='a-f-G-U-C' time='2026-01-01T00:00:00Z' start='2026-01-01T00:00:00Z' stale='2099-01-01T00:00:00Z' how='m-g'><point lat='0' lon='0' hae='0' ce='1' le='1'/><detail><contact callsign='TLS peer' endpoint='*:-1:stcp'/></detail></event>";
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static X509Certificate certificate(Path path) throws Exception {
        try (InputStream input = Files.newInputStream(path)) {
            return (X509Certificate) CertificateFactory.getInstance("X.509").generateCertificate(input);
        }
    }
    private static Commo commo() throws CommoException {
        return new Commo((level, type, message, detail) -> {}, "tls-" + UUID.randomUUID(), "TLS SMOKE");
    }
    private static SSLContext context(Path directory, char[] password, String identityName, String trustedCa) throws Exception {
        KeyStore identity = KeyStore.getInstance("PKCS12");
        try (InputStream input = Files.newInputStream(directory.resolve(identityName))) { identity.load(input, password); }
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
        final ServerSocket server;
        final CountDownLatch handshake = new CountDownLatch(1);
        final CountDownLatch rejected = new CountDownLatch(1);
        final StringBuffer received = new StringBuffer();
        final AtomicReference<Throwable> failure = new AtomicReference<>();
        volatile Socket transport;
        volatile SSLSocket socket;
        volatile X509Certificate client;
        volatile List<SNIServerName> serverNames;
        final Thread thread;
        volatile boolean closing;
        Peer(SSLContext context) throws IOException {
            // Own the underlying transport so cleanup of an already rejected
            // peer cannot attempt a second TLS close_notify on a broken pipe.
            server = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"));
            server.setSoTimeout(12000);
            thread = new Thread(() -> {
                try {
                    transport = server.accept();
                    if (closing) { transport.close(); return; }
                    socket = (SSLSocket) context.getSocketFactory().createSocket(transport, "localhost", transport.getPort(), true);
                    socket.setUseClientMode(false);
                    socket.setNeedClientAuth(true);
                    socket.setSoTimeout(10000);
                    socket.startHandshake();
                    client = (X509Certificate) socket.getSession().getPeerCertificates()[0];
                    serverNames = ((ExtendedSSLSession) socket.getSession()).getRequestedServerNames();
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
            closing = true; server.close();
            if (transport != null) transport.close();
            if (socket != null) socket.close();
            thread.join(2000); require(!thread.isAlive(), "TLS peer thread did not stop");
        }
    }
    private static StreamingNetInterface connect(Commo commo, Peer peer, Path directory, String host, String trust, String client, String password) throws Exception {
        return commo.addStreamingInterface(StreamingTransport.SSL, host, peer.server.getLocalPort(),
            new CoTMessageType[] {CoTMessageType.SITUATIONAL_AWARENESS}, client == null ? null : Files.readAllBytes(directory.resolve(client)),
            Files.readAllBytes(directory.resolve(trust)), password, password, "tls-smoke-user", "tls-smoke-auth");
    }
    private static void positive(Path directory, String password, String host) throws Exception {
        Commo commo = commo();
        CountDownLatch down = new CountDownLatch(1);
        commo.addInterfaceStatusListener(new InterfaceStatusListener() {
            public void interfaceUp(NetInterface iface) { }
            public void interfaceDown(NetInterface iface) { down.countDown(); }
            public void interfaceError(NetInterface iface, NetInterfaceErrorCode code) { }
        });
        try {
            String incoming = "tls-peer-" + UUID.randomUUID();
            CountDownLatch discovered = new CountDownLatch(1);
            AtomicReference<Contact> contact = new AtomicReference<>();
            commo.addContactPresenceListener(new ContactPresenceListener() {
                public void contactAdded(Contact value) { if (incoming.equals(value.contactUID)) { contact.set(value); discovered.countDown(); } }
                public void contactRemoved(Contact value) { }
            });
            try (Peer peer = new Peer(context(directory, password.toCharArray(), "server.p12", "ca.crt"))) {
                StreamingNetInterface stream = connect(commo, peer, directory, host, "trust.p12", "client.p12", password);
                try {
                    require(peer.handshake.await(10, TimeUnit.SECONDS), "trusted mutual TLS did not complete");
                    require(peer.client.equals(certificate(directory.resolve("client.crt"))), "server did not authenticate the exact client certificate");
                    if (host.equals("localhost")) {
                        require(peer.serverNames.size() == 1 && peer.serverNames.get(0).equals(new SNIHostName(host)), "configured DNS name was not sent as SNI");
                    } else {
                        require(peer.serverNames.isEmpty(), "literal IP must not be sent as DNS SNI");
                    }
                    peer.event(incoming);
                    require(discovered.await(10, TimeUnit.SECONDS), "real TLS CoT contact was not discovered");
                    String outgoing = "tls-send-" + UUID.randomUUID();
                    commo.sendCoT(contact.get(), String.format(EVENT, outgoing));
                    long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
                    while (!peer.received.toString().contains(outgoing) && System.nanoTime() < deadline) Thread.sleep(20);
                    require(peer.received.toString().contains(outgoing), "CoT did not traverse the authenticated TLS stream");
                    require(peer.received.toString().contains("tls-smoke-user"), "verified stream did not send its authentication document");
                    require(peer.failure.get() == null, "TLS peer failed unexpectedly");
                    peer.closing = true;
                    peer.transport.setSoLinger(true, 0);
                    peer.transport.close();
                    require(down.await(10, TimeUnit.SECONDS), "native TLS interface did not report abrupt peer close");
                    System.out.println("PASS " + host + " identity, exact client authentication, SNI policy, received/discovered/routed CoT and abrupt peer close");
                } finally { commo.removeStreamingInterface(stream); }
            }
        } finally { commo.shutdown(); }
    }
    private static void rejectedServer(Path directory, String password, String host, String serverIdentity, String trust) throws Exception {
        Commo commo = commo();
        CountDownLatch untrusted = new CountDownLatch(1);
        CountDownLatch incorrectlyUp = new CountDownLatch(1);
        CountDownLatch decision = new CountDownLatch(1);
        commo.addInterfaceStatusListener(new InterfaceStatusListener() {
            public void interfaceUp(NetInterface iface) { incorrectlyUp.countDown(); decision.countDown(); }
            public void interfaceDown(NetInterface iface) { }
            public void interfaceError(NetInterface iface, NetInterfaceErrorCode code) {
                if (code == NetInterfaceErrorCode.CONN_SSL_PEER_CERT_NOT_TRUSTED) { untrusted.countDown(); decision.countDown(); }
            }
        });
        try (Peer peer = new Peer(context(directory, password.toCharArray(), serverIdentity, "ca.crt"))) {
            StreamingNetInterface stream = connect(commo, peer, directory, host, trust, "client.p12", password);
            try {
                commo.broadcastCoT(String.format(EVENT, "must-not-send-" + UUID.randomUUID()));
                require(decision.await(10, TimeUnit.SECONDS), "server identity decision timed out");
                require(incorrectlyUp.getCount() == 1, "untrusted server interface became usable");
                require(untrusted.getCount() == 0, "invalid server identity/trust did not produce native certificate rejection");
            } finally { commo.removeStreamingInterface(stream); }
            // Join before examining bytes: include everything read up to native removal.
            peer.thread.join(2000);
            require(!peer.thread.isAlive(), "rejected TLS peer did not finish");
            require(peer.received.length() == 0, "CoT or authentication data leaked after server rejection");
            System.out.println("PASS native server rejection " + serverIdentity + " / " + host + " / " + trust + "; no Up, authentication or CoT");
        } finally { commo.shutdown(); }
    }
    private static void rejectedClient(Path directory, String password) throws Exception {
        Commo commo = commo();
        try (Peer peer = new Peer(context(directory, password.toCharArray(), "server.p12", "wrong-ca.crt"))) {
            StreamingNetInterface stream = connect(commo, peer, directory, "127.0.0.1", "trust.p12", "client.p12", password);
            try {
                commo.broadcastCoT(String.format(EVENT, "wrong-client-trust-" + UUID.randomUUID()));
                require(peer.rejected.await(10, TimeUnit.SECONDS), "server did not reject an untrusted client certificate");
                require(peer.handshake.getCount() == 1, "untrusted client completed server authentication");
                require(peer.received.length() == 0, "CoT leaked after client trust rejection");
                System.out.println("PASS required-client-auth server rejects untrusted client; no application data");
            } finally { commo.removeStreamingInterface(stream); }
        } finally { commo.shutdown(); }
    }
    private static void missingClient(Path directory, String password) throws Exception {
        Commo commo = commo();
        try (Peer peer = new Peer(context(directory, password.toCharArray(), "server.p12", "ca.crt"))) {
            boolean rejected = false;
            try { connect(commo, peer, directory, "localhost", "trust.p12", null, password); }
            catch (CommoException expected) { rejected = true; }
            require(rejected, "explicit SSL transport accepted an absent client certificate");
            require(peer.handshake.getCount() == 1 && peer.received.length() == 0, "absent-client call sent data");
            System.out.println("PASS JNI explicit SSL interface rejects missing client certificate");
        } finally { commo.shutdown(); }
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 1, "ephemeral credential directory required");
        Path directory = Path.of(args[0]);
        String password = System.getenv("TAKX_TLS_PASSWORD");
        require(password != null && !password.isEmpty(), "ephemeral certificate password required");
        positive(directory, password, "localhost");
        positive(directory, password, "127.0.0.1");
        rejectedServer(directory, password, "localhost", "wrong-dns.p12", "trust.p12");
        rejectedServer(directory, password, "127.0.0.1", "wrong-ip.p12", "trust.p12");
        rejectedServer(directory, password, "127.0.0.1", "dns-ip.p12", "trust.p12");
        rejectedServer(directory, password, "localhost", "cn-only.p12", "trust.p12");
        rejectedServer(directory, password, "127.0.0.1", "server.p12", "wrong-trust.p12");
        rejectedClient(directory, password);
        missingClient(directory, password);
        System.out.println("PASS bounded native shutdown; tested SSL endpoint identity, not TAK Server interoperability or full client acceptance");
    }
}
