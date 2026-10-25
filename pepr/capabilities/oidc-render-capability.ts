// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { a, Capability } from "pepr";
import { runtime } from "../cluster.ts";
import { NAMESPACE, type PodLike } from "./oidc-render.ts";
import { preparePod } from "./workload.ts";

export const OidcRender = new Capability({
  name: "takserver-oidc-render",
  description: "Render the OIDC client secret into CoreConfig.xml before any TAK container starts",
  namespaces: [NAMESPACE],
});

const { When } = OidcRender;

When(a.Pod)
  .IsCreated()
  .InNamespace(NAMESPACE)
  .Mutate(request => {
    // A pod admitted without the init containers would start unrendered, so a
    // missing image is a rejection and not a skip. The module's onError is
    // reject, which turns this throw into a denied admission.
    return preparePod(request.Raw as unknown as PodLike, process.env, runtime.cluster);
  });
