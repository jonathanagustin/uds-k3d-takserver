// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { PeprModule } from "pepr";
import cfg from "./package.json" with { type: "json" };
import { CloudtakAdmin } from "./capabilities/cloudtak-admin-capability.ts";
import { CoreDns } from "./capabilities/coredns-rewrite-capability.ts";
import { GatewayCa } from "./capabilities/gateway-ca-capability.ts";
import { OidcRender } from "./capabilities/oidc-render-capability.ts";
import { onCaMaterial, TakClients } from "./capabilities/takclient-capability.ts";
import { Workload } from "./capabilities/workload-capability.ts";

// The module keeps the name takserver-oidc and its uuid from when OIDC was its
// only job. They name the webhooks and the watcher in a running cluster, and
// PodMonitor takserver-oidc selects pods by the uuid, so a rename would replace
// them on upgrade.
new PeprModule(cfg, [OidcRender, CoreDns, GatewayCa, CloudtakAdmin, Workload, TakClients]);

// The CRL in Secret takserver-crl has a nextUpdate 730 days out. The watcher
// checks it once a day and writes a new one in the last 60 days, so a quiet
// cluster does not reach the date where Java rejects every client.
if (process.env.PEPR_WATCH_MODE === "true") {
  setInterval(() => void onCaMaterial(undefined, "MODIFIED").catch(() => undefined), 24 * 60 * 60 * 1000).unref();
}
