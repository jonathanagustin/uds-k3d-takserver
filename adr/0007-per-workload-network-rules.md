# 7. Per-workload network rules inside the namespace

Date: 2026-10-20

## Status

Accepted

## Context

The Package CR allowed all traffic between pods in the `takserver` namespace with two `remoteGenerated: IntraNamespace` rules. Any pod could reach Postgres, NATS, Ignite, and every TAK port. A compromised pod, or a new pod added to the namespace, had the same reach as the TAK processes.

The rules have to match what the pods really open. The upstream chart and `CoreConfig.xml` say who should talk to whom, but not all of it: the TAK processes are Ignite client nodes, and Ignite client nodes also connect to each other.

## Decision

- Remove both `IntraNamespace` rules. Every pod-to-pod flow is an Egress rule on the client and an Ingress rule on the server, limited to one port.
- The flows live in `intraNamespace` in `charts/takserver/values.yaml`, so a deployment can add or remove one without editing the template. `additionalNetworkAllow` still appends rules.
- The list comes from observed connections. `tests/flows.py` reads `/proc/net/tcp` in every pod, maps each connection to pods and a port, and checks it against the Package allow list. Run against the old rules, it saw:
  - API, messaging, and plugins to Postgres 5432 and NATS 4222. The config pod held neither.
  - Each TAK process to Ignite on 47100 and 47500.
  - TAK process to TAK process on 47100: api to config and messaging, messaging to config, plugins to api, config, and messaging.
- Flows a snapshot cannot see are kept on purpose and commented: the `takserver-db-setup` Job to Postgres (it runs once and exits), Ignite to Ignite on 47100 and 47500 (CI runs one replica), and the existing Ignite rules on 10800.
- The TAK-to-TAK rule covers every pair both ways on 47100 only. Which node opens an Ignite connection depends on which one sends first, so the observed directions are not fixed.
- Kubernetes API egress and the tenant gateway egress for Keycloak are unchanged.
- `test:flows --check` fails CI when a connection has no rule. `test:policies` fails when the Package has an `IntraNamespace` rule.

## Consequences

A pod can only reach the pods and ports its role needs. Postgres accepts connections only from the API, messaging, plugins, and the schema Job. A new workload in the namespace gets no access until a flow is added.

Remaining gaps:

- These are layer 4 (L4) rules: pod label, port and, since the update below, the client's ServiceAccount. There is no waypoint, so there are no layer 7 (L7) authorization rules between these pods. Ambient mTLS still encrypts the traffic.
- Authservice is off by design (see [ADR 0004](0004-tak-oauth-uses-openid-discovery.md)). TAK authenticates browser users itself.
- Passthrough ports 8443, 8446, and 8089 terminate TLS in TAK. The mesh cannot inspect that traffic. TAK checks the client certificate.
- The list is a snapshot of one CI run plus the commented flows. A TAK feature that opens a new connection (federation, a plugin that calls out) needs a new flow. `test:flows` reports it as a connection with no rule.

## Update: workload identity on Ingress rules

Every Ingress rule from other pods now also sets `remoteServiceAccount`. The UDS Operator then writes the AuthorizationPolicy source as the client's mTLS principal (`cluster.local/ns/<namespace>/sa/<account>`) instead of the whole namespace. The NetworkPolicy still matches the pod labels.

