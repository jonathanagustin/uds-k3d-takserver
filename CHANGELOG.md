# Changelog

## [0.3.0](https://github.com/jonathanagustin/uds-k3d-takserver/compare/v0.2.0...v0.3.0) (2026-10-22)


### Features

* add renovate fix, uptime probes, exemption docs, package metadata and portal tiles ([#72](https://github.com/jonathanagustin/uds-k3d-takserver/issues/72)) ([4880f21](https://github.com/jonathanagustin/uds-k3d-takserver/commit/4880f21d3076967be473e3eb7c289053fda74697))
* build the postgis image in this repository for amd64 and arm64 ([#81](https://github.com/jonathanagustin/uds-k3d-takserver/issues/81)) ([f0bb485](https://github.com/jonathanagustin/uds-k3d-takserver/commit/f0bb485a3d6ec523bfa9e682fe15e737ab1efdc4))


### Bug Fixes

* **ci:** strip color codes from the released package definition before checking its version ([#70](https://github.com/jonathanagustin/uds-k3d-takserver/issues/70)) ([c992016](https://github.com/jonathanagustin/uds-k3d-takserver/commit/c992016dbf9436dc84346bf35c7a50d7bba3b0b8))
* let uds run dev upgrade core-base and add a registry mirror option ([#78](https://github.com/jonathanagustin/uds-k3d-takserver/issues/78)) ([03b9d05](https://github.com/jonathanagustin/uds-k3d-takserver/commit/03b9d059930ade6eacb2db4e375c0ab15b8df1a7))
* write TAK PKCS[#12](https://github.com/jonathanagustin/uds-k3d-takserver/issues/12) files with AES-256 and an HMAC-SHA256 MAC ([#74](https://github.com/jonathanagustin/uds-k3d-takserver/issues/74)) ([460cde6](https://github.com/jonathanagustin/uds-k3d-takserver/commit/460cde632b0fcc951d0203d198a3b5774a26f6ae))

## [0.2.0](https://github.com/jonathanagustin/uds-k3d-takserver/compare/v0.1.0...v0.2.0) (2026-10-21)


### Features

* add CloudTAK with Keycloak sign-in as the browser map client ([#13](https://github.com/jonathanagustin/uds-k3d-takserver/issues/13)) ([c3b81ee](https://github.com/jonathanagustin/uds-k3d-takserver/commit/c3b81ee6b656e699beb7e2487e1034d113813dac))
* build, package, and test for linux/arm64 alongside amd64 ([#16](https://github.com/jonathanagustin/uds-k3d-takserver/issues/16)) ([2e7c663](https://github.com/jonathanagustin/uds-k3d-takserver/commit/2e7c663c415fbe7f9c8e578fccca5abbd1d00b5c))
* **cloudtak:** default OpenStreetMap basemap through a tile proxy ([#20](https://github.com/jonathanagustin/uds-k3d-takserver/issues/20)) ([bf6727e](https://github.com/jonathanagustin/uds-k3d-takserver/commit/bf6727e0d7e79b6f8abe095e8a737bb1d58968a7))
* **demo:** add CloudTAK map chapter to the demo video ([#21](https://github.com/jonathanagustin/uds-k3d-takserver/issues/21)) ([6d5f589](https://github.com/jonathanagustin/uds-k3d-takserver/commit/6d5f589bcbf0724620e0ec74764cfd1d9192f59f))
* render the OIDC client secret at admission ([#4](https://github.com/jonathanagustin/uds-k3d-takserver/issues/4)) ([bd61198](https://github.com/jonathanagustin/uds-k3d-takserver/commit/bd611987af4d1858a2e6b9a3044c5660700dffb6))
* replace intra-namespace allow-all with per-workload network rules ([#11](https://github.com/jonathanagustin/uds-k3d-takserver/issues/11)) ([951ca44](https://github.com/jonathanagustin/uds-k3d-takserver/commit/951ca4418b866837775e73741800a37f8fb8d31f))
* serve the standard TAK ports 8446 and 8089 on the passthrough gateway ([#19](https://github.com/jonathanagustin/uds-k3d-takserver/issues/19)) ([3d9e950](https://github.com/jonathanagustin/uds-k3d-takserver/commit/3d9e950136e798a0bbebacce1a7583cff51f258f))


### Bug Fixes

* give Ignite room, let TAK reach Keycloak over TLS 1.3, and keep each node's CoreConfig ([#1](https://github.com/jonathanagustin/uds-k3d-takserver/issues/1)) ([93874f7](https://github.com/jonathanagustin/uds-k3d-takserver/commit/93874f73298d6a986ed16c5cf10113304d4bdf62))
* re-encrypt gateway traffic to the TAK web UI ([#10](https://github.com/jonathanagustin/uds-k3d-takserver/issues/10)) ([752d016](https://github.com/jonathanagustin/uds-k3d-takserver/commit/752d016a172583e283d24aa237ac8beb920e4435))
* resolve DOMAIN hosts to the Istio gateways inside the cluster ([#14](https://github.com/jonathanagustin/uds-k3d-takserver/issues/14)) ([6e29e64](https://github.com/jonathanagustin/uds-k3d-takserver/commit/6e29e64d5874434a6620921e5f23636f8756e186))


### Documentation

* add contributing guide, PR template, and OpenSSF Best Practices badge ([#63](https://github.com/jonathanagustin/uds-k3d-takserver/issues/63)) ([a90843c](https://github.com/jonathanagustin/uds-k3d-takserver/commit/a90843ca24f2f0a4b8951033277e50834ca134be))
* clean up README ([#5](https://github.com/jonathanagustin/uds-k3d-takserver/issues/5)) ([3443d79](https://github.com/jonathanagustin/uds-k3d-takserver/commit/3443d79e55b27b981b8ebc09a6d4d9a0174a9013))
* renumber the standard TAK ports ADR to 0012 ([#23](https://github.com/jonathanagustin/uds-k3d-takserver/issues/23)) ([13f1bd2](https://github.com/jonathanagustin/uds-k3d-takserver/commit/13f1bd2fdb173b50b53001df56d884d82038beba))
* show the demo video at the top of the README ([#17](https://github.com/jonathanagustin/uds-k3d-takserver/issues/17)) ([089f7f1](https://github.com/jonathanagustin/uds-k3d-takserver/commit/089f7f1771e44a71241950b56371341734b615fd))
* update README demo video with the CloudTAK map chapter ([#22](https://github.com/jonathanagustin/uds-k3d-takserver/issues/22)) ([1b3c3b7](https://github.com/jonathanagustin/uds-k3d-takserver/commit/1b3c3b7f35abfd8a27e502e5ffad4113bd89102c))
