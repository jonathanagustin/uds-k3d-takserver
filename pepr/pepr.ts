// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { PeprModule } from "pepr";
import cfg from "./package.json" with { type: "json" };
import { CloudtakAdmin } from "./capabilities/cloudtak-admin-capability.ts";
import { CoreDns } from "./capabilities/coredns-rewrite-capability.ts";
import { GatewayCa } from "./capabilities/gateway-ca-capability.ts";
import { OidcRender } from "./capabilities/oidc-render-capability.ts";
import { Workload } from "./capabilities/workload-capability.ts";

// The module keeps the name takserver-oidc and its uuid from when OIDC was its
// only job. They name the webhooks and the watcher in a running cluster, and
// PodMonitor takserver-oidc selects pods by the uuid, so a rename would replace
// them on upgrade.
new PeprModule(cfg, [OidcRender, CoreDns, GatewayCa, CloudtakAdmin, Workload]);
