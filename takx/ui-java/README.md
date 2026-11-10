# UI Java source candidates

Rebuild six missing TAKX dependency candidates from public Java source. This
recipe supports compiler investigation; it does not build or run TAKX, verify
UI behavior, or establish dependency security or distribution compatibility.
Outputs have project names and implementation version `0.1.0`. They are never
published or installed under unavailable upstream Maven coordinates.

## Source profiles

The default `original` profile builds five artifacts from four original projects:

| Project | Exact source pin | Identity |
| --- | --- | --- |
| DockingFrames core and common | `Benoker/DockingFrames@3db975668140de78d760ac887b4961b3bfd726bb` | Tag, parent POM and version file identify `1.1.3p1`; LGPL 2.1-or-later source notices |
| ColorChooser | `timboudreau/colorchooser@18a2d1573cc9a012d15313ac302c63ad7e44b4cb` | Original-author **1.5 candidate**, not TAKX's requested `net.java.dev:colorchooser:1.1`; Apache 2.0 |
| Swing toast notifications | `DJ-Raven/swing-toast-notifications@191114d232d844fa6ad23a25c9c35820b6f72b3a` | Original POM identifies `1.0.3`; Apache 2.0 |
| SVG Salamander | `blackears/svgSalamander@1ae35c294f70d0db205bb3069459bcd00535d089` | Exact tag `v1.1.1`, whose original POM still says `1.0.39`; original BSD notices and BSD/LGPL texts retained |

**Wizard is separate and experimental.** The explicit `wizard-reference` profile
builds the preserved implementation at
`Lonzak/Wizard-API@746cce7bcd616790328393bac770a7db3708836c`. Its README claims a
copy of Wizard 1.1, but authentic `org.netbeans:wizard:rev-28122010` provenance
has not been established. This source-reference candidate is not an
authenticated NetBeans release. Its CDDL headers are retained; the separately
locked full CDDL 1.0 text comes from SPDX license data. No copied JAR is used.

The original-author ColorChooser 1.5 and experimental Wizard reference must keep
these identities in later probes. Neither is relabeled as TAKX's requested
version. Source compilation does not establish API compatibility with either
complete TAKX client.

## Prepare local inputs

Use Linux, Python 3.11 or later and JDK 17. Supply the exact archives and public
JARs listed in [inputs.lock.json](inputs.lock.json). The builder downloads nothing
and accepts neither SDK payloads nor unknown binary mirrors. Existing source
archives and resolved public JARs can be reused. To list the locked names and
download URLs:

```sh
python3 - <<'PY'
import json
lock = json.load(open('takx/ui-java/inputs.lock.json'))
for source in lock['archives'].values():
    print(source['file'], source['url'])
for name, jar in lock['public_jars'].items():
    print(name, jar['url'])
print(lock['license_text']['file'], lock['license_text']['url'])
PY
```

Put `docking.tar.gz`, `color.tar.gz`, `toast103.tar.gz` and `svg.tar.gz` in one
source directory. The default profile also needs `ant-1.8.1.jar`,
`javacc-5.0.jar`, `flatlaf-3.4.1.jar` and `flatlaf-extras-3.4.1.jar` in a
classpath directory. JavaCC generates the real SVG animation parser from its
original grammar; Ant is needed to compile SVG's original Ant task. No Ant task,
Swing application or native library is executed.

```sh
python3 takx/ui-java/build.py \
  --sources-dir /tmp/ui-sources --classpath-dir /tmp/ui-jars \
  --java-home "$JAVA_HOME" --output /tmp/uds-ui-original
```

For the experimental reference alone, supply `wizard-copy.tar.gz` and the exact
`CDDL-1.0.txt` in the source directory. It needs no dependency JARs; the supplied
classpath directory may be empty:

```sh
python3 takx/ui-java/build.py --profile wizard-reference \
  --sources-dir /tmp/ui-sources --classpath-dir /tmp/ui-jars \
  --java-home "$JAVA_HOME" --output /tmp/uds-ui-wizard-reference
```

Output must be a new directory outside the repository, with an existing parent.
The optional `--failure-report /tmp/new-report.json` preserves bounded failure
diagnostics separately. Each tool has a 180-second default deadline, configurable
with `--timeout-seconds` from 1 to 600. A failure or timeout kills its process
group and removes all staged classes and JARs; no partial output is accepted.
An existing output or report is never replaced.

## What the recipe verifies

Whole archive/JAR size and SHA-256 checks run before source parsing or tools.
Source extraction rejects traversal, duplicate members and selected non-regular
files. Complete Java and resource inventories are locked. All selected module
sources compile with `--release 8`, annotation processing and implicit source
compilation disabled. Generated parser bytes are also locked. This is a project
JDK 17 build, not a claim that the historical Java 6 Maven distribution built
unchanged. Whole inputs are checked again before accepting output.

Each artifact has a binary JAR, a complete consumed-source JAR, original
resources, upstream identity metadata and license/source notices. `receipt.json`
records source, resource, generated-code, class, dependency, recipe, lock and
toolchain hashes. Exact tool commands and logs are retained under `logs/`.
Source terms remain their upstream terms; the recipe does not relicense them.

ZIP entry order, timestamps, permissions, compression and manifest bytes are
fixed. On the same JDK and locked inputs, clean builds produce identical binary
and source JARs. Receipts retain the identities of the actual build inputs;
deterministic packaging is not runtime acceptance.

## Verify

Normal Unit CI runs nine cheap offline guards covering source/dependency
integrity, explicit candidate profiles, unsafe archive members, complete
inventories, deterministic packaging and failed/timeout cleanup. It downloads
nothing and compiles no third-party Java. Two complete-source tests are opt-in
and skipped without all three environment variables:

```sh
UI_JAVA_SOURCES_DIR=/tmp/ui-sources \
UI_JAVA_CLASSPATH_DIR=/tmp/ui-jars \
JAVA_HOME=/path/to/jdk-17 \
  python3 -B -m unittest discover -s takx/ui-java -p test_build.py -v
```

Those tests build both profiles, check every resource/license receipt and source
count, and compare second clean builds' binary and source JARs. The local source
checkpoint compiled 1,669 files into 2,956 classes with zero errors, including
21 generated parser sources. No complete-client, native, UI or interoperability
acceptance follows from that result.
