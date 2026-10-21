# 13. Run ATAK-CIV in a KubeVirt VM as a test client

Date: 2026-10-21

## Status

Proposed

## Context

The tests check TAK Server with curl, openssl, and a Python CoT client. None of them is a real TAK client, so they cannot catch problems that only show up with ATAK: the enroll-then-stream flow on one host, ATAK's trust and preference handling, or how it reacts to the server's certificates. ATAK-CIV is open source (GPLv3) and builds from public sources only. It needs an Android device.

Options:

- The Android emulator in a container. It needs KVM as well, and its system images are under the Android SDK license, which does not allow redistributing them in our image.
- Redroid (Android in a container sharing the host kernel). It needs binder and ashmem kernel modules on the node, which GitHub runners and most clusters do not have.
- Android-x86 in a VM. Apache-licensed images, a normal kernel boot, and KubeVirt already runs VMs as pods with UDS policies and network rules.

## Decision

- Build the ATAK-CIV APK from the `upstream/atak-civ` submodule at release 5.5.1.10 for `x86_64`, in Docker, with every native dependency compiled from source.
- Package Android-x86 9.0-r2 as a KubeVirt containerDisk (kernel boot from `/boot`, system as a qcow2) and run it with KubeVirt v1.6.2 and masquerade networking, so the VM uses cluster DNS like any pod.
- The device enrolls at runtime with a Keycloak user through ATAK's quick-enroll link, on the standard TAK ports through the passthrough gateway ([ADR 11](0011-standard-tak-ports-on-the-passthrough-gateway.md)). No key, password, or enrolled certificate is in an image.
- A ws-scrcpy viewer shows the screen at `atak.<domain>` behind Authservice and Keycloak.
- Ship it as a separate Zarf package (`atak/zarf.yaml`), amd64 only, deployed only by the `ATAK e2e` workflow. The TAK package and the default tests do not change.

## Consequences

- KVM is required. It is amd64 only; there is no arm64 Android-x86 build, so arm64 clusters cannot run it ([ADR 10](0010-amd64-and-arm64.md)).
- `virt-handler` runs privileged on every node, with the UDS policy exemptions listed in docs/atak-device.md. That is a much larger trust grant than anything else in this repository, and is the main reason the component is opt-in.
- CI cost: a cold APK build is more than an hour and the e2e job deploys UDS Core, TAK, KubeVirt, and a 3 GiB VM on one runner. The build layers live in a GHCR registry cache because the Actions cache is too small.
- Image size: the containerDisk is about 950 MB, and KubeVirt adds its own images.
- Android-x86 9 (2020) is old and unmaintained. ATAK 5.5 still supports Android 9, but this does not show behavior on current Android.
- adb on the device has no authentication. Network rules limit it to the viewer and the driver.
- ATAK enrolls with HTTP Basic. TAK's default authenticator here is the file authenticator, and only bearer tokens go to Keycloak, so a Keycloak password may not be accepted on 8446. The e2e job records what TAK answers.
- A certificate enrolled with a Keycloak token is checked against Keycloak again when it connects on 8089, so the messaging pod needs egress to the issuer (added with this work).
