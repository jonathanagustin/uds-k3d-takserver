#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Free the preinstalled toolchains a TAK test never runs.
# On the measured runner this was most of the space: dotnet, Android, GHC,
# and CodeQL. The install job later ran out of disk inside the k3d node (93%
# of 71.6 GiB used, image pulls failing), so this also drops more toolchains
# and the preinstalled Docker images.
#
# `trim-runner.sh start` deletes the toolchains in the background.
# `trim-runner.sh finish` (the default) waits for that, then prunes images.
# A workflow that only calls finish still does both, in this process.
# On run 39686333898 the amd64 deletes took 244s and Android alone took 136s,
# so the toolchain deletes run together and the step waits on the slowest one.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ]] && [[ "${CI:-}" != "true" ]]; then
  echo "Not a CI runner; leaving the disk alone."
  exit 0
fi

mode="${1:-finish}"
mkdir -p "${RUNNER_TEMP:-/tmp}"
pid_file="${RUNNER_TEMP:-/tmp}/trim-runner.pid"
log_file="${RUNNER_TEMP:-/tmp}/trim-runner.log"
status_file="${RUNNER_TEMP:-/tmp}/trim-runner.status"

# TRIM_SKIP_ABOVE_GB: leave the disk alone when at least this many GB are
# already free. The deletes cost minutes on a slow runner, and a test job
# uses about 30 GB (measured in the Test workflow). Unset, the trim always runs.
skip_if_room() {
  if [[ -z "${TRIM_SKIP_ABOVE_GB:-}" ]]; then
    return 1
  fi
  avail_gb="$(df --output=avail -BG / | tail -n 1 | tr -dc '0-9')"
  if ((avail_gb >= TRIM_SKIP_ABOVE_GB)); then
    echo "trim: ${avail_gb} GB free, at least ${TRIM_SKIP_ABOVE_GB} GB; skipping the deletes."
    df -h /
    return 0
  fi
  return 1
}

used_kb() { df --output=used -k / | tail -n 1 | tr -d ' '; }

toolchain_paths=(
  /usr/share/dotnet
  /usr/local/lib/android
  /opt/ghc
  /opt/hostedtoolcache/CodeQL
  /usr/local/share/boost
  /usr/share/swift
  /usr/local/.ghcup
  /usr/local/julia*
  /usr/share/miniconda
  /opt/az
  /usr/local/share/powershell
)

delete_toolchains() {
  local start_all start_used tmp i path pid failed line
  local -a pids
  start_all="${SECONDS}"
  start_used="$(used_kb)"
  df -h /
  tmp="$(mktemp -d)"
  i=0
  pids=()
  for path in "${toolchain_paths[@]}"; do
    (
      started="$(date +%s)"
      # The julia entry is a glob, so leave it unquoted. Size is du of that
      # tree, not a df delta, because the deletes run at the same time.
      # shellcheck disable=SC2206,SC2086
      matches=(${path})
      size_mb=0
      if ((${#matches[@]} > 0)); then
        # shellcheck disable=SC2086
        size_mb="$(sudo du -sm ${path} 2>/dev/null | awk '{s+=$1} END {printf "%d", s+0}')" || size_mb=0
      fi
      # shellcheck disable=SC2086
      sudo rm -rf ${path}
      printf 'trim: %-34s %4ss %6s MB freed\n' "${path}" "$(( $(date +%s) - started ))" "${size_mb}" \
        > "${tmp}/$(printf '%02d' "${i}")"
    ) &
    pids+=("$!")
    i=$((i + 1))
  done
  failed=0
  for pid in "${pids[@]}"; do
    wait "${pid}" || failed=1
  done
  for line in "${tmp}"/*; do
    [[ -f "${line}" ]] || continue
    cat "${line}"
  done
  rm -rf "${tmp}"
  df -h /
  printf 'trim: toolchains %ss, %s MB freed\n' "$((SECONDS - start_all))" "$(((start_used - $(used_kb)) / 1024))"
  printf '%s\n' "${failed}" > "${status_file}"
  return "${failed}"
}

wait_for_start() {
  if [[ ! -f "${pid_file}" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "${pid_file}")"
  echo "trim: waiting for toolchain deletes (pid ${pid})"
  while kill -0 "${pid}" 2>/dev/null; do
    sleep 2
  done
  if [[ -f "${log_file}" ]]; then
    cat "${log_file}"
  fi
  local status=1
  if [[ -f "${status_file}" ]]; then
    status="$(cat "${status_file}")"
  fi
  rm -f "${pid_file}"
  if [[ "${status}" != "0" ]]; then
    echo "trim: toolchain deletes failed" >&2
    exit 1
  fi
}

prune_images() {
  if skip_if_room; then
    return 0
  fi
  if ! command -v docker >/dev/null 2>&1; then
    df -h /
    return 0
  fi
  local before started
  before="$(used_kb)"
  started="${SECONDS}"
  sudo docker image prune --all --force || true
  printf 'trim: %-34s %4ss %6s MB freed\n' "docker image prune" "$((SECONDS - started))" "$(((before - $(used_kb)) / 1024))"
  df -h /
}

case "${mode}" in
  start)
    if skip_if_room; then
      printf '0\n' > "${status_file}"
      exit 0
    fi
    if [[ -f "${pid_file}" ]] && kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
      echo "trim: toolchain deletes already running"
      exit 0
    fi
    rm -f "${status_file}"
    nohup "$0" toolchains > "${log_file}" 2>&1 &
    echo "$!" > "${pid_file}"
    echo "trim: toolchain deletes started (pid $!)"
    ;;
  toolchains)
    delete_toolchains
    ;;
  finish)
    wait_for_start
    if skip_if_room; then
      exit 0
    fi
    if [[ ! -f "${status_file}" ]]; then
      delete_toolchains
    fi
    prune_images
    ;;
  *)
    echo "trim-runner.sh: use start, toolchains, or finish" >&2
    exit 1
    ;;
esac
