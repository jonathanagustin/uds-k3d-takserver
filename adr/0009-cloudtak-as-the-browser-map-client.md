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
- Sign people in through UDS Core Keycloak, not CloudTAK's password form. CloudTAK 13.111.3 has OIDC settings and a login button but no route behind it, so a small process in the CloudTAK pod serves `/api/login/oidc`: an authorization code flow with PKCE for a Keycloak client from the `Package` CR, then a TAK certificate enrolled with the user's Keycloak access token, then a CloudTAK session from CloudTAK's own session code. Password and passkey sign-in are turned off.
- Create one TAK file user for CloudTAK's admin connection and configure CloudTAK's server record from a bootstrap container in the CloudTAK pod, over localhost.
- Allow only the flows CloudTAK uses: PostGIS 5432, TAK API 8443 and 8447, TAK messaging 8089, and Keycloak on the tenant gateway 443. No internet egress.

Authservice in front of CloudTAK was the other option. It would gate the page, but CloudTAK would not see the Keycloak user. Each person would still need a TAK account and a second sign-in, and TAK would see that account.

## Consequences

- There is a browser map, built from source, that shows CoT from this TAK Server.
- One sign-in, on the UDS Keycloak page. The Keycloak user is the CloudTAK user and the subject of the TAK certificate CloudTAK uses for them, so TAK's audit trail and group membership follow the Keycloak user and their `/TAK/` groups.
- The sign-in route imports CloudTAK's compiled modules and writes CloudTAK's session the way CloudTAK does. A CloudTAK release that changes those modules can break sign-in. The CI sign-in test runs on each Renovate pull request for CloudTAK. If upstream adds an OIDC route (issue #661), the `sso` container can go.
- The redirect from CloudTAK's login page to Keycloak is a script nginx adds to the page, because CloudTAK has no setting for it.
- A CloudTAK session outlives the Keycloak session (CloudTAK's refresh lifetime), and CloudTAK logout does not end the Keycloak session.
- TAK file users live in a file in the API pod. The bootstrap container recreates the account every five minutes if a restart lost it, so the admin connection can lose its account for up to five minutes after the TAK API pod restarts. Keycloak users do not depend on that file.
- CloudTAK stores the TAK admin certificate and key in its database for its admin connection. The database is a place a TAK admin credential lives.
- No basemap without egress, and no file features without S3. Both are additions, not configuration of this component.
- CloudTAK's TAK library does not verify TAK's server certificate on its certificate-authenticated connections. 8447 enrolment is verified against the deploy-time CA.
- The image is built for amd64 and arm64 on native runners and joined into one index, as [ADR 10](0010-amd64-and-arm64.md) does for the TAK images. Its PostGIS is the same multi-arch `imresamu/postgis:15-3.4`.
- The image is about 600 MB, and the package grows by that much plus the CloudTAK release cadence: Renovate opens a pull request for each CloudTAK tag.
- CloudTAK is AGPL-3.0. Anyone who runs a modified CloudTAK for network users must offer its source. The modifications here are the start, sign-in, and bootstrap scripts and two nginx fragments, which are public in this repository. CloudTAK's own code is not changed.
