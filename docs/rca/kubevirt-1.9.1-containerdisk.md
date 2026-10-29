<!--
Copyright 2026 uds-k3d-takserver authors
SPDX-License-Identifier: GPL-3.0-only
-->

# RCA: KubeVirt v1.9.1 containerDisk startup

## Summary

KubeVirt v1.9.1 starts a containerDisk VM on this repo's deploy path. The failure recorded in `atak/zarf.yaml` at commit `76bb3b1` ("the container-disk binary is missing from the launcher") does not reproduce with the Zarf agent this cluster actually runs.

On Zarf init v0.87.0, the mutating agent rewrites `volumes[].image.reference` as well as container images. The v1.9.1 launcher init container runs `/container-disk-binary/usr/bin/container-disk --no-op` with the virt-launcher image mounted at `/container-disk-binary`. That container exited 0, and the VMI reached `Running` and `Ready`, both with Zarf alone and with UDS Core 1.15.2 (Pepr, the Exemption, and the device network policies).

v1.9.1 does add two images the old package list did not have: `quay.io/kubevirt/virt-template-apiserver:v0.2.3` and `quay.io/kubevirt/virt-template-controller:v0.2.3`. Without them the Zarf agent points those pods at the internal registry, the pull returns not found, and the KubeVirt CR never becomes `Available`. That blocks every VM. It is not the missing-binary error. Those images are now in `atak/zarf.yaml`.

`ImageVolume` does not need to be disabled. The default configuration passed, so the disable retry never ran.

## Impact

The ATAK test device is the only consumer. A normal TAK install does not deploy KubeVirt. While the package stayed on v1.8.4, containerDisk VMs worked. Moving to v1.9.1 without the virt-template images makes `uds zarf package deploy` wait until its 900 second KubeVirt `Available` check times out, and no VM is created. With those images listed, a containerDisk VMI starts.

## Timeline

