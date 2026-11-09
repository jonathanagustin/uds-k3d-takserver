# 23. Adapt the upstream TAK chart with a Pepr module

Date: 2026-11-03

## Status

Accepted. This record was written on November 3, 2026, after the decision. It documents a choice made in pull requests [#4](https://github.com/jonathanagustin/uds-takserver/pull/4) (October 20, 2026) and [#177](https://github.com/jonathanagustin/uds-takserver/pull/177) (November 1, 2026). Those pull requests did not compare the options below in writing. This record compares them now, with the evidence available on November 3.

## Context

The package deploys TAK's upstream Helm chart, `src/takserver-cluster/deployments/helm` at tag `5.7-RELEASE-14`, without changing it. That chart has no values for the things TAK needs on UDS:

- an init container that renders the OIDC client secret and the keystore password into `CoreConfig.xml` before TAK starts
- a Secret, not a ConfigMap, for the certificate volume
- startup order, probes, and Ignite timeouts
- a named `metrics` port on the API and messaging pods
- copies of the TAK CA into the gateway and CloudTAK namespaces, and a CoreDNS rewrite

Two facts set the bar:

- A TAK pod must never start with the unrendered template. TAK copies one node's `CoreConfig.xml` to the others through the Ignite cache, so one bad pod breaks sign-in on all of them ([#3](https://github.com/jonathanagustin/uds-takserver/issues/3), [#4](https://github.com/jonathanagustin/uds-takserver/pull/4)). Before #4, a Python script patched the Deployments after Helm finished. The first pods had already started by then.
- UDS package rules say a package MUST use the upstream chart when one is available and suitable. Zarf actions MUST NOT run local commands other than `coreutils` and `./zarf` ([UDS Package Requirements](https://docs.defenseunicorns.com/core/v1-16/concepts/configuration--packaging/package-requirements/)). Before #177, `zarf.yaml` ran `kubectl`, `python3`, and `sed` at deploy time ([#35](https://github.com/jonathanagustin/uds-takserver/issues/35)).

The options:

1. **Pepr module (current).** `pepr/`, five capabilities. See [The takserver-oidc module](../docs/configuration.md#the-takserver-oidc-module).
2. **Fork the chart.** Copy it into this repository and edit the templates.
3. **Helm post-renderer.** A program or Kustomize step that edits the chart's output before Helm applies it.
4. **Kustomize overlay or Zarf manifests.** Render the chart at package build time and patch the result with Kustomize. Zarf would then apply it as plain manifests.
5. **Upstream pull requests.** Add the missing values to TAK's chart.

## Comparison

**V** means verified, with the source in [Evidence](#evidence). **R** means reasoned from how the tools work and not tested here.

| Criterion | 1. Pepr (current) | 2. Fork | 3. Post-renderer | 4. Kustomize or Zarf manifests | 5. Upstream PRs |
| --- | --- | --- | --- | --- | --- |
| Values known only at run time: the OIDC secret and the keystore password | Works. The init container reads the Secrets when the pod starts. **V** [E1] | Works. The same init container in the template. The values are read in the pod, not at render time. **R** | Works the same way. **R** | Works the same way. **R** | Works once upstream adds an init container value. **R** |
| Values that depend on cluster state: CA copies across namespaces, CoreDNS rewrite from gateway Service addresses, startup order | Watcher reconciles them and updates copies when the source changes. **V** [E1] | Needs Jobs or hooks in the config chart, or deploy actions. **R** | Cannot. A post-renderer runs once, before apply, and sees only manifests. **R** | Cannot. Kustomize runs at package build time. **V** [E6] | Out of the chart's scope. **R** |
| Objects created at run time: Deployment pods, the db-setup hook Job, the Ignite StatefulSet | The pod mutation runs on every new TAK pod from any controller. **V** [E1] The hook pod is handled by a UDS Core Exemption, not by this module. **V** [E2] | Full control of every template, hooks included. **R** | Can patch the pod templates in the Deployments and the StatefulSet. **R** Helm 4 sends hooks to the post-renderer by default. Helm 3 did not. **V** [E5] | Hooks become plain manifests and lose Helm hook ordering. **R** | Full control once merged. **R** |
| Zarf and air-gap fit | Pepr's controller image comes from UDS Core's Zarf registry, so the package ships no extra image. **V** [E3] | A local chart is the normal Zarf path. **R** | Zarf v0.89.0 has no field for a user post-renderer. It sets Helm's single post-renderer slot to its own. **V** [E4] An open Zarf issue asks for the feature. **V** [E4] | Zarf supports Kustomize for manifests, built at package create. **V** [E6] The UDS rule asks for the upstream chart. **V** [E7] | Nothing to add. **R** |
| Upgrade and drift cost against upstream | Selectors depend on upstream names and labels. A rename breaks a match, and the 100% coverage tests do not catch that. **R** | Highest. Every upstream release is a merge. **R** Upstream has not pushed since April 3, 2026, so the cost is low today. **V** [E8] | Patches key on names, like Pepr. **R** | Same as a post-renderer, plus a re-render per release. **R** | Lowest, once merged and released. **R** |
| Consistency with UDS Core | UDS Core's operator and policies run on Pepr. This module is built with the Pepr version Core 1.16.0 runs. **V** [E3] [E9] | Goes against the UDS rule to use the upstream chart, unless that chart counts as not suitable. **V** [E7] | No UDS Core precedent found. **R** | No UDS Core precedent found. **R** | Matches the UDS preference for upstream charts. **V** [E7] |
| Testability | Each capability has `node --test` unit tests that use a fake cluster. The build fails under 100% line, branch, and function coverage. **V** [E10] | `helm template` plus snapshot or policy tests. **R** | The same, on the patch output. **R** | The same. **R** | Upstream's tests. **R** |
| Operating cost | Two admission pods and one watcher in `pepr-system`. The watcher was killed for memory at 256Mi and now has 512Mi. **V** [E11] | None at run time. **R** | None at run time. **R** | None at run time. **R** | None at run time. **R** |
| Failure mode | Fails closed. `onError` is `reject` and the webhook `failurePolicy` is `Fail`. A pod the module cannot prepare is denied, never started unrendered. **V** [E1] [E12] | A bad template fails at `helm install`. Nothing runs at admission. **R** | A bad patch fails at `helm install`. **R** | A bad patch fails at `uds zarf package create`. **R** | Upstream's. **R** |

### If `pepr-system` is down

- The webhook matches only the TAK pods, Deployments, and Ignite objects in `takserver`, so the rest of the cluster is not blocked. **V** [E12]
- A new config, messaging, API, or plugins pod is denied until the module is back, and so is a change to those Deployments or the Ignite objects. Running pods keep running. **R**
- The watcher's work stops. A changed CA is not copied, CoreDNS is not updated, and `takserver-startup` is not written, so a Zarf deploy waits on that health check. **R**
- With options 2 to 5, a `pepr-system` outage still affects UDS Core's own policies. This package cannot avoid that part. **R**

## Decision

Keep the Pepr module. It is the only option here that is supported by both Zarf and UDS and that also covers objects that depend on cluster state after install. The other options would still need deploy actions or Jobs for the CA copies, the CoreDNS rewrite, and the startup order. #177 removed those deploy actions to meet the `coreutils`-only rule.

## Where another option would win

- **Fork.** If upstream TAK stays inactive, a fork's merge cost stays near zero. It would remove the controller, its memory, and the fail-closed admission path. The CA copies and CoreDNS work would still need a Jobs-based or controller-based home. Revisit if the module grows mainly to patch templates.
- **Post-renderer.** For static template patches, a post-renderer would do the same work without a running controller. Revisit when Zarf supports post-renderers ([zarf-dev/zarf#3587](https://github.com/zarf-dev/zarf/issues/3587)). A related pattern applies `.patch` files to the chart source at package create time ([zarf-dev/zarf#4840](https://github.com/zarf-dev/zarf/pull/4840), an open docs pull request). It is a fork with the patches kept in this repository.
- **Upstream pull requests.** This is the long-term fix for the init container, the Secret volume, the probes, and the metrics port. Upstream has open outside pull requests and no push since April 3, 2026. This repository closed [#175](https://github.com/jonathanagustin/uds-takserver/issues/175), an upstream patch request, for that reason. If upstream becomes active, send the chart values first. Each value it accepts removes code from the module.

## Consequences

- The package depends on UDS Core's Pepr controller image and version. Upgrade Core first.
- The module must keep its webhook narrow. `pepr/scripts/finalize-chart.mjs` fails the build if a Pepr upgrade changes the template it edits.
- The webhook's object selector matched the `app` label. In the upstream chart, the four Deployments, the Ignite ConfigMap, and the Ignite StatefulSet have no `app` label on the object itself, only in their pod templates. Their admission handlers never ran, and the watcher's reconcile did that work after each object was stored. The pods were still prepared at admission. Confirmed from CI admission logs in [#273](https://github.com/jonathanagustin/uds-takserver/issues/273). The webhook now matches those objects by name.
- A new upstream release needs a check that the names and labels the module selects on still exist.

## Evidence

- **E1.** `pepr/capabilities/oidc-render-capability.ts` mutates each new TAK pod and rejects one it cannot prepare. `pepr/capabilities/workload.ts` and the other capabilities hold the reconciles. `pepr/package.json` sets `"onError": "reject"`.
- **E2.** `charts/takserver/templates/prereqs.yaml` creates Exemption `takserver-db-setup`. See [What the chart mounts](../docs/configuration.md#what-the-chart-mounts).
- **E3.** The [README](../README.md) 0.7 upgrade notes: the module uses Pepr 2.0.7, the version UDS Core 1.16.0 runs, and the controller image UDS Core put in the Zarf registry.
- **E4.** `uds-cli` 0.41.0 (`mise.toml`) builds with `github.com/zarf-dev/zarf v0.89.0` ([go.mod](https://github.com/defenseunicorns/uds-cli/blob/v0.41.0/go.mod)). In Zarf v0.89.0, `ZarfChart` has no post-renderer field ([`src/api/v1alpha1/component.go` line 198](https://github.com/zarf-dev/zarf/blob/v0.89.0/src/api/v1alpha1/component.go#L198)). Install and upgrade set `client.PostRenderer` to Zarf's own renderer ([`src/internal/packager/helm/chart.go` lines 326, 373, and 424](https://github.com/zarf-dev/zarf/blob/v0.89.0/src/internal/packager/helm/chart.go#L373)). That renderer fills in Zarf variables, adds Zarf package labels to each resource and pod template, and handles namespaces ([`post-render.go` line 89](https://github.com/zarf-dev/zarf/blob/v0.89.0/src/internal/packager/helm/post-render.go#L89)). [zarf-dev/zarf#3587](https://github.com/zarf-dev/zarf/issues/3587), "Add helm PostRenderer Support", has been open since March 19, 2025.
- **E5.** Helm v4.3.0 `pkg/action/action.go` defaults to `PostRenderStrategyCombined`, which sends hooks and templates to the post-renderer together. Its `nohooks` mode is described as the Helm 3 behavior.
- **E6.** Zarf v0.89.0 accepts `kustomizations` on manifests only ([`component.go` line 283](https://github.com/zarf-dev/zarf/blob/v0.89.0/src/api/v1alpha1/component.go#L283)). It builds them during package assembly ([`src/pkg/packager/assemble/assemble.go` line 656](https://github.com/zarf-dev/zarf/blob/v0.89.0/src/pkg/packager/assemble/assemble.go#L656)).
- **E7.** [UDS Package Requirements](https://docs.defenseunicorns.com/core/v1-16/concepts/configuration--packaging/package-requirements/): use the upstream chart when available and suitable, and keep UDS settings in a separate config chart. Zarf actions use only `coreutils` or `./zarf`.
- **E8.** GitHub reports `pushed_at` 2026-04-03 for [TAK-Product-Center/Server](https://github.com/TAK-Product-Center/Server), with outside pull requests still open. See the closing note on [#175](https://github.com/jonathanagustin/uds-takserver/issues/175).
- **E9.** [UDS Core `src/pepr`](https://github.com/defenseunicorns/uds-core/tree/main/src/pepr) holds the operator and the policies.
- **E10.** `pepr/package.json` script `test:coverage` passes `--test-coverage-lines=100`, `--test-coverage-branches=100`, and `--test-coverage-functions=100`. Added in [#69](https://github.com/jonathanagustin/uds-takserver/pull/69).
- **E11.** [#234](https://github.com/jonathanagustin/uds-takserver/pull/234) and `values/pepr-values.yaml`.
- **E12.** `pepr/scripts/finalize-chart.mjs` narrows the webhook to the `takserver` namespace and the TAK objects. The generated chart keeps `failurePolicy: Fail`. `tests/oidc-render.sh` checks both in a cluster.
