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

## Adding an exemption

1. Keep the matcher as narrow as it can be. Never use `.*`.
2. Name only the policies the workload triggers.
3. Add a section above with the policy, matcher, reason, and what would remove it.
