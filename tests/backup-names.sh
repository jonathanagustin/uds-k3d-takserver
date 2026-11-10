#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# shellcheck disable=SC2034,SC2154
# Sourced after the existing run/attempt normalization. Empty keeps ordinary CI
# names unchanged. Staged trials never alter the GitHub run identity.
case "${BACKUP_TRIAL_SUFFIX:-}" in
  "" | fresh | core | local) ;;
  *) printf '%s\n' 'invalid BACKUP_TRIAL_SUFFIX' >&2; return 1 ;;
esac
note="run-${run_id}-${attempt}${BACKUP_TRIAL_SUFFIX:+-${BACKUP_TRIAL_SUFFIX}}"
backup_name="tak-ci-${run_id}-${attempt}${BACKUP_TRIAL_SUFFIX:+-${BACKUP_TRIAL_SUFFIX}}"
restore_name="${backup_name}-r"
