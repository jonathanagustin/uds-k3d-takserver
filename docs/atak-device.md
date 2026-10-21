# ATAK test device

`atak/` runs the real ATAK-CIV Android app, built from the public source in the `upstream/atak-civ` submodule (tag 5.5.1.10), in an Android-x86 VM managed by KubeVirt. It behaves like a field device: it enrolls a client certificate on 8446, streams CoT on 8089, and shows up in `/Marti/api/clientEndPoints`. A phone view of its screen is served at `https://atak.<domain>/` behind Keycloak.

It is optional and separate from the TAK package. Nothing in `zarf.yaml` or the default tests deploys it. The dedicated workflow `.github/workflows/atak-e2e.yaml` builds and deploys it on the normal test cluster. See [ADR 13](../adr/0013-atak-test-device-in-kubevirt.md).

## Requirements

- amd64 nodes with `/dev/kvm`. The VM image is Android-x86 and the APK is built for `x86_64` only. There is no arm64 build (see [Supported architectures](../README.md#supported-architectures)).
- About 3 GiB of memory and 2 vCPU for the VM, plus KubeVirt.
- The standard TAK ports 8446 and 8089 on the passthrough gateway (`standardPorts` in `chart/values.yaml`, [ADR 12](../adr/0012-standard-tak-ports-on-the-passthrough-gateway.md)) and the in-cluster DNS rewrite, so the device can reach `takserver-stream.<domain>` the way a phone would.

## Images

| Image | Built from | Contents |
| --- | --- | --- |
| `atak-civ-vm` | `atak/vm/Dockerfile` | KubeVirt containerDisk: Android-x86 9.0-r2 kernel and initrd in `/boot`, the system as an ext4 qcow2 at `/disk/android.qcow2` (about 950 MB) |
| `atak-viewer` | `atak/viewer/Dockerfile` | ws-scrcpy v0.8.1 (MIT) with the shell and file listing compiled out, an adb client, and a phone-bezel page |
| `atak-driver` | `atak/apk/Dockerfile` target `driver` | The ATAK APK, adb, and `atak/driver/drive.sh`. Test tool only, not in the package |

The APK build (`atak/apk/Dockerfile`, driven by `atak/ci/build-apk.sh`) compiles the takthirdparty natives, the Conan dependencies, and cesium-native from source. A cold build takes well over an hour on a GitHub runner; the layers are cached in `ghcr.io/jonathanagustin/uds-k3d-takserver/build-cache`. No key, password, or enrolled certificate is in any image. The APK is signed with the debug keystore that ships in the public atak-civ repository.

Pull requests build the images locally as `:dev` and push nothing. A merge to `main` publishes them under the ATAK tag (`5.5.1.10`).

## Deploy

```bash
uds zarf package create atak --set ATAK_TAG=5.5.1.10 --confirm
uds zarf package deploy zarf-package-atak-device-amd64-*.tar.zst --set DOMAIN=uds.dev --confirm
```

The package (`atak/zarf.yaml`) has two components:

- `kubevirt`: KubeVirt v1.8.4 (operator and CR manifests pinned by checksum) and the UDS policy exemption it needs. Kubernetes 1.36 enforces numeric formats in CRD schemas. v1.6.x and v1.7.x declare the kernel and containerDisk checksums as int32, so a CRC32 above 2^31 makes every VMI status update fail and the VMI stays `Scheduled` while the guest runs. v1.9.1 does not start containerDisk VMs in this setup, so the release is pinned.
- `atak-device`: the VM, Service `atak-device-adb`, the viewer Deployment, and the UDS Package `atak`.

## Enrollment

Enrollment happens at runtime against the TAK Server it is deployed next to. The e2e driver installs the APK over adb, taps through the first-run prompts, and opens ATAK's quick-enroll link `tak://com.atakmap.app/enroll?host=takserver-stream.<domain>&username=...&token=...` with the user and password from a Secret. ATAK then enrolls on `<host>:8446` and adds the stream `<host>:8089:ssl`.

ATAK always enrolls with HTTP Basic (`CertificateEnrollmentClient` passes `passIsToken=false`), and TAK checks Basic credentials against its file authenticator. Only bearer tokens go to Keycloak. A Keycloak password is therefore refused on 8446 (TAK answers 302 to its login page). The e2e job records that answer, then creates a TAK file user `atak-device` in group `atak-test` through `/user-management/api/new-user` with the admin certificate and a password generated at run time, and the device enrolls as that user. The viewer login still uses the Keycloak user. Inside the cluster `takserver.<domain>` resolves to the tenant gateway, so the device uses `takserver-stream.<domain>`.

## Network rules

The UDS Package `atak` sets ambient mesh and:

| Direction | Peer | Port | Why |
| --- | --- | --- | --- |
| Egress | device to `istio-passthrough-gateway` pods `app=passthrough-ingressgateway` | 8446 | certificate enrollment |
| Egress | device to `istio-passthrough-gateway` pods `app=passthrough-ingressgateway` | 8089 | CoT streaming |
| Ingress and egress | viewer and device | 5555 | adb for the screen view |
| Ingress and egress | driver (`app.kubernetes.io/name=atak-driver`) and device | 5555 | test driver |
| Expose | tenant gateway host `atak` to the viewer | 8000 | phone view, behind Authservice |

adb on the device has no authentication (`ro.adb.secure=0`). Only the viewer and the driver can reach it.

The viewer's Keycloak client is `uds-atak-viewer` and is limited to the group `/UDS Core/Admin`.

## Policy exemptions

`atak/deploy/kubevirt-exemption.yaml` is a UDS `Exemption` in `uds-policy-exemptions`:

- `virt-handler` runs privileged on the host (it manages `/dev/kvm`, cgroups, and the launcher's network): `DisallowPrivileged`, `RequireNonRootUser`, `DropAllCapabilities`, `RestrictCapabilities`, `RestrictHostPathWrite`, `RestrictVolumeTypes`, `DisallowHostNamespaces`, `RestrictSELinuxType`.
- `virt-operator`, `virt-api`, `virt-controller`, and `virt-exportproxy`: `RequireNonRootUser`, `DropAllCapabilities`, `RestrictVolumeTypes`.
- `virt-launcher-atak-device-*` in `atak` (the pod that runs QEMU, as UID 107): `RestrictCapabilities` (it adds `NET_BIND_SERVICE` for masquerade networking), `DropAllCapabilities`, `RestrictVolumeTypes`, `RestrictHostPathWrite`, `RestrictIstioTrafficOverrides` (KubeVirt always adds the `traffic.sidecar.istio.io/kubevirtInterfaces` annotation to launcher pods; it is read only by Istio sidecars, and `atak` runs in ambient mode).

## Android-x86 notes

- The initrd silences the kernel log unless `DEBUG` is set. `DEBUG=0` gives a verbose serial console without a debug shell.
- Android-x86 renames `eth0` to `wifi_eth` and adds a virtual Wi-Fi `wlan0`. `VIRT_WIFI=0` keeps `eth0` for the Ethernet service, which takes the KubeVirt masquerade DHCP lease (cluster DNS included). The NIC model is `e1000`.
- The ramdisk starts adbd on TCP 5555 and runs a boot report on the serial console (network, adb, display), keeps the screen on, and disables the crash-looping Android-x86 analytics app.
