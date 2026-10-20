# 6. Re-encrypt tenant gateway traffic to the TAK web UI

Date: 2026-10-20

## Status

Accepted. Amends the 8447 connector in [ADR 0004](0004-tak-oauth-uses-openid-discovery.md).

## Context

ADR 0004 made 8447 a `tls="false"` connector. The tenant gateway ended TLS and sent HTTP to the pod. TAK Server 5.7-RELEASE-14 lists every connector with `tls="false"` as a non-secure port (`SubmissionService.getNonSecurePorts`). The admin UI reads that list from `/Marti/api/security/isSecure` and shows a red alert banner that names port 8447 as accepting unencrypted connections. TAK has no setting that says a connector sits behind a TLS proxy. The same plaintext connector made `request.isSecure()` false, so TAK did not mark its access-token cookie Secure.

The UDS Package CR `expose` entry has no option for a TLS backend. It only takes the `http` and `udp` protocols toward the Service. The only way to make the gateway speak TLS to the pod is a plain Istio DestinationRule.

## Decision

- 8447 is a TLS connector with `clientAuth="false"`. It serves keystore `takserver-web.jks`, not the main `takserver.jks`.
- The pre-install Job issues that certificate after it generates the TAK certificates. It is signed by the deploy-time CA ([ADR 0002](0002-generate-certificates-at-deploy-time.md)). Its subject alternative names are the in-cluster names of Service `takserver-web`. The keystore is added to ConfigMap `cert-migration`, so it is mounted under `certs/files` like the other keystores. An upgrade keeps the existing certificate.
- Service `takserver-web` names the port `https` with `appProtocol: https`.
- The chart adds DestinationRule `takserver-web`. It is outside the Package CR. It sets TLS mode `SIMPLE` on port 8447, SNI and the expected subject alternative name to `takserver-web.<namespace>.svc.cluster.local`, and `credentialName: takserver-web-ca`. It is exported only to the tenant gateway namespace. `insecureSkipVerify` is not used: the gateway checks the certificate against the CA.
- A gateway reads `credentialName` Secrets only from its own namespace. A Zarf deploy action copies `ca.pem` from `cert-migration` into Secret `takserver-web-ca` (key `cacert`) in `istio-tenant-gateway`. Only the CA certificate is copied. The CA key stays in the TAK namespace.
- Everything else (the host, NetworkPolicies, the SSO client) stays in the Package CR.
- `api.web.backendTLS.enabled` (default `true`) turns this off. Off restores the plaintext connector and the `http` port name, and brings the banner back.

## Consequences

The banner is gone, `isSecure` returns `true`, and TAK marks the access-token cookie Secure.

This package now ships raw Istio configuration that the UDS operator does not manage or validate. A UDS Core change to the tenant gateway namespace, or to how it handles DestinationRules, can break the browser UI without a Package CR error. The test task `web-tls` checks the connector, the Service, the DestinationRule, and the gateway Secret on every run.

In ambient mode Istio still sends this traffic through the HBONE tunnel, so the hop is TLS inside mutual TLS. Strict mTLS still applies. The cost is a second TLS handshake and encryption on the gateway-to-pod hop.

The CA certificate exists in two places. The deploy action writes it on every deploy, so a new CA reaches the gateway on the next deploy. The web certificate is valid for two years and is not rotated automatically. Delete the `takserver-web.jks` key from `cert-migration` and redeploy to issue a new one.
