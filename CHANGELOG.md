# Changelog

## [0.10.0](https://github.com/jonathanagustin/uds-takserver/compare/v0.9.1...v0.10.0) (2026-11-08)


### Features

* **bench:** retain bounded per-container capacity evidence ([#346](https://github.com/jonathanagustin/uds-takserver/issues/346)) ([8aacc1e](https://github.com/jonathanagustin/uds-takserver/commit/8aacc1e2d6f66c78b0602f7ce1bbc0c04b4ac01d))
* **compliance:** add foundational mappings and a manual crawl ([#349](https://github.com/jonathanagustin/uds-takserver/issues/349)) ([6566d75](https://github.com/jonathanagustin/uds-takserver/commit/6566d7534075117208c8c45b0a21712ba34d15c5))
* **docs:** publish versioned release and main documentation ([#348](https://github.com/jonathanagustin/uds-takserver/issues/348)) ([9cd5c2a](https://github.com/jonathanagustin/uds-takserver/commit/9cd5c2a944208248262150811dd9f48c12167493))
* **monitoring:** alert on CloudTAK health and TAK certificate expiry ([#329](https://github.com/jonathanagustin/uds-takserver/issues/329)) ([d69317e](https://github.com/jonathanagustin/uds-takserver/commit/d69317e8b02f02fe6e24041a8e1a786893b2b4b8))
* **portal:** customize browser tiles and add CloudTAK icon ([a8c1fcc](https://github.com/jonathanagustin/uds-takserver/commit/a8c1fcc9fffc9c139f66bda261bf50179f2c9ce8))
* **takclient:** revoke TAK-enrolled certificates without restarting pods ([953012a](https://github.com/jonathanagustin/uds-takserver/commit/953012af00e0ac4eec6098212e05a6a7f8ee904c))
* **takx:** add opt-in public CommonCommo build foundation ([#380](https://github.com/jonathanagustin/uds-takserver/issues/380)) ([0275ed7](https://github.com/jonathanagustin/uds-takserver/commit/0275ed7089874085bafba52b8a5d40560e32d89b))


### Bug Fixes

* **airgap:** avoid DNS lookups during firewall cleanup ([#365](https://github.com/jonathanagustin/uds-takserver/issues/365)) ([f8af744](https://github.com/jonathanagustin/uds-takserver/commit/f8af7442d67fe5b09e66ebad3dd89a911c417a9b))
* **airgap:** pin bundle images to the packaged TAK tag ([#361](https://github.com/jonathanagustin/uds-takserver/issues/361)) ([2accfc8](https://github.com/jonathanagustin/uds-takserver/commit/2accfc8074c4927fc38ac27a0541989f8c85580f))
* **airgap:** test direct transport reachability before isolation ([#360](https://github.com/jonathanagustin/uds-takserver/issues/360)) ([782a86d](https://github.com/jonathanagustin/uds-takserver/commit/782a86d53e71d3662ae72aea4de1257f7dda7dd6))
* **atak:** set the device guest to 2Gi ([#357](https://github.com/jonathanagustin/uds-takserver/issues/357)) ([b6b9bfe](https://github.com/jonathanagustin/uds-takserver/commit/b6b9bfe0e237d8e5d44e8978c71b458ae14a2343))
* **backup:** drain node-agent logs before reporting readiness ([#340](https://github.com/jonathanagustin/uds-takserver/issues/340)) ([159560a](https://github.com/jonathanagustin/uds-takserver/commit/159560aebc6d24750f356eb3ae183b15c4c9e18b))
* **bench:** compare matched workloads and retain measured evidence ([4f3384c](https://github.com/jonathanagustin/uds-takserver/commit/4f3384ca9dca477c84b1509e9570c3eacf7a5ca9))
* bound restore smoke and handle CloudTAK handshake resets ([54c42ba](https://github.com/jonathanagustin/uds-takserver/commit/54c42ba76c36114db5625cdcbc2961b3dd013b09))
* **ci:** refresh docs after release publication ([#379](https://github.com/jonathanagustin/uds-takserver/issues/379)) ([27f3880](https://github.com/jonathanagustin/uds-takserver/commit/27f3880c696f90528f19702104118de9d9f4147b))
* **docs:** recover transient downloads and avoid badge waits ([#378](https://github.com/jonathanagustin/uds-takserver/issues/378)) ([f32ee28](https://github.com/jonathanagustin/uds-takserver/commit/f32ee28c60474ce8da4105afa88114ec8b1f44bf))
* **docs:** restore README badges that GitHub camo could not fetch ([#311](https://github.com/jonathanagustin/uds-takserver/issues/311)) ([eb65d72](https://github.com/jonathanagustin/uds-takserver/commit/eb65d723c1135edbc98460a586dcdfa26ebac57b))
* **docs:** serve Release and License badges from the repo ([#314](https://github.com/jonathanagustin/uds-takserver/issues/314)) ([68b44db](https://github.com/jonathanagustin/uds-takserver/commit/68b44db46326285f6533d1ff4dd59a410f20b6c1))
* **docs:** serve the OpenSSF Scorecard badge from the repo ([#313](https://github.com/jonathanagustin/uds-takserver/issues/313)) ([703c9ad](https://github.com/jonathanagustin/uds-takserver/commit/703c9ad62546e9a77e6d7d24d83cbe15f35affe5))
* draw the architecture diagrams with plain SVG text ([#317](https://github.com/jonathanagustin/uds-takserver/issues/317)) ([cb4bd85](https://github.com/jonathanagustin/uds-takserver/commit/cb4bd8577795a541f7f2b16fba6a9eca2729f59b))
* pin CloudTAK build tooling and document human review rules ([815d013](https://github.com/jonathanagustin/uds-takserver/commit/815d0132e00a3bff0318773749fe54cb56eddf7d))
* skip diagnostic artifact uploads after failed tests ([2b594e8](https://github.com/jonathanagustin/uds-takserver/commit/2b594e8f040c16876060c3bd2a51b0b41bb557fb))
* stop CI diagnostics from printing rendered TAK config ([#316](https://github.com/jonathanagustin/uds-takserver/issues/316)) ([37efa68](https://github.com/jonathanagustin/uds-takserver/commit/37efa684f3bf17628d0a039a9c4f9d751d0696aa))
* **trust:** load the UDS CA bundle in CloudTAK and reload consumers ([#323](https://github.com/jonathanagustin/uds-takserver/issues/323)) ([fd3b725](https://github.com/jonathanagustin/uds-takserver/commit/fd3b7258a1beba3c21109bff61140a2a9d4f23b4))


### Miscellaneous

* migrate repository links and branding to uds-takserver ([#364](https://github.com/jonathanagustin/uds-takserver/issues/364)) ([ef2d1f8](https://github.com/jonathanagustin/uds-takserver/commit/ef2d1f8ba47568dc7d9137ee8d2a72d0e36dfef3))
* **renovate:** use the recommended preset name ([f24ff48](https://github.com/jonathanagustin/uds-takserver/commit/f24ff48fe3cabccb6e28fbd0197cf1bbb59c5989))
* update tooling patch versions ([#337](https://github.com/jonathanagustin/uds-takserver/issues/337)) ([0989ff3](https://github.com/jonathanagustin/uds-takserver/commit/0989ff3128364708782d22747156d8d73110fdaf))


### Documentation

* add TAKX setup guide and remove personal attribution ([#377](https://github.com/jonathanagustin/uds-takserver/issues/377)) ([3e41075](https://github.com/jonathanagustin/uds-takserver/commit/3e4107511cfe6fb13892a3feb029971662dc374e))
* add task-focused operational how-to guides ([c6f5ce5](https://github.com/jonathanagustin/uds-takserver/commit/c6f5ce58b4298b521781467d9a716fd160312d9b))
* align the landing page and navigation with UDS ([#369](https://github.com/jonathanagustin/uds-takserver/issues/369)) ([88917e9](https://github.com/jonathanagustin/uds-takserver/commit/88917e9a2292ed971038c207dcafc4a4e66f7a98))
* clarify ambient egress service account scope ([#381](https://github.com/jonathanagustin/uds-takserver/issues/381)) ([38ebd5c](https://github.com/jonathanagustin/uds-takserver/commit/38ebd5cc7c337242f19a5f257b19cda049416480))
* define branch protection for a solo maintainer ([14a7ff8](https://github.com/jonathanagustin/uds-takserver/commit/14a7ff8d2b8624fd0f41e4fc09938724dae946b6))
* document Velero chart ownership migration constraints ([#325](https://github.com/jonathanagustin/uds-takserver/issues/325)) ([c30fc6e](https://github.com/jonathanagustin/uds-takserver/commit/c30fc6e9a9adf710b7ab3a8588b84a9ef4a4fb4c))
* improve navigation and add browser coverage ([2e54695](https://github.com/jonathanagustin/uds-takserver/commit/2e54695560b7479934ab5a4f20d4b4eaf29de75c))
* match UDS styling and clarify operator guides ([#362](https://github.com/jonathanagustin/uds-takserver/issues/362)) ([61864a0](https://github.com/jonathanagustin/uds-takserver/commit/61864a056a4b3d691686e70f37c8aacd1f2fc518))
* record successful node-isolated airgap validation ([#371](https://github.com/jonathanagustin/uds-takserver/issues/371)) ([2ec9b30](https://github.com/jonathanagustin/uds-takserver/commit/2ec9b30c669527f5e5d2ad2281592ec97e0b7baa))
* refine landing page branding and search positioning ([#363](https://github.com/jonathanagustin/uds-takserver/issues/363)) ([9d00988](https://github.com/jonathanagustin/uds-takserver/commit/9d00988da94b28edd51b2e1d1586ea5f2ce39907))
* restore all status badges above the wordmark ([#370](https://github.com/jonathanagustin/uds-takserver/issues/370)) ([7fe7576](https://github.com/jonathanagustin/uds-takserver/commit/7fe7576ef28005f8bdd3fa76406c0d48d51415b3))
* simplify the README header ([#366](https://github.com/jonathanagustin/uds-takserver/issues/366)) ([bfe06dc](https://github.com/jonathanagustin/uds-takserver/commit/bfe06dc6460b0707ee5681238d005395871685dc))
* streamline guides and use native Starlight components ([#368](https://github.com/jonathanagustin/uds-takserver/issues/368)) ([3cf5084](https://github.com/jonathanagustin/uds-takserver/commit/3cf5084f81d54641fab7d55b938d0c5dd733e017))

## [0.9.1](https://github.com/jonathanagustin/uds-takserver/compare/v0.9.0...v0.9.1) (2026-11-05)


### Bug Fixes

* **docs-site:** rewrite raw HTML image paths from the README ([#308](https://github.com/jonathanagustin/uds-takserver/issues/308)) ([932b41d](https://github.com/jonathanagustin/uds-takserver/commit/932b41d777ed4dea331a80d8c2abc895e49c0945))


### Documentation

* **adr:** revoke TakClient certs through TAK's certificate table ([#310](https://github.com/jonathanagustin/uds-takserver/issues/310)) ([90dd8d5](https://github.com/jonathanagustin/uds-takserver/commit/90dd8d5c9caa0176c1c8d150619b8aa0fbbf5ef7))
* expand first-use acronyms and clear a few unclear phrases ([#305](https://github.com/jonathanagustin/uds-takserver/issues/305)) ([3e9f6cd](https://github.com/jonathanagustin/uds-takserver/commit/3e9f6cdfc82459ccd95ef1336e990af0bf303127))
* **site:** add favicon, fix Test badge and home preview, render GitHub alerts ([#304](https://github.com/jonathanagustin/uds-takserver/issues/304)) ([45ba1da](https://github.com/jonathanagustin/uds-takserver/commit/45ba1da8beb3a42c5e310ea9ed48729a65caf60a))
* title the project TAK Server on UDS ([#307](https://github.com/jonathanagustin/uds-takserver/issues/307)) ([b471f89](https://github.com/jonathanagustin/uds-takserver/commit/b471f899e5369d0bf37e3761bc0eb7f888aa0a60))

## [0.9.0](https://github.com/jonathanagustin/uds-takserver/compare/v0.8.0...v0.9.0) (2026-11-05)


### Features

* **pepr:** add a TakClient operator that issues TAK client certificates ([#271](https://github.com/jonathanagustin/uds-takserver/issues/271)) ([7c5cba6](https://github.com/jonathanagustin/uds-takserver/commit/7c5cba66516df548d5d0c4ed176b087a35b251e5))
* **uptime:** check TAK's mTLS client ports with a tak-health pod ([#280](https://github.com/jonathanagustin/uds-takserver/issues/280)) ([21335ac](https://github.com/jonathanagustin/uds-takserver/commit/21335aca65a360417172e1877aff3fafb8938e0e))


### Bug Fixes

* **chart:** config waits for stale Ignite client nodes to leave before it starts ([#299](https://github.com/jonathanagustin/uds-takserver/issues/299)) ([9217f99](https://github.com/jonathanagustin/uds-takserver/commit/9217f99c66bdbdfca7c2f102230ad0f6cd5eb7c7)), closes [#298](https://github.com/jonathanagustin/uds-takserver/issues/298)
* **pepr:** wait for Ignite to drop stopped TAK nodes before the restart ([#297](https://github.com/jonathanagustin/uds-takserver/issues/297)) ([5d75f9e](https://github.com/jonathanagustin/uds-takserver/commit/5d75f9e1ce4f33a784fc5566194e6bdc72c41245)), closes [#296](https://github.com/jonathanagustin/uds-takserver/issues/296)


### Documentation

* **demo:** posters, stills and chapter times from the restyled videos ([#293](https://github.com/jonathanagustin/uds-takserver/issues/293)) ([1a9286b](https://github.com/jonathanagustin/uds-takserver/commit/1a9286bcc00b4d124ded868dce5374abb2d04c9e))
* **demo:** v0.8.0 recording: chapter clips and stills on the doc pages ([#291](https://github.com/jonathanagustin/uds-takserver/issues/291)) ([9d3d55b](https://github.com/jonathanagustin/uds-takserver/commit/9d3d55b2cd4765d5da77c7c1b693448f874cd2d1))
* **readme:** fill the cutoff caption band in the screenshots ([#303](https://github.com/jonathanagustin/uds-takserver/issues/303)) ([5d992bc](https://github.com/jonathanagustin/uds-takserver/commit/5d992bc1adff1662a399e320a7f074c9b24dab38))
* **readme:** play the updated demo videos inline ([#294](https://github.com/jonathanagustin/uds-takserver/issues/294)) ([35e5489](https://github.com/jonathanagustin/uds-takserver/commit/35e5489491c94ad303a8c3e0ada8f1f3ed7d21eb))
* **readme:** show the ATAK device and CloudTAK map side by side ([#301](https://github.com/jonathanagustin/uds-takserver/issues/301)) ([253bb96](https://github.com/jonathanagustin/uds-takserver/commit/253bb96ec2936054e0bdd302577f2af51cc9e308))
* **readme:** stack the ATAK device and CloudTAK screenshots ([#302](https://github.com/jonathanagustin/uds-takserver/issues/302)) ([642806d](https://github.com/jonathanagustin/uds-takserver/commit/642806da2e9d3b928f547efa6f5af410af921f2d))

## [0.8.0](https://github.com/jonathanagustin/uds-takserver/compare/v0.7.1...v0.8.0) (2026-11-04)


### Features

* **cloudtak:** let a non-admin group sign in to CloudTAK ([#263](https://github.com/jonathanagustin/uds-takserver/issues/263)) ([984c0a3](https://github.com/jonathanagustin/uds-takserver/commit/984c0a3953426f6aace7446a4538db7c72609ed2)), closes [#262](https://github.com/jonathanagustin/uds-takserver/issues/262)
* **demo:** chapter clips, doc stills, and real upgrade and regular-user chapters ([#268](https://github.com/jonathanagustin/uds-takserver/issues/268)) ([6b5ef8e](https://github.com/jonathanagustin/uds-takserver/commit/6b5ef8ea0c14da00b837f6886123a4cfbb73fba1))
* expose TAK QUIC on UDP 8090 through Envoy Gateway ([#188](https://github.com/jonathanagustin/uds-takserver/issues/188)) ([288f62c](https://github.com/jonathanagustin/uds-takserver/commit/288f62cd6d7e5b6cb6db29c37bfad7f5b9ca827f))
* **pepr:** set plugins memory from package values ([#275](https://github.com/jonathanagustin/uds-takserver/issues/275)) ([69c0efa](https://github.com/jonathanagustin/uds-takserver/commit/69c0efa76dba2ab17876a263c54a222ab8e3ae03))


### Bug Fixes

* **bench:** pair image pulls per container so pull time is never negative ([#250](https://github.com/jonathanagustin/uds-takserver/issues/250)) ([cfd43c4](https://github.com/jonathanagustin/uds-takserver/commit/cfd43c4e257c1d15c3576f1a3eef7dc1e2e95279))
* **ci:** free disk in the upgrade test and fail early when the runner is too small ([#287](https://github.com/jonathanagustin/uds-takserver/issues/287)) ([004c11d](https://github.com/jonathanagustin/uds-takserver/commit/004c11d772483518b757ff33d4e830366671e05c))
* **ci:** retry the Copa patch when the package mirror drops ([#249](https://github.com/jonathanagustin/uds-takserver/issues/249)) ([6ff6e6a](https://github.com/jonathanagustin/uds-takserver/commit/6ff6e6af95fee2c2f1a2d8473cc43bd7e5e1ffcb))
* close the code gaps from the 0.7 docs audit ([#246](https://github.com/jonathanagustin/uds-takserver/issues/246)) ([03dc46a](https://github.com/jonathanagustin/uds-takserver/commit/03dc46aac051e17f899676d5d06a92e0c5f9fe42))
* **falco:** skip the cert-init container and redact passwords from CI logs ([#248](https://github.com/jonathanagustin/uds-takserver/issues/248)) ([710d674](https://github.com/jonathanagustin/uds-takserver/commit/710d67483b85a08c9004970016ee2064f87d2f61))
* **pepr:** send the TAK Deployments and Ignite objects to admission ([#274](https://github.com/jonathanagustin/uds-takserver/issues/274)) ([e512984](https://github.com/jonathanagustin/uds-takserver/commit/e512984280050bef184b5341209df6b9aee392a7))
* **uptime:** probe TAK's own /login page and follow the UDS Core uptime pattern ([#253](https://github.com/jonathanagustin/uds-takserver/issues/253)) ([97e54b3](https://github.com/jonathanagustin/uds-takserver/commit/97e54b37d1bb2ca4050927e457a7db4e5d1f5f18))


### Miscellaneous

* **deps:** pnpm 12.16.1 for the Playwright tests (refs [#103](https://github.com/jonathanagustin/uds-takserver/issues/103)) ([#278](https://github.com/jonathanagustin/uds-takserver/issues/278)) ([41c926d](https://github.com/jonathanagustin/uds-takserver/commit/41c926da318f5c372a1a5b9cefacefc6894ada84))
* **deps:** update helm to v4.3.1 ([#251](https://github.com/jonathanagustin/uds-takserver/issues/251)) ([e1fb513](https://github.com/jonathanagustin/uds-takserver/commit/e1fb51307959c5b188134db165b6185b2753a094))
* **deps:** update nats to v2.15.2 ([#247](https://github.com/jonathanagustin/uds-takserver/issues/247)) ([5b81c0b](https://github.com/jonathanagustin/uds-takserver/commit/5b81c0b8e3fbfd564198a6e9c98de156cd74259d))
* **deps:** update tak server package dependencies ([#242](https://github.com/jonathanagustin/uds-takserver/issues/242)) ([cf65254](https://github.com/jonathanagustin/uds-takserver/commit/cf6525411cace7ac895b8775d401e5d3ed2a65e5))
* **deps:** update tak server support dependencies ([#243](https://github.com/jonathanagustin/uds-takserver/issues/243)) ([48ac7b1](https://github.com/jonathanagustin/uds-takserver/commit/48ac7b114317acf2e53e4a35a0df337369404396))
* move to node 26 where it builds and batch Renovate weekly ([#265](https://github.com/jonathanagustin/uds-takserver/issues/265)) ([aa6635b](https://github.com/jonathanagustin/uds-takserver/commit/aa6635b7e38aa65fa62e1ec00210cb50b9eeefa4))
* **pepr:** describe all five capabilities and track the release version ([#270](https://github.com/jonathanagustin/uds-takserver/issues/270)) ([a1192bb](https://github.com/jonathanagustin/uds-takserver/commit/a1192bbbba47368713dc1d1cda1b92b3ad8ff2e1))


### Documentation

* **adr:** record why the upstream chart is adapted with Pepr ([#272](https://github.com/jonathanagustin/uds-takserver/issues/272)) ([2622e5b](https://github.com/jonathanagustin/uds-takserver/commit/2622e5bc21176b2affb9d1842d80993477d36f94))
* bring the guides up to 0.7 and fix the docs site layout ([#244](https://github.com/jonathanagustin/uds-takserver/issues/244)) ([4fa887d](https://github.com/jonathanagustin/uds-takserver/commit/4fa887dd27f6f4c6551217f05ca795c25c78fb69))
* **building:** stop naming a stale UBI tag and note PostGIS gets Copa ([#252](https://github.com/jonathanagustin/uds-takserver/issues/252)) ([1577067](https://github.com/jonathanagustin/uds-takserver/commit/15770677cb3eaa5f4b1a683e382173b28848e906))

## [0.7.1](https://github.com/jonathanagustin/uds-takserver/compare/v0.7.0...v0.7.1) (2026-11-02)


### Bug Fixes

* **ci:** check out the repo in the Full Core gate on every event ([#240](https://github.com/jonathanagustin/uds-takserver/issues/240)) ([ccaab20](https://github.com/jonathanagustin/uds-takserver/commit/ccaab20dc61ae5d292e4cde4cde2318ad90fa5e0))

## [0.7.0](https://github.com/jonathanagustin/uds-takserver/compare/v0.6.0...v0.7.0) (2026-11-02)


### Features

* add a TAK Grafana dashboard and alert rules ([#182](https://github.com/jonathanagustin/uds-takserver/issues/182)) ([311ff82](https://github.com/jonathanagustin/uds-takserver/commit/311ff8204a3920ceb48cfe7d7609b1fed968a7c9)), closes [#27](https://github.com/jonathanagustin/uds-takserver/issues/27)
* add an optional Velero node-agent for volume backups ([#203](https://github.com/jonathanagustin/uds-takserver/issues/203)) ([e449302](https://github.com/jonathanagustin/uds-takserver/commit/e4493025232e1141b3cdae84148d0dfaaf1249f4))
* add small and production values profiles ([#195](https://github.com/jonathanagustin/uds-takserver/issues/195)) ([b6506ae](https://github.com/jonathanagustin/uds-takserver/commit/b6506ae5300ea6006bed9b12eac349629b99658f))
* admit TAK startup shape before the first pod ([#200](https://github.com/jonathanagustin/uds-takserver/issues/200)) ([f739057](https://github.com/jonathanagustin/uds-takserver/commit/f739057a5a0947229b6c696392c0e52beef58616)), closes [#43](https://github.com/jonathanagustin/uds-takserver/issues/43)
* collect Falco events and add a TAK cert-write rule ([#184](https://github.com/jonathanagustin/uds-takserver/issues/184)) ([bb97380](https://github.com/jonathanagustin/uds-takserver/commit/bb97380b6b0a45fe8591e937bda0dbc66cc3ec9d)), closes [#30](https://github.com/jonathanagustin/uds-takserver/issues/30)
* end the CloudTAK Keycloak session on logout ([#187](https://github.com/jonathanagustin/uds-takserver/issues/187)) ([6e9bc51](https://github.com/jonathanagustin/uds-takserver/commit/6e9bc51c8e506151b439364a578458691e561006)), closes [#31](https://github.com/jonathanagustin/uds-takserver/issues/31)
* expose domain, image tag, and DNS as Zarf package values ([#202](https://github.com/jonathanagustin/uds-takserver/issues/202)) ([1edd06e](https://github.com/jonathanagustin/uds-takserver/commit/1edd06e2f82c5e32183291f12e943b6853157c58)), closes [#38](https://github.com/jonathanagustin/uds-takserver/issues/38)
* fire target-down from kube-state and screenshot the dashboard ([#204](https://github.com/jonathanagustin/uds-takserver/issues/204)) ([5c9bfd2](https://github.com/jonathanagustin/uds-takserver/commit/5c9bfd2d918adc511df518228ecc3cb503bdde44))
* probe TAK and CloudTAK uptime in the full-core job ([#183](https://github.com/jonathanagustin/uds-takserver/issues/183)) ([702dbe7](https://github.com/jonathanagustin/uds-takserver/commit/702dbe7202ed17e76302e93e89e01ad856a00b98)), closes [#28](https://github.com/jonathanagustin/uds-takserver/issues/28)
* record messaging and API start phases ([#201](https://github.com/jonathanagustin/uds-takserver/issues/201)) ([abf61c3](https://github.com/jonathanagustin/uds-takserver/commit/abf61c35e7d6b5081400f62994f76a6d21bdb6ed))
* replace the deploy-time shell actions with Pepr reconciles ([#177](https://github.com/jonathanagustin/uds-takserver/issues/177)) ([3e9fab2](https://github.com/jonathanagustin/uds-takserver/commit/3e9fab2816f7d2c8f7eee803bda39b76c34fb003)), closes [#35](https://github.com/jonathanagustin/uds-takserver/issues/35)
* restore TAK and CloudTAK from a logical dump ([#181](https://github.com/jonathanagustin/uds-takserver/issues/181)) ([cbb5651](https://github.com/jonathanagustin/uds-takserver/commit/cbb5651e2031e9282d7940718f4216955336e260)), closes [#25](https://github.com/jonathanagustin/uds-takserver/issues/25)
* run NATS 2.15 with the upstream chart ([#210](https://github.com/jonathanagustin/uds-takserver/issues/210)) ([0234818](https://github.com/jonathanagustin/uds-takserver/commit/023481886924269a8d135ac98aaa0d2d97a92714))
* scrape TAK and the Pepr module from Prometheus ([#206](https://github.com/jonathanagustin/uds-takserver/issues/206)) ([28c1e04](https://github.com/jonathanagustin/uds-takserver/commit/28c1e0474b327b347f71e356c705d1ff830a7b55))
* upgrade the PostGIS image to PostgreSQL 18 ([#208](https://github.com/jonathanagustin/uds-takserver/issues/208)) ([0f27f60](https://github.com/jonathanagustin/uds-takserver/commit/0f27f6039fb6585bdfeb32dfc52b5ae0c705efeb)), closes [#100](https://github.com/jonathanagustin/uds-takserver/issues/100)


### Bug Fixes

* **atak:** run KubeVirt v1.9.1 with the ImageVolume gate off ([#225](https://github.com/jonathanagustin/uds-takserver/issues/225)) ([e029ab9](https://github.com/jonathanagustin/uds-takserver/commit/e029ab9d649e8e933c6d1e4244e88443263ca4c0))
* **backup:** gzip the logical database dumps ([#237](https://github.com/jonathanagustin/uds-takserver/issues/237)) ([f16d14e](https://github.com/jonathanagustin/uds-takserver/commit/f16d14e98a946faf2805abf4bb64dcb959df67b2))
* **bench:** put each config's changes back before the next one ([#228](https://github.com/jonathanagustin/uds-takserver/issues/228)) ([ef05472](https://github.com/jonathanagustin/uds-takserver/commit/ef05472c073d00f90329869899dfcfd4d40a3bf6))
* **ci:** give Full Core 8G of swap and stop SIGPIPE from failing its checks ([#233](https://github.com/jonathanagustin/uds-takserver/issues/233)) ([28d86e3](https://github.com/jonathanagustin/uds-takserver/commit/28d86e3a9598cafbfbb9700609869964b62550f9))
* **deps:** update node-forge to 1.4.2 and hold minimatch 10 so the OSV check passes ([#224](https://github.com/jonathanagustin/uds-takserver/issues/224)) ([8e1ad37](https://github.com/jonathanagustin/uds-takserver/commit/8e1ad37b66f5fe67b07b58910f1f99d2a3314017))
* **deps:** update tak server support dependencies ([#218](https://github.com/jonathanagustin/uds-takserver/issues/218)) ([2f70651](https://github.com/jonathanagustin/uds-takserver/commit/2f70651f598ed4b4c78b2ac77763d17c879e3235))
* **deps:** update undici to 8.12.3 and body-parser to 2.4.0 in the Pepr module ([#152](https://github.com/jonathanagustin/uds-takserver/issues/152)) ([ed67a99](https://github.com/jonathanagustin/uds-takserver/commit/ed67a99028ba5bbbfa4a09a42ecb51f04b99beb9))
* give the takserver-oidc watcher 512Mi so it is not OOM-killed ([#234](https://github.com/jonathanagustin/uds-takserver/issues/234)) ([ae5dc46](https://github.com/jonathanagustin/uds-takserver/commit/ae5dc4660f39459dd23affc023a2d6113a6b0536))
* keep keystore passwords in a Secret ([#168](https://github.com/jonathanagustin/uds-takserver/issues/168)) ([3e777d1](https://github.com/jonathanagustin/uds-takserver/commit/3e777d1533023cf1d9e8dabd5b50c0608e9f7661)), closes [#67](https://github.com/jonathanagustin/uds-takserver/issues/67)
* keep TAK private keys out of ConfigMaps ([#205](https://github.com/jonathanagustin/uds-takserver/issues/205)) ([e06628a](https://github.com/jonathanagustin/uds-takserver/commit/e06628a210b3e358341e7c5f01115e3b409b8581)), closes [#67](https://github.com/jonathanagustin/uds-takserver/issues/67)
* plot both architectures on one scale ([#214](https://github.com/jonathanagustin/uds-takserver/issues/214)) ([c2af60d](https://github.com/jonathanagustin/uds-takserver/commit/c2af60d70dc0bf85ac24150f43259b4444a24bd1))
* **renovate:** drop host rules that need Iron Bank secrets ([#172](https://github.com/jonathanagustin/uds-takserver/issues/172)) ([4c0a414](https://github.com/jonathanagustin/uds-takserver/commit/4c0a4149bbed8c10198b81ae99693a418540eceb)), closes [#171](https://github.com/jonathanagustin/uds-takserver/issues/171)
* repair the full-core test steps that never ran ([#215](https://github.com/jonathanagustin/uds-takserver/issues/215)) ([4082510](https://github.com/jonathanagustin/uds-takserver/commit/40825104dc97f8e4a11ec68338df91fb675897c7))
* retry refused API handshakes in the cert-init hooks ([#176](https://github.com/jonathanagustin/uds-takserver/issues/176)) ([8a8ff80](https://github.com/jonathanagustin/uds-takserver/commit/8a8ff80f01582c7288785d1c94c04c09139b6e84)), closes [#168](https://github.com/jonathanagustin/uds-takserver/issues/168)
* run the TAK database dump with the PostgreSQL 18 image ([#229](https://github.com/jonathanagustin/uds-takserver/issues/229)) ([48c02c0](https://github.com/jonathanagustin/uds-takserver/commit/48c02c050a0941d4d95919d1b8f449152c0040ce))
* stop a cached CoreConfig from replacing the local file ([#174](https://github.com/jonathanagustin/uds-takserver/issues/174)) ([b36a6e2](https://github.com/jonathanagustin/uds-takserver/commit/b36a6e2f27d4a53019a47fef65330452ddf5b6d6)), closes [#3](https://github.com/jonathanagustin/uds-takserver/issues/3)
* wait for the app pods to be gone before the restore reloads the databases ([#216](https://github.com/jonathanagustin/uds-takserver/issues/216)) ([83293b2](https://github.com/jonathanagustin/uds-takserver/commit/83293b2e422fed7c9b6510681a4b1ac5fb46a1b6))


### Miscellaneous

* align slim core version, fix docs drift, tighten CI token permissions ([#155](https://github.com/jonathanagustin/uds-takserver/issues/155)) ([22ac952](https://github.com/jonathanagustin/uds-takserver/commit/22ac95296ce02527ab6ca552eb090285c385dd0f)), closes [#161](https://github.com/jonathanagustin/uds-takserver/issues/161)
* **atak:** install the viewer's runtime dependencies from a lockfile ([#150](https://github.com/jonathanagustin/uds-takserver/issues/150)) ([41e4639](https://github.com/jonathanagustin/uds-takserver/commit/41e463982d68b7eb7f898fcbd3cfb0eb0111a1d8))
* **atak:** record why the APK builder's urllib3 advisories are ignored ([#153](https://github.com/jonathanagustin/uds-takserver/issues/153)) ([7faaa9d](https://github.com/jonathanagustin/uds-takserver/commit/7faaa9dfad09b94ce59732ef1e392610b8e06775))
* **deps:** update tak server package dependencies ([#217](https://github.com/jonathanagustin/uds-takserver/issues/217)) ([ff8cb46](https://github.com/jonathanagustin/uds-takserver/commit/ff8cb46e434ea22ac417bb80d9ba8c6c066adbe9))
* record the protobuf advisories the load tester cannot take ([#220](https://github.com/jonathanagustin/uds-takserver/issues/220)) ([d37aa46](https://github.com/jonathanagustin/uds-takserver/commit/d37aa46e6393185059100c44532f49a995eb0a0d))
* **renovate:** extend the uds-common preset ([#170](https://github.com/jonathanagustin/uds-takserver/issues/170)) ([62e2401](https://github.com/jonathanagustin/uds-takserver/commit/62e2401140607098a3f07b77ca58b073464ec135)), closes [#162](https://github.com/jonathanagustin/uds-takserver/issues/162)


### Documentation

* add a Starlight site for the existing guides ([#173](https://github.com/jonathanagustin/uds-takserver/issues/173)) ([e8e11f4](https://github.com/jonathanagustin/uds-takserver/commit/e8e11f4c797f45aa623a382b6bc14dece107b773))
* keep release-please instead of the template tag flow ([#180](https://github.com/jonathanagustin/uds-takserver/issues/180)) ([599b7f0](https://github.com/jonathanagustin/uds-takserver/commit/599b7f09ac0bf2cea6bc8b2778136505fc2d7b43)), closes [#164](https://github.com/jonathanagustin/uds-takserver/issues/164)
* keep the TAK builder on Java 17 ([#209](https://github.com/jonathanagustin/uds-takserver/issues/209)) ([ce0c438](https://github.com/jonathanagustin/uds-takserver/commit/ce0c4380e443300960d33d24eb5ee8d47157acaf)), closes [#101](https://github.com/jonathanagustin/uds-takserver/issues/101)
* record the two Scorecard pins that are not registry deps ([#221](https://github.com/jonathanagustin/uds-takserver/issues/221)) ([7016bc7](https://github.com/jonathanagustin/uds-takserver/commit/7016bc72b0079aaab340867b1528dd4fa6fb7b56))
* record why only the upstream flavor ships ([#178](https://github.com/jonathanagustin/uds-takserver/issues/178)) ([e7fafea](https://github.com/jonathanagustin/uds-takserver/commit/e7fafea6a9d6f9602ffbd092a12652a9af7c3be9)), closes [#163](https://github.com/jonathanagustin/uds-takserver/issues/163)
* rewrite the docs in plain language and fill gaps ([#226](https://github.com/jonathanagustin/uds-takserver/issues/226)) ([4af9b61](https://github.com/jonathanagustin/uds-takserver/commit/4af9b61defce6d97637537fac7b9dc0c9e057cda))

## [0.6.0](https://github.com/jonathanagustin/uds-takserver/compare/v0.5.4...v0.6.0) (2026-10-24)


### Features

* add a package icon for UDS Portal and the registry ([#149](https://github.com/jonathanagustin/uds-takserver/issues/149)) ([1d9768e](https://github.com/jonathanagustin/uds-takserver/commit/1d9768ecd0423c233a6d3c7ff676fd4e42fd5e0c))
* **ci:** attest the TAK, CloudTAK and PostGIS images ([#143](https://github.com/jonathanagustin/uds-takserver/issues/143)) ([140d6ec](https://github.com/jonathanagustin/uds-takserver/commit/140d6ec8aefb455059a81d12dd05e2d8a98ef788))
* **demo:** sign the demo videos and attach their provenance ([#147](https://github.com/jonathanagustin/uds-takserver/issues/147)) ([9844122](https://github.com/jonathanagustin/uds-takserver/commit/98441223871fdc6569a5c87c253e1bd707af487d))
* match the client ServiceAccount on pod-to-pod Ingress rules ([#151](https://github.com/jonathanagustin/uds-takserver/issues/151)) ([168a14a](https://github.com/jonathanagustin/uds-takserver/commit/168a14aba26cd350a009ccf5ce9bcabac735417c))
* **release:** attach the provenance as an intoto.jsonl asset and verify it ([#142](https://github.com/jonathanagustin/uds-takserver/issues/142)) ([b1120c9](https://github.com/jonathanagustin/uds-takserver/commit/b1120c9ad6bff7bcb5aad06c2d33ae79dba47a56))


### Bug Fixes

* **cloudtak:** drop the unused build tools from the runtime image ([#141](https://github.com/jonathanagustin/uds-takserver/issues/141)) ([33c9f0f](https://github.com/jonathanagustin/uds-takserver/commit/33c9f0f6d0278a0633b627db3b4756cbd0f892d6))
* give NATS and its reloader requests and limits ([#148](https://github.com/jonathanagustin/uds-takserver/issues/148)) ([0a52608](https://github.com/jonathanagustin/uds-takserver/commit/0a52608ad304e0f227378a3811b0bcdd94906cb3))


### Miscellaneous

* **deps:** update package-deps to a3554c0 ([#137](https://github.com/jonathanagustin/uds-takserver/issues/137)) ([a08cb15](https://github.com/jonathanagustin/uds-takserver/commit/a08cb15bd086fe3ab91590829803b0bc1c72f339))
* **deps:** update support-deps to v17.0.21+9 ([#138](https://github.com/jonathanagustin/uds-takserver/issues/138)) ([4baee63](https://github.com/jonathanagustin/uds-takserver/commit/4baee634f25a94444a290cf187bf3c3c788e6980))
* drop the unknown adoptium datasource from the java pin ([#145](https://github.com/jonathanagustin/uds-takserver/issues/145)) ([358b615](https://github.com/jonathanagustin/uds-takserver/commit/358b615948290a0d818bd9c2ab9d7c1768b94a65))
* pin the remaining CI and build downloads by hash ([#144](https://github.com/jonathanagustin/uds-takserver/issues/144)) ([9fc5148](https://github.com/jonathanagustin/uds-takserver/commit/9fc5148ec7cea32ad6cd910384c1abc6c8597895))

## [0.5.4](https://github.com/jonathanagustin/uds-takserver/compare/v0.5.3...v0.5.4) (2026-10-23)


### Bug Fixes

* **demo:** close the TEST MARKER pane before the chat scene ([#134](https://github.com/jonathanagustin/uds-takserver/issues/134)) ([7a5b3d5](https://github.com/jonathanagustin/uds-takserver/commit/7a5b3d5665ca4d14833069d9cae7a0a252ae414d))


### Documentation

* link the demo video downloads to the demo release ([#133](https://github.com/jonathanagustin/uds-takserver/issues/133)) ([6d7afd6](https://github.com/jonathanagustin/uds-takserver/commit/6d7afd6dd86644a4f8e3937ef0d49c9663f3bcba))

## [0.5.3](https://github.com/jonathanagustin/uds-takserver/compare/v0.5.2...v0.5.3) (2026-10-23)


### Bug Fixes

* **ci:** skip the release on the commit under test when picking the upgrade baseline ([#128](https://github.com/jonathanagustin/uds-takserver/issues/128)) ([a151a3b](https://github.com/jonathanagustin/uds-takserver/commit/a151a3b18b6b8927620e6eec07897724319dc978))
* quote the cloudtak secret checksum annotation ([#130](https://github.com/jonathanagustin/uds-takserver/issues/130)) ([698f853](https://github.com/jonathanagustin/uds-takserver/commit/698f85309c24e38ef80f46c0ec3d5bff3e7163fb))


### Miscellaneous

* pin the atak viewer node base image by digest ([#129](https://github.com/jonathanagustin/uds-takserver/issues/129)) ([42b4fa8](https://github.com/jonathanagustin/uds-takserver/commit/42b4fa8c531bba3b87490e1c93fdad0d5ac8cf69))


### Documentation

* keep the README release examples on the current version ([#123](https://github.com/jonathanagustin/uds-takserver/issues/123)) ([0bfae62](https://github.com/jonathanagustin/uds-takserver/commit/0bfae629e750e5307c7511dfaab2c58e06f4c4a8))
* list the atak test device's kubevirt exemption and check it ([#124](https://github.com/jonathanagustin/uds-takserver/issues/124)) ([f550459](https://github.com/jonathanagustin/uds-takserver/commit/f550459d13df668c7cf9667e126bd99ea07f78b1))

## [0.5.2](https://github.com/jonathanagustin/uds-takserver/compare/v0.5.1...v0.5.2) (2026-10-22)


### Documentation

* add demo videos to README ([#107](https://github.com/jonathanagustin/uds-takserver/issues/107)) ([7526bc2](https://github.com/jonathanagustin/uds-takserver/commit/7526bc27c9bce22b791d0fe83c4e89c4ab3a78f9))
* play the demo videos inline in the README ([#110](https://github.com/jonathanagustin/uds-takserver/issues/110)) ([c97bb8d](https://github.com/jonathanagustin/uds-takserver/commit/c97bb8de80c01ebec839de311bc76c332d4d7e12))

## [0.5.1](https://github.com/jonathanagustin/uds-takserver/compare/v0.5.0...v0.5.1) (2026-10-22)


### Bug Fixes

* **demo:** repair the CloudTAK sync scenes and name chapters after their cards ([#106](https://github.com/jonathanagustin/uds-takserver/issues/106)) ([fce36d2](https://github.com/jonathanagustin/uds-takserver/commit/fce36d2c9fda7ec2b25208b93a92029d2edd94eb))


### Miscellaneous

* **deps:** update tak server package dependencies ([#94](https://github.com/jonathanagustin/uds-takserver/issues/94)) ([73074fd](https://github.com/jonathanagustin/uds-takserver/commit/73074fd3df982354e7ab8d670915db29b6d58aad))
* **deps:** update tak server support dependencies ([#95](https://github.com/jonathanagustin/uds-takserver/issues/95)) ([af5506c](https://github.com/jonathanagustin/uds-takserver/commit/af5506cdd1bd6ea8dd57e146333af3e42f2aae06))

## [0.5.0](https://github.com/jonathanagustin/uds-takserver/compare/v0.4.0...v0.5.0) (2026-10-22)


### Features

* run ATAK-CIV in a KubeVirt VM as a test client ([#18](https://github.com/jonathanagustin/uds-takserver/issues/18)) ([76bb3b1](https://github.com/jonathanagustin/uds-takserver/commit/76bb3b1ddb36c79b89f690fe88a1c333c3cbe356))


### Miscellaneous

* **deps:** replace support-deps with actions/attest v4.2.2 ([#92](https://github.com/jonathanagustin/uds-takserver/issues/92)) ([9f8d6cd](https://github.com/jonathanagustin/uds-takserver/commit/9f8d6cd89ef4a67f602ac8d4f27281b1c4cbe04b))
* **deps:** update cloudtak to v13.112.3 ([#93](https://github.com/jonathanagustin/uds-takserver/issues/93)) ([efca508](https://github.com/jonathanagustin/uds-takserver/commit/efca5080276788acc7e6fcb1c2ac6f583e39509e))
* **renovate:** hold the pepr overrides together with pepr ([#104](https://github.com/jonathanagustin/uds-takserver/issues/104)) ([eecc25d](https://github.com/jonathanagustin/uds-takserver/commit/eecc25d3f53fd59da37a78b185c01628d3527795))
* **renovate:** name major pull requests by dependency, hold the mise Java major and pepr ([#99](https://github.com/jonathanagustin/uds-takserver/issues/99)) ([8438da6](https://github.com/jonathanagustin/uds-takserver/commit/8438da61428e5f12220126bb6dd2044b753e137d))
* **renovate:** open major updates in their own pull requests ([#98](https://github.com/jonathanagustin/uds-takserver/issues/98)) ([e05e311](https://github.com/jonathanagustin/uds-takserver/commit/e05e311c0d821d34cf0f010fdccb6d3811ac2358))

## [0.4.0](https://github.com/jonathanagustin/uds-takserver/compare/v0.3.0...v0.4.0) (2026-10-22)


### Features

* add additionalNetworkAllow to the cloudtak chart and follow UDS client and metadata naming ([#87](https://github.com/jonathanagustin/uds-takserver/issues/87)) ([e5a4abf](https://github.com/jonathanagustin/uds-takserver/commit/e5a4abfbe5f68768c60845b00c283ee5ab035bb3))


### Bug Fixes

* let cloudtak's nginx start on a node with ipv6 disabled ([#83](https://github.com/jonathanagustin/uds-takserver/issues/83)) ([96e298d](https://github.com/jonathanagustin/uds-takserver/commit/96e298ddcb97405e8292d76106c0875830ed4f8e))


### Miscellaneous

* move the cloudtak chart to charts/ and the test values next to the test bundle ([#90](https://github.com/jonathanagustin/uds-takserver/issues/90)) ([67b9c6e](https://github.com/jonathanagustin/uds-takserver/commit/67b9c6eff6b4aa2c55849cb3febaccf7f91af03f))


### Documentation

* drop the image build from the quick start and list unmet package requirements ([#85](https://github.com/jonathanagustin/uds-takserver/issues/85)) ([0a1c6ed](https://github.com/jonathanagustin/uds-takserver/commit/0a1c6ed692ff1b2c48d83a3825c1516767a62460))

## [0.3.0](https://github.com/jonathanagustin/uds-takserver/compare/v0.2.0...v0.3.0) (2026-10-22)


### Features

* add renovate fix, uptime probes, exemption docs, package metadata and portal tiles ([#72](https://github.com/jonathanagustin/uds-takserver/issues/72)) ([4880f21](https://github.com/jonathanagustin/uds-takserver/commit/4880f21d3076967be473e3eb7c289053fda74697))
* build the postgis image in this repository for amd64 and arm64 ([#81](https://github.com/jonathanagustin/uds-takserver/issues/81)) ([f0bb485](https://github.com/jonathanagustin/uds-takserver/commit/f0bb485a3d6ec523bfa9e682fe15e737ab1efdc4))


### Bug Fixes

* **ci:** strip color codes from the released package definition before checking its version ([#70](https://github.com/jonathanagustin/uds-takserver/issues/70)) ([c992016](https://github.com/jonathanagustin/uds-takserver/commit/c992016dbf9436dc84346bf35c7a50d7bba3b0b8))
* let uds run dev upgrade core-base and add a registry mirror option ([#78](https://github.com/jonathanagustin/uds-takserver/issues/78)) ([03b9d05](https://github.com/jonathanagustin/uds-takserver/commit/03b9d059930ade6eacb2db4e375c0ab15b8df1a7))
* write TAK PKCS[#12](https://github.com/jonathanagustin/uds-takserver/issues/12) files with AES-256 and an HMAC-SHA256 MAC ([#74](https://github.com/jonathanagustin/uds-takserver/issues/74)) ([460cde6](https://github.com/jonathanagustin/uds-takserver/commit/460cde632b0fcc951d0203d198a3b5774a26f6ae))

## [0.2.0](https://github.com/jonathanagustin/uds-takserver/compare/v0.1.0...v0.2.0) (2026-10-21)


### Features

* add CloudTAK with Keycloak sign-in as the browser map client ([#13](https://github.com/jonathanagustin/uds-takserver/issues/13)) ([c3b81ee](https://github.com/jonathanagustin/uds-takserver/commit/c3b81ee6b656e699beb7e2487e1034d113813dac))
* build, package, and test for linux/arm64 alongside amd64 ([#16](https://github.com/jonathanagustin/uds-takserver/issues/16)) ([2e7c663](https://github.com/jonathanagustin/uds-takserver/commit/2e7c663c415fbe7f9c8e578fccca5abbd1d00b5c))
* **cloudtak:** default OpenStreetMap basemap through a tile proxy ([#20](https://github.com/jonathanagustin/uds-takserver/issues/20)) ([bf6727e](https://github.com/jonathanagustin/uds-takserver/commit/bf6727e0d7e79b6f8abe095e8a737bb1d58968a7))
* **demo:** add CloudTAK map chapter to the demo video ([#21](https://github.com/jonathanagustin/uds-takserver/issues/21)) ([6d5f589](https://github.com/jonathanagustin/uds-takserver/commit/6d5f589bcbf0724620e0ec74764cfd1d9192f59f))
* render the OIDC client secret at admission ([#4](https://github.com/jonathanagustin/uds-takserver/issues/4)) ([bd61198](https://github.com/jonathanagustin/uds-takserver/commit/bd611987af4d1858a2e6b9a3044c5660700dffb6))
* replace intra-namespace allow-all with per-workload network rules ([#11](https://github.com/jonathanagustin/uds-takserver/issues/11)) ([951ca44](https://github.com/jonathanagustin/uds-takserver/commit/951ca4418b866837775e73741800a37f8fb8d31f))
* serve the standard TAK ports 8446 and 8089 on the passthrough gateway ([#19](https://github.com/jonathanagustin/uds-takserver/issues/19)) ([3d9e950](https://github.com/jonathanagustin/uds-takserver/commit/3d9e950136e798a0bbebacce1a7583cff51f258f))


### Bug Fixes

* give Ignite room, let TAK reach Keycloak over TLS 1.3, and keep each node's CoreConfig ([#1](https://github.com/jonathanagustin/uds-takserver/issues/1)) ([93874f7](https://github.com/jonathanagustin/uds-takserver/commit/93874f73298d6a986ed16c5cf10113304d4bdf62))
* re-encrypt gateway traffic to the TAK web UI ([#10](https://github.com/jonathanagustin/uds-takserver/issues/10)) ([752d016](https://github.com/jonathanagustin/uds-takserver/commit/752d016a172583e283d24aa237ac8beb920e4435))
* resolve DOMAIN hosts to the Istio gateways inside the cluster ([#14](https://github.com/jonathanagustin/uds-takserver/issues/14)) ([6e29e64](https://github.com/jonathanagustin/uds-takserver/commit/6e29e64d5874434a6620921e5f23636f8756e186))


### Documentation

* add contributing guide, PR template, and OpenSSF Best Practices badge ([#63](https://github.com/jonathanagustin/uds-takserver/issues/63)) ([a90843c](https://github.com/jonathanagustin/uds-takserver/commit/a90843ca24f2f0a4b8951033277e50834ca134be))
* clean up README ([#5](https://github.com/jonathanagustin/uds-takserver/issues/5)) ([3443d79](https://github.com/jonathanagustin/uds-takserver/commit/3443d79e55b27b981b8ebc09a6d4d9a0174a9013))
* renumber the standard TAK ports ADR to 0012 ([#23](https://github.com/jonathanagustin/uds-takserver/issues/23)) ([13f1bd2](https://github.com/jonathanagustin/uds-takserver/commit/13f1bd2fdb173b50b53001df56d884d82038beba))
* show the demo video at the top of the README ([#17](https://github.com/jonathanagustin/uds-takserver/issues/17)) ([089f7f1](https://github.com/jonathanagustin/uds-takserver/commit/089f7f1771e44a71241950b56371341734b615fd))
* update README demo video with the CloudTAK map chapter ([#22](https://github.com/jonathanagustin/uds-takserver/issues/22)) ([1b3c3b7](https://github.com/jonathanagustin/uds-takserver/commit/1b3c3b7f35abfd8a27e502e5ffad4113bd89102c))
