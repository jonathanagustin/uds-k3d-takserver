# ATAK test device

`atak/` runs the real ATAK-CIV Android app, built from the public source in the `upstream/atak-civ` submodule (tag 5.5.1.10), in an Android-x86 VM managed by KubeVirt. It behaves like a field device: it imports a connection data package with its client certificate, streams CoT on 8089 over mutual TLS, and shows up in `/Marti/api/clientEndPoints`. A phone view of its screen is served at `https://atak.<domain>/` behind Keycloak.

It is optional and separate from the TAK package. Nothing in `zarf.yaml` or the default tests deploys it. The dedicated workflow `.github/workflows/atak-e2e.yaml` builds and deploys it on the normal test cluster. See [ADR 13](../adr/0013-atak-test-device-in-kubevirt.md).

## Requirements

- amd64 nodes with `/dev/kvm`. The VM image is Android-x86 and the APK is built for `x86_64` only. There is no arm64 build (see [Supported architectures](../README.md#supported-architectures)).
- About 3 GiB of memory and 2 vCPU for the VM, plus KubeVirt.
- The standard TAK streaming port 8089 on the passthrough gateway (`standardPorts` in `chart/values.yaml`, [ADR 12](../adr/0012-standard-tak-ports-on-the-passthrough-gateway.md)) and the in-cluster DNS rewrite, so the device can reach `takserver-stream.<domain>` the way a phone would.

## Images

| Image | Built from | Contents |
| --- | --- | --- |
| `atak-civ-vm` | `atak/vm/Dockerfile` | KubeVirt containerDisk: Android-x86 9.0-r2 kernel and initrd in `/boot`, the system as an ext4 qcow2 at `/disk/android.qcow2` (about 950 MB) |
| `atak-viewer` | `atak/viewer/Dockerfile` | ws-scrcpy v0.8.1 (MIT) with the shell and file listing compiled out, an adb client, and a phone-bezel page |
| `atak-driver` | `atak/apk/Dockerfile` target `driver` | The ATAK APK, adb, and `atak/driver/drive.sh`. Test tool only, not in the package |

The APK build (`atak/apk/Dockerfile`, driven by `atak/ci/build-apk.sh`) compiles the takthirdparty natives, the Conan dependencies, and cesium-native from source. A cold build takes well over an hour on a GitHub runner; the layers are cached in `ghcr.io/jonathanagustin/uds-k3d-takserver/build-cache`. No key, certificate, or password is in any image. The APK is signed with the debug keystore that ships in the public atak-civ repository.

Pull requests build the images locally as `:dev` and push nothing. A merge to `main` publishes them under the ATAK tag (`5.5.1.10`).

## Deploy

```bash
uds zarf package create atak --set ATAK_TAG=5.5.1.10 --confirm
uds zarf package deploy zarf-package-atak-device-amd64-*.tar.zst --set DOMAIN=uds.dev --confirm
```

The package (`atak/zarf.yaml`) has two components:

- `kubevirt`: KubeVirt v1.8.4 (operator and CR manifests pinned by checksum) and the UDS policy exemption it needs. Kubernetes 1.36 enforces numeric formats in CRD schemas. v1.6.x and v1.7.x declare the kernel and containerDisk checksums as int32, so a CRC32 above 2^31 makes every VMI status update fail and the VMI stays `Scheduled` while the guest runs. v1.9.1 does not start containerDisk VMs in this setup, so the release is pinned.
- `atak-device`: the VM, Service `atak-device-adb`, the viewer Deployment, and the UDS Package `atak`.

## Device certificate

The device authenticates with a client certificate, the way a provisioned field device does. There is no password enrollment.

At run time `atak/ci/e2e.sh`:

1. Reads the deploy-time TAK CA (`ca.pem` and `ca-do-not-share.key`) from ConfigMap `takserver/cert-migration` ([ADR 2](../adr/0002-generate-certificates-at-deploy-time.md)) and issues a 30-day client certificate with `CN=atak-device` and `extendedKeyUsage = clientAuth`. The CA key stays in a temporary directory on the runner and is deleted after signing.
2. Registers the certificate in TAK with `java -jar UserManager.jar certmod -g Operators <cert.pem>` in the messaging pod. Only the public certificate goes into the pod. This is how TAK 5.7 maps a certificate to a user: `X509Authenticator` matches a client certificate against the file users by fingerprint or by the CN, and takes that user's groups. `certmod` adds the user with the fingerprint and no password, the same way `enable_admin.sh` adds the admin certificate. `Operators` is the group Keycloak users get, so the device and CloudTAK users see each other. A certificate with no file user still connects, but only in the anonymous group.
3. Builds a standard ATAK connection data package (`atak-device.dpk`): `MANIFEST/manifest.xml`, `certs/server.pref` with one stream `takserver-stream.<domain>:8089:ssl` and its `caLocation0`, `caPassword0`, `certificateLocation0`, and `clientPassword0` entries, the client `certs/atak-device.p12`, and the CA in `certs/truststore.p12`. Both PKCS#12 files use SHA-1/3DES, which Android 9 reads, and a password generated for this run. The CA certificate in the truststore carries a friendlyName (`openssl pkcs12 -export -nokeys -caname ...`); without one, Android's PKCS12 keystore lists no entry and ATAK reports "Unable to validate Truststore". The `.pref` also sets `atakControlForcePortrait` so the screen fits the phone view.
4. Stores the package in Secret `atak/atak-device-dpk` and mounts it into the driver pod.

The driver installs the APK over adb, taps through the first-run prompts, pushes the package to `/sdcard/Download/atak-device.dpk`, and restarts ATAK. On start ATAK imports `Download/atak*.dpk` files (`PreferenceControl`), the normal import path for a provisioned device. The `.p12` files go to `atak/cert`, the `.pref` adds the stream with those certificates, and ATAK connects to 8089 over mutual TLS. The e2e job then looks for `atak-device` in `/Marti/api/subscriptions/all` and `/Marti/api/clientEndPoints`.

Inside the cluster `takserver.<domain>` resolves to the tenant gateway, so the device uses `takserver-stream.<domain>`. The viewer login uses the Keycloak user.

### Why not password enrollment

ATAK always enrolls on 8446 with HTTP Basic (`CertificateEnrollmentClient` passes `passIsToken=false`). With `auth default="file"` TAK checks Basic credentials against its file authenticator and sends only bearer tokens to Keycloak, so a Keycloak password gets a 302 to the login page. Enrolling the device would need a TAK file user with a password. A certificate issued from the TAK CA needs no password user and matches how devices are provisioned in the field. The 8446 enrollment test in `tests/` still covers the enrollment endpoint.

### Provisioning device certificates

For a real device, an operator does the same steps by hand:

1. Issue a client certificate from the TAK CA, with the device or user name as the CN. TAK's `makeCert.sh client <name>` does this where the CA is on disk. With this package, sign a CSR with `ca.pem` and `ca-do-not-share.key` from `cert-migration`, as `atak/ci/e2e.sh` does.
2. Register it: `kubectl exec -n takserver deploy/takserver-messaging -c takserver-messaging -- sh -c 'cd / && . ./setenv.sh && java -Xmx128m -jar UserManager.jar certmod -g <group> /tmp/<name>.pem'` after copying the PEM to `/tmp` in the pod. `UserAuthenticationFile.xml` is not on a volume, so run it again after the messaging pod restarts.
3. Package the `.p12`, the truststore, and a `.pref` as above, and hand the package to the device: copy it to the device's `Download` folder as `atak*.dpk`, or open it with ATAK's Import Manager.

Remove a device with `certmod -D <cert.pem>`. The CA has no revocation list here, so also keep certificate lifetimes short.

## Network rules

The UDS Package `atak` sets ambient mesh for the viewer. The VM's launcher pod carries `istio.io/dataplane-mode: none` and stays out of the mesh: ztunnel hands inbound connections to the pod from inside its network namespace, which bypasses KubeVirt's masquerade DNAT, so adb never reached the guest (`adb: device offline`). Its traffic is still limited by these NetworkPolicies, and TAK traffic is mutual TLS from the device to TAK. adb from the viewer and the driver to the device is plain TCP inside the cluster.

Rules:

| Direction | Peer | Port | Why |
| --- | --- | --- | --- |
| Egress | device to `istio-passthrough-gateway` pods `app=passthrough-ingressgateway` | 8089 | CoT streaming over mutual TLS |
| Ingress and egress | viewer and device | 5555 | adb for the screen view |
| Ingress and egress | driver (`app.kubernetes.io/name=atak-driver`) and device | 5555 | test driver |
| Expose | tenant gateway host `atak` to the viewer | 8000 | phone view, behind Authservice |

adb on the device has no authentication (`ro.adb.secure=0`). Only the viewer and the driver can reach it.

The viewer's Keycloak client is `uds-atak-viewer` and is limited to the group `/UDS Core/Admin`.

## Policy exemptions

`atak/deploy/kubevirt-exemption.yaml` is a UDS `Exemption` in `uds-policy-exemptions`:

- `virt-handler` runs privileged on the host (it manages `/dev/kvm`, cgroups, and the launcher's network): `DisallowPrivileged`, `RequireNonRootUser`, `DropAllCapabilities`, `RestrictCapabilities`, `RestrictHostPathWrite`, `RestrictVolumeTypes`, `DisallowHostNamespaces`, `RestrictSELinuxType`.
- `virt-operator`, `virt-api`, `virt-controller`, and `virt-exportproxy`: `RequireNonRootUser`, `DropAllCapabilities`, `RestrictVolumeTypes`.
- `virt-launcher-atak-device-*` in `atak` (the pod that runs QEMU, as UID 107): `RestrictCapabilities` (it adds `NET_BIND_SERVICE` for masquerade networking), `DropAllCapabilities`, `RestrictVolumeTypes`, `RestrictHostPathWrite`, `RestrictIstioTrafficOverrides` (KubeVirt always adds the `traffic.sidecar.istio.io/kubevirtInterfaces` annotation to launcher pods; only Istio sidecars read it, and there is no sidecar here).

## Android-x86 notes

- The initrd silences the kernel log unless `DEBUG` is set. `DEBUG=0` gives a verbose serial console without a debug shell.
- Android-x86 renames `eth0` to `wifi_eth` and adds a virtual Wi-Fi `wlan0`. `VIRT_WIFI=0` keeps `eth0` for the Ethernet service, which takes the KubeVirt masquerade DHCP lease (cluster DNS included). The NIC model is `e1000`.
- The ramdisk starts adbd on TCP 5555 and runs a boot report on the serial console (network, adb, display), keeps the screen on, and disables the crash-looping Android-x86 analytics app.
