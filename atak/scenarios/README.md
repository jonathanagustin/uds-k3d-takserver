# Synthetic Android interoperability scenario

This opt-in scenario prepares a small mission package for the existing ATAK-CIV
KubeVirt/ADB device. It stages the package for manual import and captures the device screen and
UI XML. Staging does not establish that a marker, attachment,
server connection, or peer exchange worked.

The source baseline is the maintained official
[`TAK-Product-Center/atak-civ`](https://github.com/TAK-Product-Center/atak-civ/tree/9f6893dd657feacc35ec5de03dad721c2e44170e),
revision `9f6893dd657feacc35ec5de03dad721c2e44170e` (5.5.1.10), also pinned by
this repository's `upstream/atak-civ` gitlink. This lane uses the newer official
path, not the archived DoD example or a proprietary console. Manifest semantics
come from `atak/ATAK/app/src/main/java/com/atakmap/android/missionpackage/file/`
`MissionPackageManifest.java`, `MissionPackageConfiguration.java`, and
`MissionPackageContent.java`: version 2, Configuration, Contents, zipEntry and
isCoT. Those sources carry GPLv3/per-file notices; no implementation is copied
here. Our script is GPL-3.0-only and the fixture is original synthetic data.

Build the mission lane's deterministic fixture once its change is integrated:

```sh
python3 takx/mission-package/build_fixture.py --output /tmp/synthetic-mission.dpk
python3 atak/scenarios/android-interoperability.py \
  --mission-package /tmp/synthetic-mission.dpk --output /tmp/android-offline-evidence
```

The agreed fixture has `MANIFEST/manifest.xml` version 2, package UID
`00000000-0000-4000-8000-000000000410`, CoT entry
`cot/synthetic-android-mission-point.cot`, marker UID
`synthetic-android-mission-point`, callsign `SYNTHETIC-MISSION TEST`, point `0,0`,
synthetic remarks, and `files/README.txt`. It requests import and retention
(`onReceiveImport=true`, `onReceiveDelete=false`). The protocol codec fixtures
remain separate: this marker represents a synthetic exercise location.

Offline validation rejects non-synthetic marker UIDs, unlabelled markers, invalid
coordinates, unsafe cross-platform paths, encrypted or special ZIP entries,
unsupported compression, duplicate members, missing or unlisted payloads, and
packages over 1 MiB expanded or compressed. Every scenario payload must be
listed once in the manifest; the CoT marker declares `isCoT=true` and the README
attachment must exist. This narrower scenario policy does not replace the mission
lane’s actual Java package-reader admission guard. Its receipt binds the exact package SHA-256 and says `not-run`.
This checks scenario input, not complete ATAK package compatibility.

## Actual device gate

Supply the already-built, installed ATAK APK and already-running, provisioned
KVM/KubeVirt device from the existing manual `atak/ci/e2e.sh` path. The driver
image must already be present. No tool here acquires an APK, builds an image,
provisions certificates, dispatches CI, or starts recording.

```sh
demo/atak-adb.sh start
demo/atak-adb.sh scenario /tmp/synthetic-mission.dpk /tmp/android-device-evidence
```

For an existing direct ADB connection, use the Python command with
`--device SERIAL` instead. Both output directories must be fresh. Commands are
bounded to 45 seconds each. The script stages the file in Download; it does not restart ATAK or infer that
startup imports an arbitrary package. A successful command means
`staged-for-manual-import`, never scenario pass. Open ATAK’s Import UI, select
`Download/atak-synthetic-scenario.dpk`, and accept its import prompts.
Failure preserves a typed failure receipt without raw subprocess diagnostics.
Screenshots/UI XML are local test evidence and should be reviewed before sharing.

The existing driver stages its connection package, restarts ATAK, and taps known
import prompts. That is not an import acknowledgement for this mission fixture.
At the pinned official revision, `atak/ATAK/app/src/main/AndroidManifest.xml`
(blob `e2f96c76554adf077efd0ffdc3d19d440ebd7a75`) exports
`com.atakmap.android.maps.ImportFileActivity` with SEND and content-VIEW filters.
Its `ImportFileActivity.java`
(blob `f1c1163ba7ae497e0582c4b7cfafc127ce3d3dac`) requires a parcelable
`Intent.EXTRA_STREAM`, queries its content resolver for DISPLAY_NAME, copies the
stream, then forwards an internal import intent. A file push or launcher action
satisfies none of that contract. This harness deliberately does not fabricate a
content-provider URI or label Android activity dispatch as app acknowledgement.

Complete these assertions on the actual device before calling the scenario
qualified: accept the package import, locate `SYNTHETIC-MISSION TEST` at `0,0`,
open its synthetic remarks, and open `files/README.txt` through the imported
mission package. Then share the marker through the connected TAK server to a
second actual client; verify the receiving UID and coordinates and share an
updated point back. Record both clients, exact APK/source versions, package
hash, server connection and peer evidence. A screenshot of a map alone does not
prove network exchange. The existing `tests/demo/atak-sync.demo.ts` provides the
CloudTAK-to-device walkthrough; its optional scenes do not qualify these stricter
assertions. No actual APK/emulator execution or footage is claimed by this
source change. Heavy recording remains manual and workflow permissions and
minutes are unchanged.

Run the small offline guards with:

```sh
python3 -m unittest discover -s tests -p test_android_scenario.py
```
