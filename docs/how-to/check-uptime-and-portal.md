# Check uptime probes and Portal tiles

Inspect the UDS probes and Portal entries for TAK and CloudTAK, and distinguish
browser availability from TAK client-port health.

## What you'll accomplish

Confirm that Core generated the expected probes, that Prometheus reports their
targets as up, and that Portal shows the browser tiles to the intended users.

## Prerequisites

- A full UDS Core deployment with monitoring and Portal. Slim core installs
  neither the Probe API nor Portal.
- TAK and CloudTAK deployed with their default uptime checks enabled.
- Access to Grafana Explore and Portal, and the UDS CLI with cluster read access.

## Before you begin

Use your deployment's domain in place of `<domain>`. The browser paths are
`/login`, because each application serves that page without relying on a
redirect to Keycloak. A passing browser probe does not prove a TAK client can
stream data; `tak-health` checks those ports separately.

## Steps

1. Check Package readiness and generated probes:

   ```bash title="Inspect Packages and probes"
   uds zarf tools kubectl get package -n takserver
   uds zarf tools kubectl get package -n cloudtak
   uds zarf tools kubectl get probes.monitoring.coreos.com -A
   ```

   Expect `uds-takserver-tenant-uptime` in `takserver` and
   `uds-map-tenant-uptime` in `cloudtak`. With client health enabled,
   `uds-tak-health-admin-uptime` covers `/stream`, `/api`, and `/enroll`.
2. In Grafana, open **UDS / Monitoring / Probe Uptime**. Check all five targets:
   TAK `/login`, CloudTAK `/login`, and the three `tak-health` paths. In Explore,
   query a target directly:

   ```text title="Check the TAK browser target"
   probe_success{instance="https://takserver.<domain>/login"}
   ```

   Expect `1`. Inspect `probe_http_status_code` for the same instance; `200`
   confirms the page answered. For a failed client health target, read the
   last checks:

   ```bash title="Inspect client-port checks"
   uds zarf tools kubectl logs deploy/tak-health -n takserver --tail=6
   ```

3. Open Portal as a UDS Core admin. Expect **TAK Server** and **CloudTAK**.
   Sign in separately as a member of `/CloudTAK/Users` who is not an admin;
   expect **CloudTAK** only. A user in neither group should see neither tile.
   The passthrough client ports and `tak-health` endpoint are intentionally
   hidden; their absence is expected.
4. If the optional ATAK package is installed, inspect
   `uds-atak-tenant-uptime` in namespace `atak` for
   `https://atak.<domain>/phone.html`. Authservice protects that page; Core
   provisions a separate probe client. The full-core job does not deploy ATAK,
   so its passing result does not verify this optional target.

## Verification

All enabled targets should have a current `probe_success` of `1`, and Portal
should show the tiles described above for each user. Core alerts after a target
has failed for five minutes. Its TLS expiry alerts concern the gateway
certificates, not the deploy-time TAK CA or passthrough certificates.

The full-core suite's `tests/uptime-probes.sh` verifies failure and recovery by
temporarily scaling CloudTAK and TAK messaging to zero. That test interrupts
clients; run it only on a disposable test deployment. `tests/portal.sh` runs
the browser checks for the three user roles.

## Troubleshooting

### There is no Probe resource

**Problem:** Monitoring has no target to scrape.

**Symptom:** The Probe API is absent or a named Probe is missing.

**Solution:** Confirm full Core monitoring is installed and `uptime.enabled`
has not been disabled. Describe the Package to inspect operator status. A
slim-core test that skips this check is not evidence that the probe works.

### A target reports zero

**Problem:** A generated check cannot reach its application.

**Symptom:** `probe_success` is `0`; HTTP status is `0` or `503`.

**Solution:** Status `0` means no HTTP response; check DNS, TLS, and routing.
For `503`, inspect the workload readiness. For `/stream`, read the
`tak-health` log and check messaging; `/api` and `/enroll` depend on TAK API.
For ATAK, inspect operator logs for the `uds-atak-viewer-probe` client.

## Related documentation

- [Uptime monitoring reference](../networking.md#uptime-monitoring)
- [Client-port health](../networking.md#client-port-health)
- [Monitoring and alerts](../configuration.md#monitoring)
