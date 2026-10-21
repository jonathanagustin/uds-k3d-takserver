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
