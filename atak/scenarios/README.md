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


## Supported content-URI dispatch

To exercise the official exported activity, first expose the **same package**
through an existing Android document/media provider, readable by the device’s
ADB shell and ATAK. Obtain its real `content://` URI from that provider. Creating
and granting the URI is a runtime prerequisite: a pathname or invented URI does
not satisfy it. The harness does not install a provider or change Android
permissions. Then use:

```sh
demo/atak-adb.sh scenario /tmp/synthetic-mission.dpk /tmp/android-dispatch-evidence \
  content://media/external/file/ACTUAL_ID
```

`ACTUAL_ID` is a placeholder; it must be replaced with a real provider row. The
script reads that provider stream with `adb content read` and requires the exact
validated package SHA-256 before sending explicit SEND/EXTRA_STREAM to the
exported `ImportFileActivity`, with the read-grant flag. It waits for Android’s
`am start -W` `Status: ok` response. A successful dispatch receipt says
`android-import-activity-dispatched-unverified`: the Android activity manager
accepted the dispatch, while ATAK’s import result, permission prompts, map and
attachment still require actual UI verification. A mismatching provider stream
fails before dispatch. Commands have a 45-second deadline, provider output is
capped at 1 MiB, and other command output at 8 MiB; raw diagnostics are omitted.

## Verify the actual outbound share at a TLS peer

The maintained official plugin example
`plugin-examples/helloworld/app/src/main/java/com/atakmap/android/helloworld/HelloWorldDropDownReceiver.java`
at the same `9f6893d` revision (blob
`77a097ccc01524f41cc056768230693011acfc35`, lines 1083–1086) converts a map
rectangle into CoT and calls `getExternalDispatcher().dispatchToBroadcast`.
That is an outbound interoperability example. In contrast,
`plugin-examples/cotinjector/app/src/main/java/com/atakmap/android/cotinjector/CotInjector.java`
(blob `5fff585929c9fe67b356230a1bbea57ab0da517f`) uses the **internal**
dispatcher; its local marker injection is not evidence of peer delivery. These
are public official example semantics, not a plugin binary or copied console.
The source remains subject to the official root `LICENSE.md` and per-file
notices; no example implementation is copied into this harness.

Start the observer with existing test-only TAK client credentials in the same
server group as the Android device, then manually share the imported marker from
Android while the observer is connected:

```sh
python3 atak/scenarios/observe-peer.py --mission-package /tmp/synthetic-mission.dpk \
  --host takserver-stream.uds.dev --ca /secure/test-ca.pem \
  --cert /secure/peer.pem --key /secure/peer.key \
  --seconds 60 --output /tmp/android-peer-evidence
```

The observer uses verified mutual TLS with hostname checking and sends no CoT,
replayed fixture or protocol-negotiation request. It expects the existing XML
CoT stream on 8089; a server requiring negotiated binary streaming needs a
separate qualified client. Connect, DNS, handshake and receive share a maximum
120-second deadline on this Linux harness; incoming data is capped at 1 MiB.
It accepts a matching fixture UID only when type, latitude, longitude and
callsign also match. A wrong matching-UID event, closed stream, deadline or
budget excess fails. Receipts contain no certificate/key material, peer stream
or provider URI.

`peer-observed-matching-cot` proves those marker fields arrived on the actual TLS
connection. It does not attribute a retained server event to a particular UI
click. Correlate the manual Android Share with the captured device evidence and
observer window; preserve exact APK/server versions. Reverse-direction sharing,
attachment opening and Android map display remain separate actual-client gates.
The offline socket and ADB tests are explicit protocol mocks, not an emulator or
network qualification. No local APK, active device or peer credentials were
used to qualify this source implementation.


## Hosted e2e extension (source implemented; not runtime qualified)

The existing hosted ATAK e2e step sets `ATAK_INTEROP_SCENARIO=true`, making
`atak/ci/e2e.sh` invoke `atak/ci/interoperability.sh` once after its baseline
device and SSO checks. Other callers, including manual demo recording, retain
their existing baseline unless explicitly opting into this test. It reuses that cluster, installed APK,
existing driver image and gateway port-forward. It adds no cluster, APK build,
image build, recording job or workflow permissions. Image input keys remain
unchanged. The outer timeout is 475 seconds plus a five-second kill grace: an
**eight-minute maximum increment**. Bootstrap has an 80-second aggregate limit;
UI staging/import has 150 seconds; fresh outbound observation has 120 seconds;
reverse sending/UI verification has 100 seconds. The outer limit includes
failure handling and cleanup, so phases cannot extend the total budget.

