# Connect the ATAK test device

Deploy the optional Android test device and provision it against the existing
TAK Server for Team Awareness Kit (TAK) clients with the driver. Check its connection and test location.

## What you'll accomplish

Run Android Tactical Assault Kit for Civilian Use (ATAK-CIV) in the KubeVirt Android virtual machine (VM), provision its client certificate through
a `TakClient`, and see its callsign in TAK and CloudTAK.

## Prerequisites

- A working TAK deployment with the standard passthrough port 8089 and the
  in-cluster Domain Name System (DNS) rewrite. See [Standard TAK ports](../networking.md#standard-tak-ports).
- An amd64 node with `/dev/kvm`. The VM guest is 2Gi with 2 vCPU, plus
  capacity for KubeVirt's launcher overhead. 2Gi is the configured guest, not
  a measured minimum. Android-x86 and this Android application package (APK) have no arm64 build.
- The Unified Defense Stack (UDS) command-line interface (CLI), Docker, k3d, and a checkout of this repository for the test driver.
- Published images matching the `ATAK_TAG` you select, including `atak-driver`
  for the automated provisioning path.

## Before you begin

The device is a test fixture. It has a fixed mock location, uses a debug-signed
APK, and exposes unauthenticated adb only to its viewer and driver through
network policy. Do not expose adb outside the cluster. The phone viewer is
behind Keycloak and requires `/UDS Core/Admin`.

The package boots the VM and viewer. The driver installs the APK and imports
the certificate data package. The automated driver below targets the
repository's k3d test cluster. For a real phone, follow
[Provisioning device certificates](../atak-device.md#provisioning-device-certificates).

## Steps

1. Select the last tested device package and pull its matching driver image
   into local Docker:

   ```bash title="Prepare the device package and driver"
   export ATAK_TAG=5.5.1.10
   export ATAK_PACKAGE=oci://ghcr.io/jonathanagustin/uds-takserver/packages/atak-device:5.5.1.10
   docker pull "ghcr.io/jonathanagustin/uds-takserver/atak-driver:${ATAK_TAG}"
   ```

2. On the k3d test cluster, run the ATAK e2e provisioning and connection check:

   ```bash title="Provision and check the test device"
   DOMAIN=uds.dev bash atak/ci/e2e.sh
   ```

   The script deploys `ATAK_PACKAGE`, imports the matching driver image, creates `TakClient`
   `takclients/atak-device` in group `Operators`, waits for its Secret, copies
   `package.zip` into the driver's data-package Secret, and runs the driver.
   The driver installs the APK, imports the package from Android's Download
   folder, and restarts ATAK. Allow time for Android boot and first-run prompts.
3. Open `https://atak.<domain>/`, sign in as a UDS Core admin, and inspect the
   phone view. Open `https://map.<domain>/` as a CloudTAK user in `Operators` to
   inspect the device's marker.

## Verification

```bash title="Inspect device provisioning"
uds zarf tools kubectl get takclient atak-device -n takclients
uds zarf tools kubectl get vmi -n atak
uds zarf tools kubectl get pods -n atak
```

The `TakClient` must be Ready and the VM must run. The e2e script also checks
TAK's `/Marti/api/clientEndPoints` and the device's latest Cursor on Target (CoT) coordinates.
Expect callsign `ATAK-DEVICE (TEST LOCATION)` near 38.8895, -77.0353 unless you
overrode the test settings. ATAK's red `NO GPS` label is expected: this is a
mock self position, not a live Global Positioning System (GPS) fix.

## Troubleshooting

### The VM does not start

**Problem:** KubeVirt cannot run the device.

**Symptom:** The VMI is not Running, or the launcher reports a missing
`container-disk` binary.

**Solution:** Confirm amd64 and `/dev/kvm`, then describe the VMI and launcher
pod. Use the package's KubeVirt configuration, which disables `ImageVolume`
for container runtimes without Container Runtime Interface (CRI) image-volume support. See
[Deploy](../atak-device.md#deploy) for the version-specific explanation.

### The device connects but sees no group traffic

**Problem:** The certificate has no matching TAK file user or group.

**Symptom:** ATAK connects but does not exchange events with CloudTAK users.

**Solution:** Inspect the `TakClient` Ready condition and watcher logs. Its
certificate must be provisioned by the operator and its TAK file user must
belong to `Operators`; copying a certificate signed by a certificate authority (CA) alone does not establish
that group membership.

## Related documentation

- [ATAK device reference](../atak-device.md)
- [KubeVirt test device decision](../../adr/0014-atak-test-device-in-kubevirt.md)
- [TakClient operator decision](../../adr/0022-takclient-operator.md)
