#!/bin/bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Start CloudTAK as a non-root user. Upstream api/start writes
# /etc/nginx/nginx.conf, starts nginx as root, and runs `npm run prod` in a
# loop. This renders the same nginx.conf into /tmp, drops the `user`
# directive, moves the pid file, logs, and temp paths under /tmp, and runs
# the API once so Kubernetes sees a crash and restarts the container.
set -euo pipefail

mkdir -p /tmp/nginx
node nginx.conf.js \
  | sed -e '/^user /d' \
        -e 's#^pid .*#pid /tmp/nginx/nginx.pid;#' \
        -e 's#^error_log .*#error_log /dev/stderr warn;#' \
        -e 's#^\( *\)access_log .*#\1access_log /dev/stdout main;\n\1client_body_temp_path /tmp/nginx/client_body;\n\1proxy_temp_path /tmp/nginx/proxy;\n\1fastcgi_temp_path /tmp/nginx/fastcgi;\n\1uwsgi_temp_path /tmp/nginx/uwsgi;\n\1scgi_temp_path /tmp/nginx/scgi;#' \
  > /tmp/nginx/nginx.conf

# Keycloak sign-in (sso.mjs in its own container, 127.0.0.1:5002). The ^~
# prefix location wins over CloudTAK's `location ~ ^/api` regex, and the
# sub_filter loads the auto-redirect script into the app's HTML pages.
if [ "${CLOUDTAK_Config_oidc_enabled:-false}" = "true" ]; then
  awk -v sso=/home/etl/uds/nginx-sso.conf -v head=/home/etl/uds/nginx-sso-head.conf '
    /location ~ \^\/api/ { while ((getline l < sso) > 0) print l; close(sso) }
    { print }
    /server_tokens off;/ { while ((getline l < head) > 0) print l; close(head) }
  ' /tmp/nginx/nginx.conf > /tmp/nginx/nginx.conf.sso
  mv /tmp/nginx/nginx.conf.sso /tmp/nginx/nginx.conf
  grep -q 'location ^~ /api/login/oidc' /tmp/nginx/nginx.conf
fi

# Default basemap tile proxy (basemap.mjs). Off unless the chart turns it on.
if [ "${BASEMAP_ENABLED:-}" = "true" ]; then
  node /home/etl/uds/basemap.mjs nginx /tmp/nginx/basemap
  awk -v srv=/tmp/nginx/basemap/server.conf -v http=/tmp/nginx/basemap/http.conf '
    /location ~ \^\/api/ { while ((getline l < srv) > 0) print l; close(srv) }
    { print }
    /^ *scgi_temp_path / { while ((getline l < http) > 0) print l; close(http) }
  ' /tmp/nginx/nginx.conf > /tmp/nginx/nginx.conf.basemap
  mv /tmp/nginx/nginx.conf.basemap /tmp/nginx/nginx.conf
  grep -q 'location ^~ /uds-basemap/' /tmp/nginx/nginx.conf
fi
nginx -e /dev/stderr -c /tmp/nginx/nginx.conf

exec node dist/index.js