Bootstrap creates a one-day synthetic peer TakClient in the device's server
group, reads its existing controller-issued CA/client credentials into an owned
0700 temporary directory, and obtains the **public deployed server certificate**
from authenticated Kubernetes Secret `takserver-certs`, key `takserver.pem`.
Its exact DER SHA-256 supplies the explicit leaf pin. The observer's ordinary
CLI still defaults to CA plus hostname verification. Explicit pin mode retains
`CERT_REQUIRED`, verifies the CA chain and then the exact DER leaf before
readiness or application reads. It does not learn a pin from the network and
has no fallback to an unverified connection. Separate `--connect-host` and
`--host` allow the existing `127.0.0.1:28443` gateway forward with streaming SNI.
Credentials never enter the evidence directory or command output. Cleanup
removes them first, sanitizes text evidence before upload, deletes the temporary
TakClient and helper pod only after checking their per-run ownership label.
The helper uses a fresh `atak-scenario-<16-hex-owner>` name and create-only
admission, refusing an existing name. The normal `atak-demo-adb` recording pod
is neither reused nor deleted. `DOMAIN`, `DEVICE_GROUP` and `DRIVER_IMAGE` are
explicitly propagated from e2e through the nested scenario/driver calls. Owned observer/tool process groups are
killed on failure or interruption. Cleanup failure makes the overall run fail
and is recorded separately; it cannot leave a successful final qualification.
Resource cleanup has a 15-second aggregate deadline. Deletion uses an exact UID
precondition and zero grace for these owned test resources, then polls for
actual TakClient and pod absence. `cleanup_verified=true` therefore requires
`owned_resources_absent=true`, not merely an accepted `--wait=false` request.
A replacement or foreign-labelled object is never deleted; pending finalizers,
API errors or incomplete cleanup fail the run. This receipt describes those
resource checks, not certificate revocation-history verification.

The actual acceptance phases are:

1. Build the canonical package from the mission lane's locked fixture sources.
   Check the official Android gitlink is still `9f6893d`; compare the installed
   device APK SHA-256 with `/atak-civ.apk` in the already-selected driver image.
   Stage the package, open the native navigation menu and **All tools & plugins**
   (the icon toolbar has no textual accessibility labels in this source), then
   use **Import → Local SD → Download → selected
   DPK → OK → Copy** UI route. No launcher action, private broadcast or invented
   content URI stands in for import. Find the actual marker in Overlays, open
   its detail pane, inspect both numeric DD fields at `0,0`, pan to it and save
   actual coordinate/map screenshots. Empty/incomplete PNG output fails.
2. Connect the read-only observer **before** editing Android's callsign. It
   publishes readiness and drains pre-share data. Edit the actual marker to add
   an unpredictable eight-hex-digit challenge and open its Share dialog. The
   observer drains to quiet and acknowledges arming. After Android's own clock
   advances at least two seconds beyond the edit, publish its clock cutoff and
   tap the real `contact_list_button_send_to_all` **Broadcast** target. The
   silent observer is never assumed to appear in Contacts. Require the fixture
   UID/type/point, challenged callsign and CoT timestamp at or beyond the cutoff.
   Older retained events cannot satisfy this check. Pre-share bytes and the
   accepted event/cutoff times are recorded; the observer sends no CoT/heartbeat.
3. The separate `atak/ci/reverse-marker.py` explicitly sends exactly one new
   synthetic CoT with the same UID, fresh times, point `0.001,0.002` and a
   `RETURN` callsign suffix. Reopen the actual Android marker pane and verify
   that changed callsign and both numeric coordinates, then pan and capture
   actual map evidence. A successful socket send alone is not return acceptance.

The fresh-time predicate is source-backed at official revision `9f6893d`:
`ContactPresenceDropdown.java` calls `CotEventFactory.createCotEvent(target)`
on Share; `Marker.isSupported` does not expose CotEvent, so the factory's marker
fallback sets time/start to a new `CoordinatedTime` (factory lines 118–121).
`ImportManagerView.importLocalFile` takes the real selected file into
`promptImportAction`; its file-row click toggles the selection checkbox.
`MapTouchController.goTo(select=true)` opens the hierarchy-selected point's
actual details. UI resource IDs and labels come from the same pinned source.
Missing or ambiguous controls, certificate prompts, source/APK mismatch, clock
mismatch, absent peer data and partial phases fail; there is no skipped-scene
success or coordinate guessing.

The final status deliberately describes the observed combination:
`ui-import-broadcast-action-fresh-challenge-and-return-verified`. It requires all
three phases, not just dispatch or baseline e2e. UI Broadcast plus a fresh
Android-only challenge establishes the tested sequence; it is not a universal
claim about attribution of unrelated auto-broadcast traffic. Attachment opening
and other peer/client/platform versions remain outside these acceptance gates.
No hosted scenario execution, new footage or new interoperability success has
yet qualified this source extension.

The workflow excludes inactive scenario documentation but explicitly reincludes
all three runtime scenario scripts. Changes to the consumed mission builder,
fixture lock and three exact fixture files also trigger the existing e2e run.
Runtime/VM/APK/driver/deployment/workflow changes still trigger it; source-only
documentation changes do not. Offline Unit tests cover UI state failures,
retained-event freshness, TLS identity rejection before application reads,
partial controller failures, owned-process cleanup and these path filters.

## Avoiding duplicate post-merge runs

Pull requests and manual runs always perform the complete device qualification.
A main push may reuse a completed same-repository PR run only when its successful
deployment, device, scenario and cleanup evidence binds the exact integrated Git
tree. The source head and the actual checkout merge-tree are recorded separately.
The read-only admission job also checks unchanged producer/publisher semantics
and device/package keys across the push, all four keyed images, and matching
plain release digests for the three published device images and package.

Missing, expired, ambiguous, stale or inaccessible API/artifact/registry evidence
selects the full run. Direct pushes select the full run. A reused run publishes
nothing; stale release tags require the normal main test/publisher path. The
tiny seven-day proof contains source/tree/key identifiers and fixed scenario
status, with no captures, credentials or personal data. This is GitHub API-bound
workflow evidence, not a standalone signed provenance claim.
