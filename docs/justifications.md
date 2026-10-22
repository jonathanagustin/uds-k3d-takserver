# Policy exemptions and security posture

UDS Core's policy engine validates and mutates every pod. A package has to keep its exemptions small and say why each one exists. This page lists every `Exemption` the package renders, and the places where it deliberately differs from the default UDS posture.

`.github/scripts/check-exemptions.sh` renders the chart and fails when an `Exemption` has no `## <name>` section on this page. Add the section in the same change that adds the exemption.

## Exemptions

## takserver-db-setup

- **Policy:** `RestrictIstioSidecarOverrides`
- **Matcher:** `^takserver-db-setup-.*`, kind `pod`, namespace `takserver`
- **Defined in:** `chart/templates/prereqs.yaml`
- **Why:** The upstream chart's post-install database Job sets the `proxy.istio.io/config` annotation so the schema container waits for an Istio sidecar. The chart has no value that removes it. Without the exemption the policy denies the Job's pod, and Helm waits out its timeout.
- **Why it is safe:** The package uses Istio ambient mode, which does not inject a sidecar. The annotation has no effect on the mesh here. The matcher is the one hook Job name, not a wildcard.
- **What removes it:** An upstream chart that makes the annotation optional or drops it.

## Differences from the default UDS posture

These are not exemptions. The policy engine mutates these settings or leaves them alone, so no `Exemption` object exists.

### Root user and writable root filesystem

The TAK images run as root and write `/certs`, `/logs`, `/conf`, and `/tmp`. The upstream Deployments expose no `securityContext`, so the package cannot set `runAsNonRoot` or a read-only root filesystem without forking them. See [ADR 0005](../adr/0005-slim-core-boundaries.md) and [Configuration](configuration.md).

What UDS mutates on the TAK pods (`runAsNonRoot`, `runAsUser`, dropped capabilities) has to be read from a live cluster, not assumed. Record it here after a run:

```sh
uds zarf tools kubectl get pods -n takserver -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].securityContext}{"\n"}{end}'
```

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
- **Status:** Semantic Versioning. release-please sets the version from Conventional Commits, and the published package tag is `<version>-upstream`, for example `0.3.0-upstream`. The package ships two upstream applications with separate versions, TAK Server `5.7-RELEASE-14` and CloudTAK `v13.111.3`, so no single application version leads the tag.

## Adding an exemption

1. Keep the matcher as narrow as it can be. Never use `.*`.
2. Name only the policies the workload triggers.
3. Add a section above with the policy, matcher, reason, and what would remove it.
