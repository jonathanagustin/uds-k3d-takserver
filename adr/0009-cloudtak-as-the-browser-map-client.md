# 9. CloudTAK as the browser map client

Date: 2026-10-20

## Status

Accepted

## Context

TAK Server's browser map, WebTAK, is not in the public TAK Server source or its GitHub release. The public `LICENSE.md` names WebTAK as covered by the TAK EULA, and the maintainers confirmed in TAK-Product-Center/Server issue #23 that it is not open source. The images in this repository are built from the public source, so they have no browser map. The TAK web UI on `takserver.<domain>` is the admin and mission UI.

CloudTAK (dfpc-coe/CloudTAK, AGPL-3.0) is a separate, open source browser map client that connects to a TAK Server with the same certificate and password APIs that ATAK uses. It is not WebTAK and does not look like it.

## Decision

Add CloudTAK as an optional Zarf component, `cloudtak`, in its own namespace and on its own host, `map.<domain>`. TAK Server is unchanged apart from three Ingress rules.

- Build the image from a `upstream/cloudtak` submodule pinned to `v13.111.3`, with CloudTAK's own Dockerfile, then copy the result onto a smaller runtime stage that runs as uid 101 with a read-only root filesystem. Publish it next to the TAK images. Do not use upstream images.
- Deploy only the API (which serves the web app) and a PostGIS database. Leave out the tile server, events, media, retention, and S3.
- Put Keycloak in front with UDS Authservice. CloudTAK has no working OIDC login, so users sign in to CloudTAK with a TAK account after Keycloak.
- Create one TAK file user for CloudTAK and configure CloudTAK's server record from a bootstrap container in the CloudTAK pod, over localhost.
- Allow only the flows CloudTAK uses: PostGIS 5432, TAK API 8443 and 8447, and TAK messaging 8089. No internet egress.

## Consequences

- There is a browser map, built from source, that shows CoT from this TAK Server.
- Two sign-ins. Keycloak decides who reaches the page. CloudTAK and TAK see the CloudTAK account, not the Keycloak user, so TAK's audit trail and group membership for CloudTAK traffic belong to that one account. Removing the second sign-in needs an OIDC route in CloudTAK (upstream issue #661).
- TAK file users live in a file in the API pod. The bootstrap container recreates the account every five minutes if a restart lost it, so sign-in can fail for up to five minutes after the TAK API pod restarts.
- CloudTAK stores the TAK admin certificate and key in its database for its admin connection. The database is a place a TAK admin credential lives.
- No basemap without egress, and no file features without S3. Both are additions, not configuration of this component.
- CloudTAK's TAK library does not verify TAK's server certificate on its certificate-authenticated connections. 8447 sign-in is verified against the deploy-time CA.
- The image is about 600 MB, and the package grows by that much plus the CloudTAK release cadence: Renovate opens a pull request for each CloudTAK tag.
- CloudTAK is AGPL-3.0. Anyone who runs a modified CloudTAK for network users must offer its source. The modifications here are the start and bootstrap scripts, which are public in this repository.