- `workloadServiceAccounts` in `charts/takserver/values.yaml` maps each TAK client's app label to its ServiceAccount. The render fails for a client with no entry. The upstream chart gives api, messaging, config, plugins and Ignite one account, `takserver-ignite`, and leaves the db-setup Job on `default`. So the identity separates the TAK processes from any other pod in the namespace, but not from each other. The opt-in admission path described below assigns per-process accounts without an upstream chart fork; the default remains shared.
- The Ingress rules from CloudTAK, in the takserver Package and on CloudTAK's PostGIS, match the `cloudtak` ServiceAccount. The basemap `remoteHost` rule already sets `serviceAccount: cloudtak`.
- In Core 1.16.0, `serviceAccount` scopes ambient waypoint egress for both `remoteHost` and `remoteGenerated: Anywhere` ([rule translation](https://github.com/defenseunicorns/uds-core/blob/v1.16.0/src/pepr/operator/controllers/istio/egress.ts#L148-L176), [ServiceAccount principals](https://github.com/defenseunicorns/uds-core/blob/v1.16.0/src/pepr/operator/controllers/istio/egress-ambient.ts#L85-L159)). Ordinary in-cluster egress still uses [label selectors](https://github.com/defenseunicorns/uds-core/blob/v1.16.0/src/pepr/operator/controllers/network/generators/egress.ts), so the Keycloak tenant gateway and Kubernetes API rules stay label-based.
- `tests/flows.py --check` fails when an Ingress rule from other pods has no `remoteServiceAccount`. It also fails when a generated ALLOW AuthorizationPolicy admits the namespace or a peer namespace with no principal.
- The cloudtak test fetches a tile as ServiceAccount `cloudtak`, then runs a second pod as ServiceAccount `basemap-denied` against the same host. Both pods carry `app: cloudtak`, so the negative test passes the same label selector and exercises the identity check at the egress waypoint. A readiness probe that always fails keeps the temporary pod out of the CloudTAK Service's ready endpoints. That pod has to fail its fetch. Reaching the host from the other account means the egress rule is not limited to CloudTAK.

## Dedicated TAK identities (opt-in migration)

The pinned upstream chart hardcodes `takserver-ignite` on four TAK Deployments.
The existing fail-closed workload admission adapter can assign dedicated
ServiceAccounts without forking that chart. Package value
`tak.workloadIdentityPhase` coordinates policy and admission: `shared` preserves
the default/custom accounts; `transition` admits both old and dedicated
principals while rotating the Deployments; `strict` removes the transitional
legacy principal; `rollback` admits both while restoring the legacy identity.
The config chart creates namespaced discovery Roles and bindings, restricting
the Ignite log permission to config. No new cluster-wide permission is granted.
Pod admission preserves a standalone pod's chosen account, so copying an app
label does not automatically acquire that workload's identity.

Policy generation is asynchronous. The supported package-stage path uses the
pinned Zarf 0.89.0 [sequential chart deployment](https://github.com/zarf-dev/zarf/blob/v0.89.0/src/pkg/packager/deploy.go#L690-L739)
and [per-chart custom-resource health check](https://github.com/zarf-dev/zarf/blob/v0.89.0/src/internal/packager/helm/chart.go#L179-L202).
The configuration chart must complete before the Pepr admission chart starts.
For an existing Package, the checker rejects a stale
[`status.observedGeneration`](https://github.com/zarf-dev/zarf/blob/v0.89.0/vendor/sigs.k8s.io/cli-utils/pkg/kstatus/status/generic.go#L73-L100)
and requires a true [Ready condition](https://github.com/zarf-dev/zarf/blob/v0.89.0/vendor/sigs.k8s.io/cli-utils/pkg/kstatus/status/status.go#L154-L181).
Core 1.16.0 [publishes both after reconciliation](https://github.com/defenseunicorns/uds-core/blob/v1.16.0/src/pepr/operator/reconcilers/package-reconciler.ts#L159-L174).
This replaces the earlier manual Helm config-first staging procedure for this
path. A stored Package alone does not establish policy convergence. See the
[operator procedure](../docs/networking.md#opt-in-tak-workload-identity-migration).

Existing installations follow `shared` → `transition` → `strict`, verifying all
live Pod identities and positive/negative traffic before removing legacy
principals. Reversal follows `strict` → `rollback` → `shared`, retaining both
principal sets until legacy identities return. A clean strict installation is a
separate qualification case, not a direct shared-to-strict migration.

The guarded package trial also checks retained application data through migration
and reversal, then tests a clean strict reinstall in its disposable cluster.
**Both-architecture live qualification is pending.** No successful run is claimed;
source tests and rendered manifests alone do not satisfy issue #32. The default
remains shared.
