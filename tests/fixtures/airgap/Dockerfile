# syntax=docker/dockerfile:1
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

FROM alpine:3.22@sha256:bfe7ceb9f09ec0566c48fb93356e45a47a00be5a1dd14fa5b909e7709c66b034
RUN --mount=type=secret,id=ca,required=true SSL_CERT_FILE=/run/secrets/ca apk add --no-cache iptables=1.8.11-r1 curl=8.14.1-r4 busybox-extras=1.37.0-r20
CMD ["sleep", "infinity"]
