# 11. CloudTAK default basemap through a tile proxy in its pod

Date: 2026-10-20

## Status

Accepted

## Context

CloudTAK 13.111.3 starts with no basemap, so the map is blank until an administrator adds one. The CloudTAK-Data bundle in the image only has basemaps for commercial imagery services, which are not freely licensed.

CloudTAK serves a ZXY basemap through its own API (`/api/basemap/:id/tiles/:z/:x/:y`). The API fetches each tile itself and first runs `isSafeUrl` from `@tak-ps/node-safeurl`, which refuses private, loopback, and reserved addresses, including `240.0.0.0/4`. In this mesh, an external host registered through UDS `remoteHost` egress resolves to an Istio ServiceEntry address in that range. The API would therefore refuse every tile, and a tile server inside the cluster is a private address too.

CloudTAK also accepts a TileJSON document for a basemap. It fetches that document on the server, skipping `isSafeUrl` when the host is the PMTiles host (`localhost` when no PMTiles server is configured), and hands it to the web client as is. The web client adds the user's session token to tile URLs on the CloudTAK host only.

The OpenStreetMap Foundation tile policy allows interactive use of `tile.openstreetmap.org` with visible attribution, an identifying and contactable User-Agent, the browser's Referer passed through, caching per the server's headers (or at least 7 days), and no bulk or offline download.

UDS Core 1.15 installs the ambient egress namespace (`istio-egress-ambient`) as a required part of `core-base`. A Package `remoteHost` rule creates a ServiceEntry and an AuthorizationPolicy there for one exact host and port, limited to a service account.

## Decision

- nginx in the CloudTAK container proxies `/uds-basemap/tiles/{z}/{x}/{y}` to `basemap.url` (default `https://tile.openstreetmap.org/{z}/{x}/{y}.png`). `basemap.mjs` writes that nginx configuration from the chart's settings when the container starts:
  - Only signed-in users get tiles. An `auth_request` checks the token the web client adds, against CloudTAK's API on 127.0.0.1, and caches a valid answer for 60 seconds.
  - Requests to the tile host carry only Host, Accept, the browser's Referer (the site's address when there is none), and a User-Agent that names CloudTAK, this repository, and an optional operator contact. Browser cookies, Authorization headers, and forwarding headers are not sent.
  - TLS to the tile host is verified against the system CA bundle.
  - Tiles are cached on disk in `/tmp`, following the tile host's cache headers, or 7 days when it sends none. Stale tiles are served if the host fails.
  - Zoom levels outside `basemap.minzoom`..`basemap.maxzoom` are refused. Each session is limited to 20 tiles a second after a burst of 200, which a map view stays inside and bulk download does not.
- The bootstrap container keeps a server basemap record pointing at that path, with the attribution and a TileJSON URL on `localhost:5000`, and makes it CloudTAK's default for new users (`map::basemap`). It recognises the record by its URL path and changes it when the settings change.
- The Package allows egress from the `cloudtak` service account to the URL's host and port only, as a `remoteHost` rule. The pod gets its own `cloudtak` service account for that.
- `basemap.enabled: false` removes the record, the proxy, and the egress rule. `basemap.url` points at another tile server, for example one inside an air-gapped network, and `basemap.egress` replaces the generated rule for a tile server inside the cluster.

## Consequences

- The map shows OpenStreetMap on first sign-in, with "© OpenStreetMap contributors" in the map's attribution box.
- The cluster needs a route to the tile host. Installs without one set `basemap.enabled: false` or point `basemap.url` at a reachable tile server.
- The OSM tile servers are donation-funded and have no SLA. The policy expects a contactable User-Agent from a caching proxy, so production installs should set `basemap.contact`. Heavy use calls for a commercial provider or a self-hosted tile server (`basemap.url`).
- Users who signed in before the basemap existed keep the basemap they had. They can pick it in CloudTAK's basemap menu.
- CloudTAK's own tile route for this record (`/api/basemap/:id/tiles/:z/:x/:y`) still refuses the address, so server-side features that fetch tiles through it do not work with this basemap. The web map does not use that route for it.
- The image now has a third nginx fragment and `basemap.mjs`. Without `BASEMAP_ENABLED` the image behaves as before.
