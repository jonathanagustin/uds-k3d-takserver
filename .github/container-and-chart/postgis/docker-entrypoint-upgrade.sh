#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Upgrade a PostgreSQL 15 data directory to 18, then start the server the way
# the official image does. A new directory is left for that entrypoint.
#
# pg_upgrade --link keeps the upgrade on the same volume. The old directory is
# removed after the new server has been started, so it is not a rollback copy.
# Take a volume snapshot before rolling this image onto an existing database.
set -euo pipefail

old_major=15
new_major=18
old_bindir="/usr/lib/postgresql/${old_major}/bin"
new_bindir="/usr/lib/postgresql/${new_major}/bin"
socket_dir=/tmp

# A flag means "run postgres", matching docker-entrypoint.sh.
if [[ "${1:-}" == -* ]]; then
  set -- postgres "$@"
fi

if [[ "${1:-}" != "postgres" ]]; then
  exec docker-entrypoint.sh "$@"
fi

pgdata="${PGDATA:-/var/lib/postgresql/data}"
old_data="${pgdata}.pg${old_major}"
db_user="${POSTGRES_USER:-postgres}"

log() { printf '%s\n' "$*" >&2; }

ensure_passwd() {
  if getent passwd "$(id -u)" >/dev/null; then
    return 0
  fi
  local wrapper
  local candidates=()
  shopt -s nullglob
  candidates=(/usr/lib/*/libnss_wrapper.so /lib/*/libnss_wrapper.so)
  shopt -u nullglob
  if [[ ${#candidates[@]} -eq 0 ]]; then
    log "uid $(id -u) is not in /etc/passwd and libnss_wrapper is not installed"
    exit 1
  fi
  wrapper="${candidates[0]}"
  NSS_WRAPPER_PASSWD="$(mktemp)"
  NSS_WRAPPER_GROUP="$(mktemp)"
  export LD_PRELOAD="${wrapper}" NSS_WRAPPER_PASSWD NSS_WRAPPER_GROUP
  printf 'postgres:x:%s:%s:PostgreSQL:%s:/bin/false\n' "$(id -u)" "$(id -g)" "${pgdata}" > "${NSS_WRAPPER_PASSWD}"
  printf 'postgres:x:%s:\n' "$(id -g)" > "${NSS_WRAPPER_GROUP}"
}

clear_passwd() {
  if [[ -n "${NSS_WRAPPER_PASSWD:-}" ]]; then
    rm -f "${NSS_WRAPPER_PASSWD}" "${NSS_WRAPPER_GROUP}"
    unset LD_PRELOAD NSS_WRAPPER_PASSWD NSS_WRAPPER_GROUP
  fi
}

server_version() {
  local dir="$1"
  if [[ -s "${dir}/PG_VERSION" ]]; then
    tr -d '[:space:]' < "${dir}/PG_VERSION"
  fi
}

# A previous attempt moved the data aside and did not finish. Put it back
# when the new directory is not a PostgreSQL 18 cluster yet.
if [[ -d "${old_data}" && "$(server_version "${pgdata}")" != "${new_major}" ]]; then
  log "found an unfinished upgrade at ${old_data}; moving it back"
  rm -rf "${pgdata}"
  mv "${old_data}" "${pgdata}"
fi

current="$(server_version "${pgdata}")"
if [[ "${current}" == "${old_major}" ]]; then
  if [[ "$(id -u)" -eq 0 ]]; then
    log "refusing to upgrade ${pgdata} as root; the container has to run as the user that owns the data directory"
    exit 1
  fi
  if [[ -e "${old_data}" ]]; then
    log "refusing to upgrade: ${old_data} already exists"
    exit 1
  fi
  ensure_passwd
  rm -f "${pgdata}/postmaster.pid"
  log "reading locale from the PostgreSQL ${old_major} cluster in ${pgdata}"
  "${old_bindir}/pg_ctl" -D "${pgdata}" -w -o "-c listen_addresses= -c unix_socket_directories=${socket_dir}" start
  if ! locale_row="$("${old_bindir}/psql" -h "${socket_dir}" -U "${db_user}" -d postgres -At -v ON_ERROR_STOP=1 \
    -c "SELECT datcollate || '|' || datctype || '|' || pg_encoding_to_char(encoding) || '|' || datlocprovider::text FROM pg_database WHERE datname = 'template0';")"; then
    "${old_bindir}/pg_ctl" -D "${pgdata}" -w -m fast stop || true
    exit 1
  fi
  "${old_bindir}/pg_ctl" -D "${pgdata}" -w -m fast stop
  checksum="$("${old_bindir}/pg_controldata" "${pgdata}" | sed -n 's/^Data page checksum version:[[:space:]]*//p')"
  checksum="${checksum//[[:space:]]/}"
  IFS='|' read -r collate ctype encoding provider <<< "${locale_row}"
  if [[ -z "${collate}" || -z "${ctype}" || -z "${encoding}" || -z "${provider}" ]]; then
    log "could not read the cluster locale (${locale_row:-empty})"
    exit 1
  fi
  case "${provider}" in
    c) locale_provider=libc ;;
    i) locale_provider=icu ;;
    *)
      log "unsupported locale provider '${provider}'"
      exit 1
      ;;
  esac

  log "upgrading PostgreSQL ${old_major} in ${pgdata} to ${new_major} (locale ${collate}, ${locale_provider})"
  mv "${pgdata}" "${old_data}"
  mkdir -p "${pgdata}"
  chmod 700 "${pgdata}"
  init_args=(
    --username="${db_user}"
    --auth-local=trust
    --locale-provider="${locale_provider}"
    --locale="${collate}"
    --lc-collate="${collate}"
    --lc-ctype="${ctype}"
    --encoding="${encoding}"
    -D "${pgdata}"
  )
  if [[ "${locale_provider}" == "icu" ]]; then
    init_args+=(--icu-locale="${collate}")
  fi
  if [[ -n "${POSTGRES_PASSWORD:-}" ]]; then
    pwfile="$(mktemp)"
    printf '%s\n' "${POSTGRES_PASSWORD}" > "${pwfile}"
    init_args+=(--pwfile="${pwfile}" --auth-host=scram-sha-256)
  else
    init_args+=(--auth-host=trust)
  fi
  # PostgreSQL 18 turns checksums on. pg_upgrade refuses a mismatch.
  if [[ "${checksum}" == "0" ]]; then
    init_args+=(--no-data-checksums)
  else
    init_args+=(--data-checksums)
  fi
  "${new_bindir}/initdb" "${init_args[@]}"
  rm -f "${pwfile:-}"

  cd /tmp
  if ! "${new_bindir}/pg_upgrade" \
    --old-bindir="${old_bindir}" \
    --new-bindir="${new_bindir}" \
    --old-datadir="${old_data}" \
    --new-datadir="${pgdata}" \
    --username="${db_user}" \
    --link \
    --socketdir="${socket_dir}"; then
    log "pg_upgrade failed; putting the PostgreSQL ${old_major} data directory back"
    if [[ -d /tmp/pg_upgrade_output.d ]]; then
      find /tmp/pg_upgrade_output.d -type f -print -exec cat {} \; >&2 || true
    fi
    rm -rf "${pgdata}"
    mv "${old_data}" "${pgdata}"
    exit 1
  fi

  log "updating PostGIS extensions"
  "${new_bindir}/pg_ctl" -D "${pgdata}" -w -o "-c listen_addresses= -c unix_socket_directories=${socket_dir}" start
  mapfile -t databases < <("${new_bindir}/psql" -h "${socket_dir}" -U "${db_user}" -d postgres -At -v ON_ERROR_STOP=1 \
    -c "SELECT datname FROM pg_database WHERE datallowconn;")
  for database in "${databases[@]}"; do
    has="$("${new_bindir}/psql" -h "${socket_dir}" -U "${db_user}" -d "${database}" -At -v ON_ERROR_STOP=1 \
      -c "SELECT 1 FROM pg_extension WHERE extname = 'postgis';")"
    if [[ "${has}" == "1" ]]; then
      "${new_bindir}/psql" -h "${socket_dir}" -U "${db_user}" -d "${database}" -v ON_ERROR_STOP=1 \
        -c "SELECT postgis_extensions_upgrade();"
    fi
  done
  if [[ -f /tmp/analyze_new_cluster.sh ]]; then
    # pg_upgrade leaves this next to the directory it was run from. The 18
    # client has to win over /usr/bin, which is the pg_wrapper.
    PATH="${new_bindir}:${PATH}" /tmp/analyze_new_cluster.sh
  fi
  "${new_bindir}/pg_ctl" -D "${pgdata}" -w -m fast stop
  rm -rf "${old_data}"
  log "PostgreSQL ${new_major} data directory is ready"
  clear_passwd
elif [[ -n "${current}" && "${current}" != "${new_major}" ]]; then
  log "refusing to start PostgreSQL ${current} data in ${pgdata}; this image upgrades ${old_major} to ${new_major}"
  exit 1
fi

exec docker-entrypoint.sh "$@"
