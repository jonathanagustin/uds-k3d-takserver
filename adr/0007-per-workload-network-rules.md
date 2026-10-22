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

- These are L4 rules: pod label and port. There is no waypoint, so there are no L7 or per-identity Istio authorization rules between these pods. Ambient mTLS still encrypts the traffic.
- Authservice is off by design (see [ADR 0004](0004-tak-oauth-uses-openid-discovery.md)). TAK authenticates browser users itself.
- Passthrough ports 8443, 8446, and 8089 terminate TLS in TAK. The mesh cannot inspect that traffic. TAK checks the client certificate.
- The list is a snapshot of one CI run plus the commented flows. A TAK feature that opens a new connection (federation, a plugin that calls out) needs a new flow. `test:flows` reports it as a connection with no rule.
