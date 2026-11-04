# 20. QUIC through Envoy Gateway

Date: 2026-10-25

## Status

Accepted

## Context

Istio does not route UDP. UDS Core 1.16.0 sends a Package expose entry with `protocol: UDP` through Envoy Gateway (`envoy-gateway` and `envoy-default-gateway` on `core-base`), and that path is not covered by Istio AuthorizationPolicy or mTLS.

TAK Server 5.7-RELEASE-14 can listen for QUIC. `QuicSslContextBuilder` in `NioNettyInitializer.buildQuicServerSslContext` sets `ClientAuth.REQUIRE` and ALPN `takstream`. The input element in `CoreConfig.xsd` defaults `auth` to `x509`, and the example input omits the attribute, so the connection uses `X509AuthCodec` the same way the TLS input on 8089 does. The server reads the peer certificate, rejects an expired one, and takes the username from the subject. A client with no certificate does not finish the handshake.

The plaintext UDP input on 8087 and the multicast inputs set `auth="anonymous"`. Those stay out.

## Decision

`quic.enabled` defaults to false. Nothing in CoreConfig, the chart, or the Package changes while it is false, and there is no UDP Service.

When it is true, CoreConfig gains `<input _name="quic" protocol="quic" port="8090" coreVersion="2"/>`, Service `takserver-messaging-quic` publishes UDP 8090 to the messaging pods, and the Package exposes that service with `protocol: UDP`.

The UDS operator writes the UDPRoute and one ingress NetworkPolicy from the Envoy default gateway proxy. The chart adds no allow rule of its own.

The test bundle selects `envoy-gateway` and `envoy-default-gateway` and sets the flag. The controller request is 50m CPU and 256Mi. The proxy that Envoy Gateway 1.9.2 creates for a UDP listener requests 100m CPU and 512Mi, plus a 10m/32Mi shutdown manager.

`tests/quic.sh` connects through that gateway. A client without a certificate must be refused with a TLS alert; no answer at all fails. A client with the admin certificate must stream a CoT event, and its uid must appear in `/Marti/api/subscriptions/all`.

## Consequences

- A normal install does not run Envoy Gateway and does not open UDP.
- The test bundle does. The extra request is about 160m CPU and 800Mi on top of the pinned Istiod and passthrough gateway. The public CI runners have 4 CPU and 16 GB. A 2 CPU, 8 GB node still has to fit those requests beside the TAK test-values.
- UDP is not mesh mTLS. The client certificate is the authentication.
- `kubectl port-forward` does not carry UDP. The test sends to the gateway's LoadBalancer address from the runner, the same path UDS Core's UDP test uses. With no LoadBalancer address it falls back to the ClusterIP from the k3d node network namespace.
- The messaging image ships the Netty QUIC native library for both linux-x86_64 and linux-aarch_64 (`netty-incubator-codec-native-quic-0.0.75.Final`), with BoringSSL for both. QUIC works on amd64 and arm64 nodes, and `tests/quic.sh` runs on both.
- The full-core bundle does not select Envoy Gateway. It must not turn `quic.enabled` on until it does.
