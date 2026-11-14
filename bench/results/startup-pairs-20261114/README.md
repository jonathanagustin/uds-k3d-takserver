<!-- Copyright 2026 uds-takserver authors -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Native startup qualification pairs — 2026-11-14

One successful cold/warm qualification pair was retained for each native architecture:
[AMD64 run 43551469352](https://github.com/jonathanagustin/uds-takserver/actions/runs/43551469352)
and [ARM64 run 43554526073](https://github.com/jonathanagustin/uds-takserver/actions/runs/43554526073).
Each pair uses its own cluster. The eight rows below are correlated application
incarnations, not eight independent trials. Earlier failed warm qualifications
remain recorded in [issue #48](https://github.com/jonathanagustin/uds-takserver/issues/48).
These successful qualification samples do not establish a performance distribution.

All phase values are seconds. “Pull pairs” is the sum of observed complete
Pulling/Pulled event pairs. A zero does not establish cache presence, absence of
network pulls, or zero actual pull time. Init timestamps have whole-second
resolution; zero OIDC duration does not establish zero work. Container→JVM joins
the container start timestamp to the official JVM epoch. JVM→log uses millisecond
epoch precision; the other elapsed phases are rounded to three decimals.

| Architecture | Boundary | Application | Pull pairs | Wait deps | Trust | OIDC | Container→JVM | JVM→log | Log→Ready |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| amd64 | cold | takserver-api | 0.000 | 36.000 | 41.000 | 0.000 | 1.201 | 53.477 | 7.321 |
| amd64 | cold | takserver-messaging | 0.000 | 37.000 | 41.000 | 0.000 | 1.219 | 44.113 | 5.667 |
| amd64 | warm | takserver-api | 0.000 | 2.000 | 40.000 | 0.000 | 0.638 | 52.409 | 0.953 |
| amd64 | warm | takserver-messaging | 0.000 | 3.000 | 40.000 | 0.000 | 0.647 | 44.514 | 8.839 |
| arm64 | cold | takserver-api | 1.000 | 33.000 | 40.000 | 0.000 | 0.278 | 50.883 | 3.839 |
| arm64 | cold | takserver-messaging | 1.000 | 31.000 | 40.000 | 0.000 | 0.265 | 41.831 | 3.903 |
| arm64 | warm | takserver-api | 0.000 | 3.000 | 40.000 | 0.000 | 0.407 | 50.099 | 3.493 |
| arm64 | warm | takserver-messaging | 0.000 | 3.000 | 41.000 | 0.000 | 0.435 | 41.598 | 0.967 |

| Architecture | Cold Pod span (s) | Warm Pod span (s) |
| --- | --- | --- |
| amd64 | 140.000 | 100.000 |
| arm64 | 131.000 | 101.000 |

Pod span runs from the earliest application Pod creation to the latest application
Ready timestamp in that episode. It is not deployment-command wall time. Image,
init, JVM and application timings can overlap across containers and applications;
do not sum these columns into a total.

Trust initialization occupies 40–41 seconds in all eight observations. The
reviewed import-trust script allows up to 30 seconds for an optional CA bundle,
which is a candidate contributor for a follow-up experiment. These records do not
attribute that interval to a cause or justify changing trust policy. No tuning,
CDS, probe benefit, class-loading duration, or observer-overhead claim is made.
The different runners and single pair per architecture do not support an ISA
ranking. Class counts are later scrape observations, not startup durations.

## Provenance and replay

`sources.json` retains source commits, workflow/run/attempt identities, authenticated
artifact metadata and ZIP digests, individual file hashes, and source snapshot
hashes. The original six JSON files per architecture are unchanged under
`records/`. Source snapshots are retained under `source/`; the three collector
source files are identical across both commits. The commits differ in other
harness and repository changes, so these are not identical-host comparisons.
The original artifact ZIPs were downloaded and their SHA-256 digests checked
against GitHub artifact metadata before extraction. An offline replay checks the
retained files against the manifest; it does not independently authenticate GitHub.

From the repository root, run:

```sh
python3 -B bench/results/startup-pairs-20261114/check.py
```

The standard-library checker verifies original hashes, source and pair bindings,
fresh Pod/JVM identities, native architecture, and independent calculations from
raw timestamps. `--table` prints the readout. Frozen collector source is evidence
and is not executed by this checker. The original pair validator also accepted
both downloaded pairs before this readout was written.
