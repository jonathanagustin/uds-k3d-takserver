# Synthetic Android interoperability scenario

This opt-in scenario prepares a small mission package for the existing ATAK-CIV
KubeVirt/ADB device. It requests a real import and captures the device screen and
UI XML. It does not turn an import request into a claim that a marker, attachment,
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
coordinates, traversal, duplicate members, and packages over 1 MiB expanded or
compressed. Its receipt binds the exact package SHA-256 and says `not-run`.
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
bounded to 45 seconds each. The script uses the same Download-folder import and
ATAK restart as `atak/driver/drive.sh`; import prompts may still need acceptance.
A successful command means `import-requested-unverified`, never scenario pass.
Failure preserves a typed failure receipt without raw subprocess diagnostics.
Screenshots/UI XML are local test evidence and should be reviewed before sharing.

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
