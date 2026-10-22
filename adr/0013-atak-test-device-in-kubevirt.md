# 13. Run ATAK-CIV in a KubeVirt VM as a test client

Date: 2026-10-21

## Status

Proposed

## Context

The tests check TAK Server with curl, openssl, and a Python CoT client. None of them is a real TAK client, so they cannot catch problems that only show up with ATAK: connecting with a provisioned client certificate, ATAK's data package, trust and preference handling, or how it reacts to the server's certificates. ATAK-CIV is open source (GPLv3) and builds from public sources only. It needs an Android device.

Options:

- The Android emulator in a container. It needs KVM as well, and its system images are under the Android SDK license, which does not allow redistributing them in our image.
- Redroid (Android in a container sharing the host kernel). It needs binder and ashmem kernel modules on the node, which GitHub runners and most clusters do not have.
- Android-x86 in a VM. Apache-licensed images, a normal kernel boot, and KubeVirt already runs VMs as pods with UDS policies and network rules.

## Decision

- Build the ATAK-CIV APK from the `upstream/atak-civ` submodule at release 5.5.1.10 for `x86_64`, in Docker, with every native dependency compiled from source.
- Package Android-x86 9.0-r2 as a KubeVirt containerDisk (kernel boot from `/boot`, system as a qcow2) and run it with KubeVirt v1.8.4 and masquerade networking, so the VM uses cluster DNS like any pod.
- The device authenticates with a client certificate, not a password. At run time the e2e job issues `CN=atak-device` from the deploy-time TAK CA ([ADR 2](0002-generate-certificates-at-deploy-time.md)), registers it in TAK group `Operators` with `UserManager.jar certmod` (TAK maps a client certificate to a file user by fingerprint or CN), and hands ATAK a standard connection data package (a `.pref` for `takserver-stream.<domain>:8089:ssl`, the client `.p12`, and the truststore `.p12`) over adb. ATAK imports it from `Download/atak*.dpk` and connects on 8089 over mutual TLS through the passthrough gateway ([ADR 12](0012-standard-tak-ports-on-the-passthrough-gateway.md)). The generated material exists only on the runner and in Secret `atak/atak-device-dpk`. No key, certificate, or password is in an image.
- A ws-scrcpy viewer shows the screen at `atak.<domain>` behind Authservice and Keycloak.
- Ship it as a separate Zarf package (`atak/zarf.yaml`), amd64 only, deployed only by the `ATAK e2e` workflow. The TAK package and the default tests do not change.

## Consequences

- ATAK's streaming library sends no SNI. The 8089 listener on the passthrough gateway therefore routes by port alone ([ADR 12](0012-standard-tak-ports-on-the-passthrough-gateway.md)), and `tests/api-smoke.sh` checks a handshake without SNI.
- The VM has no GPS, so the driver stages an ATAK defaults preferences file before first start that gives ATAK a fixed test location (National Mall, Washington, DC) with ATAK's restore-location settings and turns internal GPS off, and the callsign `ATAK-DEVICE (TEST LOCATION)` marks it as a test position wherever it appears. It is never a real fix.
- KVM is required. It is amd64 only; there is no arm64 Android-x86 build, so arm64 clusters cannot run it ([ADR 10](0010-amd64-and-arm64.md)).
- `virt-handler` runs privileged on every node, with the UDS policy exemptions listed in docs/atak-device.md. That is a much larger trust grant than anything else in this repository, and is the main reason the component is opt-in.
- CI cost: a cold APK build is more than an hour and the e2e job deploys UDS Core, TAK, KubeVirt, and a 3 GiB VM on one runner. The build layers live in a GHCR registry cache because the Actions cache is too small.
- Image size: the containerDisk is about 950 MB, and KubeVirt adds its own images.
- Android-x86 9 (2020) is old and unmaintained. ATAK 5.5 still supports Android 9, but this does not show behavior on current Android.
- adb on the device has no authentication. Network rules limit it to the viewer and the driver.
- The VM's launcher pod is outside the ambient mesh (`istio.io/dataplane-mode: none`), because ztunnel's in-pod redirection bypasses KubeVirt's masquerade DNAT and adb never reaches the guest. The pod gets no mesh mTLS or Istio authorization; NetworkPolicies still limit it, and its TAK traffic is TLS end to end.
- No password enrollment. ATAK enrolls on 8446 with HTTP Basic only (`passIsToken=false`), and with the file authenticator TAK sends only bearer tokens to Keycloak, so a Keycloak password gets a 302. Enrolling would need a TAK file user with a password. The device therefore does not exercise 8446; the enrollment tests in `tests/` cover that endpoint.
- Operators provision real device certificates the same way: issue from the TAK CA (`makeCert.sh client`, or sign with the `cert-migration` CA), run `certmod -g <group>` in the messaging pod, and deliver a data package. `UserAuthenticationFile.xml` is not on a volume, so registrations must be repeated after the messaging pod restarts, and there is no revocation list, so lifetimes should be short. Steps are in docs/atak-device.md.
