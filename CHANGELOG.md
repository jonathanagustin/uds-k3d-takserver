# Changelog

## [0.7.0](https://github.com/jonathanagustin/uds-k3d-takserver/compare/v0.6.0...v0.7.0) (2026-10-29)


### Features

* add a TAK Grafana dashboard and alert rules ([#182](https://github.com/jonathanagustin/uds-k3d-takserver/issues/182)) ([311ff82](https://github.com/jonathanagustin/uds-k3d-takserver/commit/311ff8204a3920ceb48cfe7d7609b1fed968a7c9)), closes [#27](https://github.com/jonathanagustin/uds-k3d-takserver/issues/27)
* add small and production values profiles ([#195](https://github.com/jonathanagustin/uds-k3d-takserver/issues/195)) ([b6506ae](https://github.com/jonathanagustin/uds-k3d-takserver/commit/b6506ae5300ea6006bed9b12eac349629b99658f))
* collect Falco events and add a TAK cert-write rule ([#184](https://github.com/jonathanagustin/uds-k3d-takserver/issues/184)) ([bb97380](https://github.com/jonathanagustin/uds-k3d-takserver/commit/bb97380b6b0a45fe8591e937bda0dbc66cc3ec9d)), closes [#30](https://github.com/jonathanagustin/uds-k3d-takserver/issues/30)
* end the CloudTAK Keycloak session on logout ([#187](https://github.com/jonathanagustin/uds-k3d-takserver/issues/187)) ([6e9bc51](https://github.com/jonathanagustin/uds-k3d-takserver/commit/6e9bc51c8e506151b439364a578458691e561006)), closes [#31](https://github.com/jonathanagustin/uds-k3d-takserver/issues/31)
* probe TAK and CloudTAK uptime in the full-core job ([#183](https://github.com/jonathanagustin/uds-k3d-takserver/issues/183)) ([702dbe7](https://github.com/jonathanagustin/uds-k3d-takserver/commit/702dbe7202ed17e76302e93e89e01ad856a00b98)), closes [#28](https://github.com/jonathanagustin/uds-k3d-takserver/issues/28)
* restore TAK and CloudTAK from a logical dump ([#181](https://github.com/jonathanagustin/uds-k3d-takserver/issues/181)) ([cbb5651](https://github.com/jonathanagustin/uds-k3d-takserver/commit/cbb5651e2031e9282d7940718f4216955336e260)), closes [#25](https://github.com/jonathanagustin/uds-k3d-takserver/issues/25)
* run NATS 2.15 with the upstream chart ([#210](https://github.com/jonathanagustin/uds-k3d-takserver/issues/210)) ([0234818](https://github.com/jonathanagustin/uds-k3d-takserver/commit/023481886924269a8d135ac98aaa0d2d97a92714))


### Bug Fixes

* **deps:** update tak server support dependencies ([#218](https://github.com/jonathanagustin/uds-k3d-takserver/issues/218)) ([2f70651](https://github.com/jonathanagustin/uds-k3d-takserver/commit/2f70651f598ed4b4c78b2ac77763d17c879e3235))
* **deps:** update undici to 8.12.3 and body-parser to 2.4.0 in the Pepr module ([#152](https://github.com/jonathanagustin/uds-k3d-takserver/issues/152)) ([ed67a99](https://github.com/jonathanagustin/uds-k3d-takserver/commit/ed67a99028ba5bbbfa4a09a42ecb51f04b99beb9))
* keep keystore passwords in a Secret ([#168](https://github.com/jonathanagustin/uds-k3d-takserver/issues/168)) ([3e777d1](https://github.com/jonathanagustin/uds-k3d-takserver/commit/3e777d1533023cf1d9e8dabd5b50c0608e9f7661)), closes [#67](https://github.com/jonathanagustin/uds-k3d-takserver/issues/67)
* plot both architectures on one scale ([#214](https://github.com/jonathanagustin/uds-k3d-takserver/issues/214)) ([c2af60d](https://github.com/jonathanagustin/uds-k3d-takserver/commit/c2af60d70dc0bf85ac24150f43259b4444a24bd1))
* **renovate:** drop host rules that need Iron Bank secrets ([#172](https://github.com/jonathanagustin/uds-k3d-takserver/issues/172)) ([4c0a414](https://github.com/jonathanagustin/uds-k3d-takserver/commit/4c0a4149bbed8c10198b81ae99693a418540eceb)), closes [#171](https://github.com/jonathanagustin/uds-k3d-takserver/issues/171)
* repair the full-core test steps that never ran ([#215](https://github.com/jonathanagustin/uds-k3d-takserver/issues/215)) ([4082510](https://github.com/jonathanagustin/uds-k3d-takserver/commit/40825104dc97f8e4a11ec68338df91fb675897c7))
* retry refused API handshakes in the cert-init hooks ([#176](https://github.com/jonathanagustin/uds-k3d-takserver/issues/176)) ([8a8ff80](https://github.com/jonathanagustin/uds-k3d-takserver/commit/8a8ff80f01582c7288785d1c94c04c09139b6e84)), closes [#168](https://github.com/jonathanagustin/uds-k3d-takserver/issues/168)
* stop a cached CoreConfig from replacing the local file ([#174](https://github.com/jonathanagustin/uds-k3d-takserver/issues/174)) ([b36a6e2](https://github.com/jonathanagustin/uds-k3d-takserver/commit/b36a6e2f27d4a53019a47fef65330452ddf5b6d6)), closes [#3](https://github.com/jonathanagustin/uds-k3d-takserver/issues/3)
* wait for the app pods to be gone before the restore reloads the databases ([#216](https://github.com/jonathanagustin/uds-k3d-takserver/issues/216)) ([83293b2](https://github.com/jonathanagustin/uds-k3d-takserver/commit/83293b2e422fed7c9b6510681a4b1ac5fb46a1b6))


### Miscellaneous

* align slim core version, fix docs drift, tighten CI token permissions ([#155](https://github.com/jonathanagustin/uds-k3d-takserver/issues/155)) ([22ac952](https://github.com/jonathanagustin/uds-k3d-takserver/commit/22ac95296ce02527ab6ca552eb090285c385dd0f)), closes [#161](https://github.com/jonathanagustin/uds-k3d-takserver/issues/161)
* **atak:** install the viewer's runtime dependencies from a lockfile ([#150](https://github.com/jonathanagustin/uds-k3d-takserver/issues/150)) ([41e4639](https://github.com/jonathanagustin/uds-k3d-takserver/commit/41e463982d68b7eb7f898fcbd3cfb0eb0111a1d8))
* **atak:** record why the APK builder's urllib3 advisories are ignored ([#153](https://github.com/jonathanagustin/uds-k3d-takserver/issues/153)) ([7faaa9d](https://github.com/jonathanagustin/uds-k3d-takserver/commit/7faaa9dfad09b94ce59732ef1e392610b8e06775))
* record the protobuf advisories the load tester cannot take ([#220](https://github.com/jonathanagustin/uds-k3d-takserver/issues/220)) ([d37aa46](https://github.com/jonathanagustin/uds-k3d-takserver/commit/d37aa46e6393185059100c44532f49a995eb0a0d))
* **renovate:** extend the uds-common preset ([#170](https://github.com/jonathanagustin/uds-k3d-takserver/issues/170)) ([62e2401](https://github.com/jonathanagustin/uds-k3d-takserver/commit/62e2401140607098a3f07b77ca58b073464ec135)), closes [#162](https://github.com/jonathanagustin/uds-k3d-takserver/issues/162)


### Documentation

* add a Starlight site for the existing guides ([#173](https://github.com/jonathanagustin/uds-k3d-takserver/issues/173)) ([e8e11f4](https://github.com/jonathanagustin/uds-k3d-takserver/commit/e8e11f4c797f45aa623a382b6bc14dece107b773))
* keep release-please instead of the template tag flow ([#180](https://github.com/jonathanagustin/uds-k3d-takserver/issues/180)) ([599b7f0](https://github.com/jonathanagustin/uds-k3d-takserver/commit/599b7f09ac0bf2cea6bc8b2778136505fc2d7b43)), closes [#164](https://github.com/jonathanagustin/uds-k3d-takserver/issues/164)
* keep the TAK builder on Java 17 ([#209](https://github.com/jonathanagustin/uds-k3d-takserver/issues/209)) ([ce0c438](https://github.com/jonathanagustin/uds-k3d-takserver/commit/ce0c4380e443300960d33d24eb5ee8d47157acaf)), closes [#101](https://github.com/jonathanagustin/uds-k3d-takserver/issues/101)
* record the two Scorecard pins that are not registry deps ([#221](https://github.com/jonathanagustin/uds-k3d-takserver/issues/221)) ([7016bc7](https://github.com/jonathanagustin/uds-k3d-takserver/commit/7016bc72b0079aaab340867b1528dd4fa6fb7b56))
* record why only the upstream flavor ships ([#178](https://github.com/jonathanagustin/uds-k3d-takserver/issues/178)) ([e7fafea](https://github.com/jonathanagustin/uds-k3d-takserver/commit/e7fafea6a9d6f9602ffbd092a12652a9af7c3be9)), closes [#163](https://github.com/jonathanagustin/uds-k3d-takserver/issues/163)

## [0.6.0](https://github.com/jonathanagustin/uds-k3d-takserver/compare/v0.5.4...v0.6.0) (2026-10-24)


### Features

* add a package icon for UDS Portal and the registry ([#149](https://github.com/jonathanagustin/uds-k3d-takserver/issues/149)) ([1d9768e](https://github.com/jonathanagustin/uds-k3d-takserver/commit/1d9768ecd0423c233a6d3c7ff676fd4e42fd5e0c))
* **ci:** attest the TAK, CloudTAK and PostGIS images ([#143](https://github.com/jonathanagustin/uds-k3d-takserver/issues/143)) ([140d6ec](https://github.com/jonathanagustin/uds-k3d-takserver/commit/140d6ec8aefb455059a81d12dd05e2d8a98ef788))
* **demo:** sign the demo videos and attach their provenance ([#147](https://github.com/jonathanagustin/uds-k3d-takserver/issues/147)) ([9844122](https://github.com/jonathanagustin/uds-k3d-takserver/commit/98441223871fdc6569a5c87c253e1bd707af487d))
* match the client ServiceAccount on pod-to-pod Ingress rules ([#151](https://github.com/jonathanagustin/uds-k3d-takserver/issues/151)) ([168a14a](https://github.com/jonathanagustin/uds-k3d-takserver/commit/168a14aba26cd350a009ccf5ce9bcabac735417c))
* **release:** attach the provenance as an intoto.jsonl asset and verify it ([#142](https://github.com/jonathanagustin/uds-k3d-takserver/issues/142)) ([b1120c9](https://github.com/jonathanagustin/uds-k3d-takserver/commit/b1120c9ad6bff7bcb5aad06c2d33ae79dba47a56))


### Bug Fixes

* **cloudtak:** drop the unused build tools from the runtime image ([#141](https://github.com/jonathanagustin/uds-k3d-takserver/issues/141)) ([33c9f0f](https://github.com/jonathanagustin/uds-k3d-takserver/commit/33c9f0f6d0278a0633b627db3b4756cbd0f892d6))
* give NATS and its reloader requests and limits ([#148](https://github.com/jonathanagustin/uds-k3d-takserver/issues/148)) ([0a52608](https://github.com/jonathanagustin/uds-k3d-takserver/commit/0a52608ad304e0f227378a3811b0bcdd94906cb3))


### Miscellaneous

* **deps:** update package-deps to a3554c0 ([#137](https://github.com/jonathanagustin/uds-k3d-takserver/issues/137)) ([a08cb15](https://github.com/jonathanagustin/uds-k3d-takserver/commit/a08cb15bd086fe3ab91590829803b0bc1c72f339))
* **deps:** update support-deps to v17.0.21+9 ([#138](https://github.com/jonathanagustin/uds-k3d-takserver/issues/138)) ([4baee63](https://github.com/jonathanagustin/uds-k3d-takserver/commit/4baee634f25a94444a290cf187bf3c3c788e6980))
* drop the unknown adoptium datasource from the java pin ([#145](https://github.com/jonathanagustin/uds-k3d-takserver/issues/145)) ([358b615](https://github.com/jonathanagustin/uds-k3d-takserver/commit/358b615948290a0d818bd9c2ab9d7c1768b94a65))
* pin the remaining CI and build downloads by hash ([#144](https://github.com/jonathanagustin/uds-k3d-takserver/issues/144)) ([9fc5148](https://github.com/jonathanagustin/uds-k3d-takserver/commit/9fc5148ec7cea32ad6cd910384c1abc6c8597895))

## [0.5.4](https://github.com/jonathanagustin/uds-k3d-takserver/compare/v0.5.3...v0.5.4) (2026-10-23)


### Bug Fixes

* **demo:** close the TEST MARKER pane before the chat scene ([#134](https://github.com/jonathanagustin/uds-k3d-takserver/issues/134)) ([7a5b3d5](https://github.com/jonathanagustin/uds-k3d-takserver/commit/7a5b3d5665ca4d14833069d9cae7a0a252ae414d))


### Documentation

* link the demo video downloads to the demo release ([#133](https://github.com/jonathanagustin/uds-k3d-takserver/issues/133)) ([6d7afd6](https://github.com/jonathanagustin/uds-k3d-takserver/commit/6d7afd6dd86644a4f8e3937ef0d49c9663f3bcba))

## [0.5.3](https://github.com/jonathanagustin/uds-k3d-takserver/compare/v0.5.2...v0.5.3) (2026-10-23)


### Bug Fixes

* **ci:** skip the release on the commit under test when picking the upgrade baseline ([#128](https://github.com/jonathanagustin/uds-k3d-takserver/issues/128)) ([a151a3b](https://github.com/jonathanagustin/uds-k3d-takserver/commit/a151a3b18b6b8927620e6eec07897724319dc978))
* quote the cloudtak secret checksum annotation ([#130](https://github.com/jonathanagustin/uds-k3d-takserver/issues/130)) ([698f853](https://github.com/jonathanagustin/uds-k3d-takserver/commit/698f85309c24e38ef80f46c0ec3d5bff3e7163fb))


### Miscellaneous

* pin the atak viewer node base image by digest ([#129](https://github.com/jonathanagustin/uds-k3d-takserver/issues/129)) ([42b4fa8](https://github.com/jonathanagustin/uds-k3d-takserver/commit/42b4fa8c531bba3b87490e1c93fdad0d5ac8cf69))


### Documentation

* keep the README release examples on the current version ([#123](https://github.com/jonathanagustin/uds-k3d-takserver/issues/123)) ([0bfae62](https://github.com/jonathanagustin/uds-k3d-takserver/commit/0bfae629e750e5307c7511dfaab2c58e06f4c4a8))
* list the atak test device's kubevirt exemption and check it ([#124](https://github.com/jonathanagustin/uds-k3d-takserver/issues/124)) ([f550459](https://github.com/jonathanagustin/uds-k3d-takserver/commit/f550459d13df668c7cf9667e126bd99ea07f78b1))

## [0.5.2](https://github.com/jonathanagustin/uds-k3d-takserver/compare/v0.5.1...v0.5.2) (2026-10-22)


### Documentation

* add demo videos to README ([#107](https://github.com/jonathanagustin/uds-k3d-takserver/issues/107)) ([7526bc2](https://github.com/jonathanagustin/uds-k3d-takserver/commit/7526bc27c9bce22b791d0fe83c4e89c4ab3a78f9))
* play the demo videos inline in the README ([#110](https://github.com/jonathanagustin/uds-k3d-takserver/issues/110)) ([c97bb8d](https://github.com/jonathanagustin/uds-k3d-takserver/commit/c97bb8de80c01ebec839de311bc76c332d4d7e12))

## [0.5.1](https://github.com/jonathanagustin/uds-k3d-takserver/compare/v0.5.0...v0.5.1) (2026-10-22)


### Bug Fixes

* **demo:** repair the CloudTAK sync scenes and name chapters after their cards ([#106](https://github.com/jonathanagustin/uds-k3d-takserver/issues/106)) ([fce36d2](https://github.com/jonathanagustin/uds-k3d-takserver/commit/fce36d2c9fda7ec2b25208b93a92029d2edd94eb))


### Miscellaneous

* **deps:** update tak server package dependencies ([#94](https://github.com/jonathanagustin/uds-k3d-takserver/issues/94)) ([73074fd](https://github.com/jonathanagustin/uds-k3d-takserver/commit/73074fd3df982354e7ab8d670915db29b6d58aad))
* **deps:** update tak server support dependencies ([#95](https://github.com/jonathanagustin/uds-k3d-takserver/issues/95)) ([af5506c](https://github.com/jonathanagustin/uds-k3d-takserver/commit/af5506cdd1bd6ea8dd57e146333af3e42f2aae06))

## [0.5.0](https://github.com/jonathanagustin/uds-k3d-takserver/compare/v0.4.0...v0.5.0) (2026-10-22)


### Features

* run ATAK-CIV in a KubeVirt VM as a test client ([#18](https://github.com/jonathanagustin/uds-k3d-takserver/issues/18)) ([76bb3b1](https://github.com/jonathanagustin/uds-k3d-takserver/commit/76bb3b1ddb36c79b89f690fe88a1c333c3cbe356))


### Miscellaneous

* **deps:** replace support-deps with actions/attest v4.2.2 ([#92](https://github.com/jonathanagustin/uds-k3d-takserver/issues/92)) ([9f8d6cd](https://github.com/jonathanagustin/uds-k3d-takserver/commit/9f8d6cd89ef4a67f602ac8d4f27281b1c4cbe04b))
* **deps:** update cloudtak to v13.112.3 ([#93](https://github.com/jonathanagustin/uds-k3d-takserver/issues/93)) ([efca508](https://github.com/jonathanagustin/uds-k3d-takserver/commit/efca5080276788acc7e6fcb1c2ac6f583e39509e))
* **renovate:** hold the pepr overrides together with pepr ([#104](https://github.com/jonathanagustin/uds-k3d-takserver/issues/104)) ([eecc25d](https://github.com/jonathanagustin/uds-k3d-takserver/commit/eecc25d3f53fd59da37a78b185c01628d3527795))
* **renovate:** name major pull requests by dependency, hold the mise Java major and pepr ([#99](https://github.com/jonathanagustin/uds-k3d-takserver/issues/99)) ([8438da6](https://github.com/jonathanagustin/uds-k3d-takserver/commit/8438da61428e5f12220126bb6dd2044b753e137d))
* **renovate:** open major updates in their own pull requests ([#98](https://github.com/jonathanagustin/uds-k3d-takserver/issues/98)) ([e05e311](https://github.com/jonathanagustin/uds-k3d-takserver/commit/e05e311c0d821d34cf0f010fdccb6d3811ac2358))

## [0.4.0](https://github.com/jonathanagustin/uds-k3d-takserver/compare/v0.3.0...v0.4.0) (2026-10-22)


### Features

* add additionalNetworkAllow to the cloudtak chart and follow UDS client and metadata naming ([#87](https://github.com/jonathanagustin/uds-k3d-takserver/issues/87)) ([e5a4abf](https://github.com/jonathanagustin/uds-k3d-takserver/commit/e5a4abfbe5f68768c60845b00c283ee5ab035bb3))


### Bug Fixes

* let cloudtak's nginx start on a node with ipv6 disabled ([#83](https://github.com/jonathanagustin/uds-k3d-takserver/issues/83)) ([96e298d](https://github.com/jonathanagustin/uds-k3d-takserver/commit/96e298ddcb97405e8292d76106c0875830ed4f8e))


### Miscellaneous

* move the cloudtak chart to charts/ and the test values next to the test bundle ([#90](https://github.com/jonathanagustin/uds-k3d-takserver/issues/90)) ([67b9c6e](https://github.com/jonathanagustin/uds-k3d-takserver/commit/67b9c6eff6b4aa2c55849cb3febaccf7f91af03f))


### Documentation

* drop the image build from the quick start and list unmet package requirements ([#85](https://github.com/jonathanagustin/uds-k3d-takserver/issues/85)) ([0a1c6ed](https://github.com/jonathanagustin/uds-k3d-takserver/commit/0a1c6ed692ff1b2c48d83a3825c1516767a62460))

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
