# Compiler dependency assessment

The default `patched` profile updates six locked public JARs: the five artifacts
with known advisories plus the matching Bouncy Castle utility module. The
explicit `--profile baseline` option preserves the original compilation
comparison and contains known vulnerable versions. Neither profile is a runnable
TAKX package or a complete runtime dependency closure.

[advisories.json](advisories.json) records the query date, exact 23 direct Maven
coordinates for each profile, advisory IDs and input-lock hash. Regenerate it
with `python3 takx/kernel-java/audit-dependencies.py`; this explicitly contacts
OSV and does not install or update dependencies. The current query returned 14
advisories across five baseline artifacts and none for the 23 patched inputs.
An empty query result is not a security certification; it excludes native GIS,
JDK, transitive dependencies, reachability and unpublished findings.

| Artifact | Baseline | Patched | Baseline findings |
| --- | --- | --- | --- |
| `com.squareup.okio:okio-jvm` | 3.2.0 | 3.4.0 | [CVE-2023-3635](https://osv.dev/vulnerability/GHSA-w33c-445m-f8w7): gzip resource exhaustion |
| `com.google.guava:guava` | 30.0-jre | 33.7.2-jre | [CVE-2020-8908](https://osv.dev/vulnerability/GHSA-5mg8-w23w-74h3), [CVE-2023-2976](https://osv.dev/vulnerability/GHSA-7g45-4rm6-3mm3): temporary-file disclosure; [CVE-2026-102554](https://osv.dev/vulnerability/GHSA-xxph-c9ww-hj94): deserialization memory exhaustion |
| `org.json:json` | 20220924 | 20260719 | [CVE-2022-45688](https://osv.dev/vulnerability/GHSA-3vqj-43w4-2q58), [CVE-2023-5072](https://osv.dev/vulnerability/GHSA-4jq9-2xhw-jpx7), [CVE-2026-59171](https://osv.dev/vulnerability/GHSA-ghc9-756g-vrcv): parsing/resource-exhaustion denial of service |
| `org.bouncycastle:bcprov-jdk18on` | 1.78.1 | 1.85 | [CVE-2025-14813](https://osv.dev/vulnerability/GHSA-574f-3g2m-x479): 28147-89 cipher keystream reuse; [CVE-2026-8763](https://osv.dev/vulnerability/GHSA-9pwp-9qqc-pr26): name constraints; [CVE-2026-0636](https://osv.dev/vulnerability/GHSA-c3fc-8qff-9hwx): LDAP injection; [CVE-2026-5598](https://osv.dev/vulnerability/GHSA-p93r-85wp-75v3): timing channel; [CVE-2026-13506](https://osv.dev/vulnerability/GHSA-qp49-qgx5-5m26): ASN.1 nesting guard |
| `org.bouncycastle:bcpkix-jdk18on` | 1.78.1 | 1.85 | [CVE-2025-8916](https://osv.dev/vulnerability/GHSA-4cx2-fc23-5wg6): excessive allocation; [CVE-2026-5588](https://osv.dev/vulnerability/GHSA-wg6q-6289-32hp): risky cryptographic algorithm |
| `org.bouncycastle:bcutil-jdk18on` | 1.78.1 | 1.85 | No finding returned; upgraded to keep the three BC modules aligned |

These versions were available from Maven Central and outside the returned OSV
affected ranges when assessed. Later fixed versions matter: Guava 32 and JSON
20231013 address older findings but do not cover the newer findings above.
The exact URLs, sizes and SHA256 hashes are locked. Baseline entries are retained
unchanged; patched entries are separate replacements, never silently relabeled
as matching the original 23 JARs.

Before any runtime adoption, resolve and audit the entire dependency closure
(including Okio/Kotlin and Guava companion modules), run real HTTPS and malformed
gzip tests, JSON limit/parser compatibility tests, Guava serialization and
temporary-file tests, and certificate/path-validation/cryptographic tests with
the aligned BC modules. The complete Java compile and unchanged Kernel VSI tests
validate source linkage and the exercised filesystem behavior only. They do not
exercise these security-sensitive dependency contracts or native GIS/JNI.

## Shared-scope additions

The opt-in `engine-shared` scope adds ten locked JARs. At the pinned ATAK source,
[`takkernel/shared/build.gradle`](https://github.com/TAK-Product-Center/atak-civ/blob/9f6893dd657feacc35ec5de03dad721c2e44170e/takkernel/shared/build.gradle)
declares Jackson databind 2.13.1, `mil-sym-renderer` 0.1.41 and `mil-sym-java`
2.1.5. Jackson adds its matching core/annotations. The official
[renderer POM](https://repo.maven.apache.org/maven2/io/github/missioncommand/mil-sym-renderer/0.1.41/mil-sym-renderer-0.1.41.pom)
and [parent dependency management](https://repo.maven.apache.org/maven2/io/github/missioncommand/mil-sym-java/0.1.41/mil-sym-java-0.1.41.pom)
resolve JavaRenderer, RendererPluginInterface, JavaRendererServer, JavaLineArray
and JavaRendererUtils, all 0.1.41. These five transitives supply real classes;
no replacement symbol APIs are supplied.

The default patched shared profile upgrades Jackson databind/core to 2.23.0 and
annotations to 2.23 (the version declared by its 2.23 BOM). The baseline retains
all three at 2.13.1. [shared-advisories.json](shared-advisories.json) records 31
advisory entries for the 33 baseline coordinates, including 14 for old Jackson
databind and three for old Jackson core; the other 14 belong to the existing
engine baseline. It returns no advisories for the 33 patched coordinates.
Regenerate with `python3 takx/kernel-java/audit-dependencies.py --scope engine-shared`.
All archive URLs, sizes and SHA256 hashes are in the shared lock section.

This validates compilation with those exact inputs, not a complete runtime
closure or military-symbol rendering. In particular, published symbol-library
runtime dependencies, renderer resources, native linkage, untrusted input
handling and full client interoperability still require separate validation.
