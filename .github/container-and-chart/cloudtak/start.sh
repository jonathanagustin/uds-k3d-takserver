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
nginx -e /dev/stderr -c /tmp/nginx/nginx.conf

exec node dist/index.js
