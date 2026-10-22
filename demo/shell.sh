#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Sourced (hidden) at the start of every tape. Same CLIs a user gets from
# `uds`: kubectl and yq are the copies Zarf vendors.
# shellcheck disable=SC2139
alias kubectl='uds zarf tools kubectl'
alias yq='uds zarf tools yq'
export PS1='\[\e[38;5;141m\]uds-k3d-takserver\[\e[0m\] \[\e[38;5;245m\]$\[\e[0m\] '
export KUBECTL_EXTERNAL_DIFF=""
export TERM=xterm-256color
# The release workflow's keyless signing identity (README, "Verify a release").
export RELEASE_WORKFLOW='^https://github\.com/jonathanagustin/uds-k3d-takserver/\.github/workflows/release\.yaml@refs/(tags/v[0-9]+\.[0-9]+\.[0-9]+|heads/main)$'
export RELEASE_ISSUER=https://token.actions.githubusercontent.com
