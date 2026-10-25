# Policy exemptions and security posture

UDS Core's policy engine validates and mutates every pod. A package has to keep its exemptions small and say why each one exists. This page lists every `Exemption` the package renders, and the one the optional ATAK test device adds, and the places where it deliberately differs from the default UDS posture.

`.github/scripts/check-exemptions.sh` renders the chart, reads `atak/deploy/*.yaml`, and fails when an `Exemption` has no `## <name>` section on this page. hk runs it when the chart, `atak/deploy/`, this page or the script changes. Add the section in the same change that adds the exemption.

`tests/exemptions.sh` (task `test:exemptions`, part of `test:all` on amd64 and arm64) audits the live cluster the way the UDS Core audit guide does. It fails when an `Exemption` that matches the `takserver` or `cloudtak` namespace is not the expected one, names other policies, or uses a bare wildcard, and when a pod in those namespaces is annotated `exempted` without a matching expected exemption. It prints the exempted-resource list and the security context of each TAK pod.

## Exemptions

## takserver-db-setup

- **Policy:** `RestrictIstioSidecarOverrides`
- **Matcher:** `^takserver-db-setup-.*`, kind `pod`, namespace `takserver`
- **Defined in:** `charts/takserver/templates/prereqs.yaml`
- **Why:** The upstream chart's post-install database Job sets the `proxy.istio.io/config` annotation so the schema container waits for an Istio sidecar. The chart has no value that removes it. Without the exemption the policy denies the Job's pod, and Helm waits out its timeout.
- **Why it is safe:** The package uses Istio ambient mode, which does not inject a sidecar. The annotation has no effect on the mesh here. The matcher is the one hook Job name, not a wildcard.
- **What removes it:** An upstream chart that makes the annotation optional or drops it.

## kubevirt

Only the optional ATAK test device uses this. It is not part of the package: `atak/deploy/kubevirt-exemption.yaml` is applied by the ATAK end-to-end workflow, and a normal install never creates it. It is one `Exemption` object with three entries.

- **Defined in:** `atak/deploy/kubevirt-exemption.yaml`
- **KubeVirt node agent** (`virt-handler-*`, namespace `kubevirt`)
  - **Policies:** `DisallowPrivileged`, `RequireNonRootUser`, `DropAllCapabilities`, `RestrictCapabilities`, `RestrictHostPathWrite`, `RestrictVolumeTypes`, `DisallowHostNamespaces`, `RestrictSELinuxType`
  - **Why:** `virt-handler` is a privileged node agent. It opens `/dev/kvm`, manages the launcher pods' network namespaces and mounts the containerDisk, so it needs host paths, host PID and privileged mode.
- **KubeVirt control plane** (`virt-(operator|api|controller|exportproxy)-*`, namespace `kubevirt`)
  - **Policies:** `RequireNonRootUser`, `DropAllCapabilities`, `RestrictVolumeTypes`
  - **Why:** These run as non-root, but the operator does not set every field the UDS defaults expect.
- **ATAK test device VM launcher** (`virt-launcher-atak-device-*`, namespace `atak`)
  - **Policies:** `RestrictCapabilities`, `DropAllCapabilities`, `RestrictVolumeTypes`, `RestrictHostPathWrite`, `RestrictIstioTrafficOverrides`
  - **Why:** `virt-launcher` runs the device VM as UID 107 and adds `NET_BIND_SERVICE` for masquerade networking. KubeVirt always sets the `traffic.sidecar.istio.io/kubevirtInterfaces` annotation on launcher pods. It only matters to Istio sidecars and there is none here, so it changes nothing.
- **Why it is safe:** Every matcher names the KubeVirt components or the one launcher name pattern, in the `kubevirt` and `atak` namespaces. Nothing in the `takserver` or `cloudtak` namespaces is exempted.
- **What removes it:** Not running the ATAK test device, or a KubeVirt release that sets these fields itself.

## Differences from the default UDS posture

These are not exemptions. The policy engine mutates these settings or leaves them alone, so no `Exemption` object exists.

### Non-root user and writable root filesystem

The TAK images default to `USER 0`, and the upstream Deployments set no `securityContext`. UDS Core's policy engine fills it in when each pod is admitted. `test:exemptions` prints the result on every CI run. On amd64 and arm64 every TAK pod (api, config, messaging, plugins, ignite, nats, the database setup hook, postgresql) runs with:

- pod: `runAsUser: 1000`, `runAsGroup: 1000`, `runAsNonRoot: true`. PostgreSQL also has `fsGroup: 1001`, and its container runs as `1001`.
- each container: `allowPrivilegeEscalation: false`, `capabilities.drop: ["ALL"]`.

TAK still starts because the image makes the directories it writes world-writable (`/certs`, `/logs`, `/conf`, `/work` and the TAK work and log directories under `/opt/tak`). The root filesystem stays writable. A read-only one would mean forking the upstream Deployments. See [ADR 0005](../adr/0005-slim-core-boundaries.md) and [Configuration](configuration.md).

### Ambient mesh instead of sidecars

Both Package CRs set `serviceMesh.mode: ambient`. Passthrough TLS on 8443, 8446, and 8089 has to reach TAK unchanged, and there is no waypoint and no Authservice in front of TAK. See [Networking](networking.md).

## UDS package requirements

The [UDS package requirements](https://docs.defenseunicorns.com/core/concepts/configuration--packaging/package-requirements/) are a pre-publish checklist. These are the items this package does not meet, or meets only through the exception the requirement allows.

### Metrics monitor

- **Requirement:** Implement a monitor for each application metrics endpoint, unless the application provides no metrics.
- **Status:** Not applicable. TAK Server 5.7-RELEASE-14 has no Prometheus endpoint, and its actuator is served on the Marti HTTPS connectors, where port 8443 requires a client certificate. The Package has no `monitor` entry.
- **Details:** [ADR 3](../adr/0003-no-prometheus-monitor.md) and [Configuration](configuration.md).
- **What changes it:** A Prometheus registry in the TAK image and a metrics port that does not require a client certificate.

### Commands in Zarf actions

- **Requirement:** Zarf actions use only `coreutils` or `./zarf` self references.
- **Status:** Not met. The `onDeploy` actions in `zarf.yaml` use `sed`, and two of them run `python3`: one writes the CoreDNS rewrite patch as JSON, and one runs `patch-oidc-pods.py`, which adds the startup and trust init containers that the upstream Deployments cannot take through values. The actions use `kubectl` when it is on the path and fall back to `zarf tools kubectl`. Without `python3` on the deploy host, those two actions fail.
- **What removes it:** Moving the init containers into the `takserver-oidc` Pepr module or an upstream chart value, and building the CoreDNS patch with `./zarf tools yq`.

### Version scheme

- **Requirement:** Versions follow `<upstream-app-version>-uds.<n>`, or Semantic Versioning when that scheme does not apply.
- **Status:** Semantic Versioning. release-please sets the version from Conventional Commits, and the published package tag is `<version>-upstream`, for example `0.3.0-upstream`. The package ships two upstream applications with separate versions, TAK Server `5.7-RELEASE-14` and CloudTAK (the `appVersion` in `charts/cloudtak/Chart.yaml`), so no single application version leads the tag. release-please stays instead of the template's `<upstream-app-version>-uds.<n>` tag and `uds-pk release` flow, because that second publisher would also have to bump `charts/takserver/Chart.yaml`, `common/zarf.yaml`, and `README.md`, which release-please already owns.

## Adding an exemption

1. Keep the matcher as narrow as it can be. Never use `.*`.
2. Name only the policies the workload triggers.
3. Add a section above with the policy, matcher, reason, and what would remove it.
