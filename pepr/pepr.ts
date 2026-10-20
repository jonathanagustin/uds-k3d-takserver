// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { PeprModule } from "pepr";
import cfg from "./package.json" with { type: "json" };
import { OidcRender } from "./capabilities/oidc-render-capability.ts";

new PeprModule(cfg, [OidcRender]);
