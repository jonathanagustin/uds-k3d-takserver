// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { a, Capability } from "pepr";
import { addRender, NAMESPACE, type PodLike } from "./oidc-render.ts";

export const OidcRender = new Capability({
  name: "takserver-oidc-render",
  description: "Render the OIDC client secret into CoreConfig.xml and name the metrics port on the API and messaging pods",
  namespaces: [NAMESPACE],
});

const { When } = OidcRender;

When(a.Pod)
  .IsCreated()
  .InNamespace(NAMESPACE)
  .Mutate(request => {
    const image = process.env.RENDER_IMAGE;
    // A pod admitted without the init container would start unrendered, so a
    // missing image is a rejection and not a skip. The module's onError is
    // reject, which turns this throw into a denied admission.
    if (!image) {
      throw new Error("RENDER_IMAGE is not set on the takserver-oidc module");
    }
    addRender(request.Raw as unknown as PodLike, image);
  });