- Commit `76bb3b1` pinned KubeVirt at v1.8.4. The comment says v1.6.x and v1.7.x fail on k3s v1.37.1 because of the int32 checksum bug (kubevirt #17858), and that v1.9.1 fails to start containerDisk VMs because the container-disk binary is missing from the launcher.
- Stock k3s v1.37.1 and kind v1.37.0, with no Zarf and no Pepr, both start a cirros containerDisk VMI on v1.9.1 with `ImageVolume` left on. Run [40838044037](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/40838044037).
- The deploy-path runs are on branch `cursor/kubevirt-191-containerdisk-repro-3d28`. The package on that branch is v1.9.1.
- Run [40840789467](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/40840789467) installed KubeVirt through Zarf. The CR stayed `Available=False` for 15 minutes because the virt-template images were missing.
- Run [40843977960](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/40843977960) created the VMI in a namespace that kubectl had created. Every rewritten pull failed for lack of the Zarf pull secret.
- Run [40845544294](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/40845544294) seeded that secret the way a Zarf manifest namespace does. Both stacks passed.

## Reproduction

Workflow `.github/workflows/kubevirt-191-zarf-rca.yaml`, on push to this branch. Two jobs:

| Job | What it deploys |
| --- | --- |
| `zarf-init-191` | k3d with `rancher/k3s:v1.37.1-k3s1` and `/dev/kvm`, then `oci://ghcr.io/zarf-dev/packages/init:v0.87.0` |
| `uds-core-191` | The repo's checkpoint `oci://ghcr.io/defenseunicorns/dev/uds/checkpoints/k3d-core-slim-dev:1.15.2`, which creates the k3d cluster, runs that same init package, and installs Pepr |

Both then build the `kubevirt` component of `atak/zarf.yaml` with UDS CLI v0.40.0 (Zarf CLI v0.88.0) and deploy it. A second package mirrors `quay.io/kubevirt/cirros-container-disk-demo` the way the package mirrors `atak-civ-vm`. The VMI is named `atak-device` in namespace `atak`, so the launcher matches the Exemption. The UDS job also applies the device `Package` network allow rule. The guest is cirros at 128Mi, not the Android image.

The Android disk was not booted. The containerDisk mechanism under test is the same: an image volume for the disk and an image volume for virt-launcher.

## Evidence

Successful run: [40845544294](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/40845544294).

| Job | Result | Link |
| --- | --- | --- |
| zarf-init-191 | Pass. `phase=Running`, `Ready=True` | [job 123352005978](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/40845544294/job/123352005978) |
| uds-core-191 | Pass. `phase=Running`, `Ready=True` | [job 123352005507](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/40845544294/job/123352005507) |

Both nodes are `v1.37.1+k3s1` with `containerd://2.3.4-k3s1` and `/dev/kvm`. The in-cluster agent image pulled by the init package is `127.0.0.1:31999/zarf-dev/zarf/agent:v0.87.0`.

Admitted launcher pod on the UDS job (`virt-launcher-atak-device-jzgrj`). Zarf records the pre-mutation reference in annotations and replaces the pod spec:

| Field | Before (annotation) | After (pod spec) |
| --- | --- | --- |
| `volumes[containerdisk].image.reference` | `quay.io/kubevirt/cirros-container-disk-demo` | `127.0.0.1:31999/kubevirt/cirros-container-disk-demo:latest-zarf-3314652848` |
| `volumes[launcher-volume].image.reference` | `quay.io/kubevirt/virt-launcher:v1.9.1` | `127.0.0.1:31999/kubevirt/virt-launcher:v1.9.1-zarf-4024454106` |
| init `volumecontainerdisk` image | `quay.io/kubevirt/cirros-container-disk-demo` | same cirros registry tag |
| init `volumecontainerdisk` command | | `/container-disk-binary/usr/bin/container-disk --no-op`, mount `launcher-volume` at `/container-disk-binary` |

That init container terminated `Completed`, exit code 0, restart count 0. The zarf-only job has the same rewrite and the same `Completed` init container.

Pepr, on the UDS job, validated `CREATE` of `virt-launcher-atak-device-jzgrj` and returned `allowed: true`. The log says the pod is exempt from `RestrictVolumeTypes`, `DropAllCapabilities`, `RestrictCapabilities`, `RestrictHostPathWrite`, and `RestrictIstioTrafficOverrides`. The operator created `allow-atak-egress-device-to-tak-streaming` and `deny-atak-default`. Neither stopped the VMI.

Exact errors from the runs that did fail, before the package and the namespace secret were corrected:

Virt-template images absent, both jobs, run [40840789467](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/40840789467). The KubeVirt CR stayed `Available=False`, reason `DeploymentInProgress`, message `Deploying version v1.9.1 with registry quay.io/kubevirt`. The pod event was:

```text
Failed to pull image "127.0.0.1:31999/kubevirt/virt-template-apiserver:v0.2.3-zarf-2659374386":
failed to resolve reference "...": not found
```

The controller tag was `v0.2.3-zarf-2952474416`, also not found. `virt-operator`, `virt-api`, `virt-controller`, and `virt-handler` were already `Running`.

Namespace created outside Zarf, both jobs, run [40843977960](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/40843977960). The VMI condition was `Synchronized=False`, reason `ImagePullBackOff`:

```text
Back-off pulling image "127.0.0.1:31999/kubevirt/virt-launcher:v1.9.1-zarf-4024454106":
ErrImagePull: ... authorization failed: no basic auth credentials
```

The pod spec already had `imagePullSecrets: [{name: private-registry}]` and the image-volume rewrite above. The secret was not in namespace `atak`. Disabling `ImageVolume` hit the same pull error on the virt-launcher init containers, so that retry did not reach the binary.

## Root cause

High confidence. The missing-binary failure is the v1.9 `ImageVolume` path when the virt-launcher image volume does not mount. The init container's command is `/container-disk-binary/usr/bin/container-disk`, and that file exists only inside the mounted virt-launcher image. On this deploy path the Zarf v0.87.0 agent rewrites that volume reference to the internal registry, the image is in the package, the pull secret is present, and the init container exits 0. Pepr admits the pod because the Exemption matches `virt-launcher-atak-device-*`.

The comment in `76bb3b1` describes a failure this stack does not produce. Zarf gained image-volume mutation in v0.70.1. The slim checkpoint's init package is v0.87.0. An older agent that rewrote container images and left `volumes[].image.reference` pointing at `quay.io` would leave the binary mount empty whenever the node could not pull quay.io, which is the air-gap case Zarf is for. That matches hypothesis (a) for those older agents. It is not what v0.87.0 does, and it is not what these runs did.

## Contributing factors

- **Virt-template images (hypothesis c), confirmed.** v1.9.1 deploys `virt-template-apiserver` and `virt-template-controller` at tag `v0.2.3`. They are not the `v1.9.1` tag and they are not named in the upstream operator manifest. The agent still rewrites them. If they are absent from the package, the KubeVirt CR never becomes `Available`. `virt-launcher:v1.9.1` itself is already in the list and was pushed.
- **Pull secret scope.** Zarf copies `private-registry` into a namespace when a package manifest declares that namespace. The `atak-device` component does. The `kubevirt` component does not. A VMI applied into a namespace that kubectl created cannot pull the rewritten images. The full package deploy does not hit this.
- **Hypothesis (b), not the cause.** Pepr did not strip or reject the `image` volume. The Exemption exempts this launcher from `RestrictVolumeTypes`, and the admission result was `allowed: true`. The generated network policies did not affect startup.
- **Hypothesis (a), not the cause on this agent.** The agent rewrites `volumes[].image.reference`. The annotation keeps the original `quay.io` reference. The pod spec uses the internal registry.

## Fix and verification

`atak/zarf.yaml` on this branch pins v1.9.1 and adds:

- `quay.io/kubevirt/virt-template-apiserver:v0.2.3`
- `quay.io/kubevirt/virt-template-controller:v0.2.3`

`ImageVolume` stays at the v1.9 default. The Exemption is unchanged.

Verification is run [40845544294](https://github.com/jonathanagustin/uds-k3d-takserver/actions/runs/40845544294). After those images were in the package and `private-registry` was in `atak`, both the Zarf-only cluster and the UDS Core 1.15.2 cluster reported the VMI `Running` and `Ready`. The `volumecontainerdisk` init container completed. The disable-`ImageVolume` retry did not run.

## Recommendations

- Ship v1.9.1 with the two virt-template images in the package. The v1.8.4 pin's containerDisk reason is not reproduced here. v1.6.x and v1.7.x stay out because of the int32 checksum bug on k3s v1.37.
- Leave `ImageVolume` enabled. Disabling it was not required for the VMI to start.
- Keep the existing Exemption. Pepr matched it and allowed the image volumes.
- Keep creating namespace `atak` from the `atak-device` manifest, which is what seeds the registry pull secret. Do not apply the device VMI into a namespace created only with kubectl.
- The guest in this RCA was cirros, packaged the same way as `atak-civ-vm`. The Android image was not booted. A later ATAK e2e on v1.9.1 is the check that the real disk still reaches `Ready`.
