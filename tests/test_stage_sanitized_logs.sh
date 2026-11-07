#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The staging script is what CI uploads. A failed or partial sanitize must
# not leave a directory that --check accepts.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
stage="${root}/.github/scripts/stage-sanitized-logs.sh"
sentinel="stage-sentinel-value"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

fails=0
ok() { echo "ok: $1"; }
bad() { echo "not ok: $1" >&2; fails=$((fails + 1)); }

src="${work}/src"
mkdir -p "${src}"
printf 'secret="%s"\n' "${sentinel}" > "${src}/api.log"
dest="${work}/staged"
if "${stage}" "${dest}" "${src}/api.log"; then
  copied="$(find "${dest}/payload" -type f -name api.log -print -quit)"
  if "${stage}" --check "${dest}" \
    && [[ -n "${copied}" ]] \
    && ! grep -q "${sentinel}" "${copied}" \
    && grep -q 'secret="\[REDACTED\]"' "${copied}"; then
    ok "clean log is staged and the value is gone"
  else
    bad "clean log was not staged safely"
  fi
else
  bad "clean log staging failed"
fi

nul="${work}/nul.log"
printf 'secret="%s"\n' "${sentinel}" > "${nul}"
printf '\0' >> "${nul}"
dirty="${work}/dirty"
if "${stage}" "${dirty}" "${nul}"; then
  bad "NUL log staging exited 0"
else
  if [[ -e "${dirty}" ]]; then
    bad "failed staging left ${dirty}"
  elif "${stage}" --check "${dirty}" 2>/dev/null; then
    bad "missing staging directory passed --check"
  else
    ok "NUL log removes the staging directory and --check fails"
  fi
fi

partial="${work}/partial"
mkdir -p "${partial}/payload"
printf 'secret="%s"\n' "${sentinel}" > "${partial}/payload/late.log"
if "${stage}" --check "${partial}"; then
  bad "staging without a marker passed --check"
else
  ok "staging without a marker is not uploadable"
fi

marked="${work}/marked"
mkdir -p "${marked}/payload"
printf 'plain\n' > "${marked}/payload/a.log"
printf 'sanitized\n' > "${marked}/SANITIZED"
sleep 1
printf 'secret="%s"\n' "${sentinel}" > "${marked}/payload/late.log"
if "${stage}" --check "${marked}"; then
  bad "a file newer than the marker passed --check"
else
  ok "a file written after the marker is not uploadable"
fi

outside="${work}/outside"
mkdir -p "${outside}"
printf 'secret="%s"\n' "${sentinel}" > "${outside}/hid.log"
ln -s "${outside}/hid.log" "${work}/link.log"
linked="${work}/linked-stage"
if "${stage}" "${linked}" "${work}/link.log"; then
  bad "file symlink staging exited 0"
else
  if [[ -e "${linked}" ]]; then
    bad "file symlink staging left ${linked}"
  elif [[ "$(cat "${outside}/hid.log")" != "secret=\"${sentinel}\"" ]]; then
    bad "file symlink staging modified the outside target"
  else
    ok "file symlink is refused and the outside target is unchanged"
  fi
fi

tree="${work}/tree"
mkdir -p "${tree}"
ln -s "${outside}" "${tree}/via"
dirlink="${work}/dirlink-stage"
if "${stage}" "${dirlink}" "${tree}"; then
  bad "directory symlink staging exited 0"
else
  if [[ -e "${dirlink}" ]]; then
    bad "directory symlink staging left ${dirlink}"
  elif [[ "$(cat "${outside}/hid.log")" != "secret=\"${sentinel}\"" ]]; then
    bad "directory symlink staging modified the outside target"
  else
    ok "directory symlink is refused and the outside target is unchanged"
  fi
fi

printf 'secret="%s"\n' "${sentinel}" | gzip > "${work}/api.log.gz"
archived="${work}/archive-stage"
if "${stage}" "${archived}" "${work}/api.log.gz"; then
  bad "gzip staging exited 0"
else
  if [[ -e "${archived}" ]]; then
    bad "gzip staging left ${archived}"
  elif ! gzip -dc "${work}/api.log.gz" | grep -q "${sentinel}"; then
    bad "gzip staging modified the source archive"
  else
    ok "gzip archive is not staged"
  fi
fi

printf 'not-a-png' > "${work}/shot.png"
binary="${work}/binary-stage"
if "${stage}" "${binary}" "${work}/shot.png"; then
  bad "png staging exited 0"
else
  if [[ -e "${binary}" ]]; then
    bad "png staging left ${binary}"
  else
    ok "png is not staged as a sanitized log"
  fi
fi

marked_link="${work}/marked-link"
mkdir -p "${marked_link}/payload"
printf 'plain\n' > "${marked_link}/payload/a.log"
printf 'sanitized\n' > "${marked_link}/SANITIZED"
ln -s "${outside}/hid.log" "${marked_link}/payload/leak.log"
if "${stage}" --check "${marked_link}"; then
  bad "a symlink passed --check"
else
  ok "a symlink does not pass --check"
fi

marked_gz="${work}/marked-gz"
mkdir -p "${marked_gz}/payload"
printf 'sanitized\n' > "${marked_gz}/SANITIZED"
cp "${work}/api.log.gz" "${marked_gz}/payload/api.log.gz"
if "${stage}" --check "${marked_gz}"; then
  bad "a gzip file passed --check"
else
  ok "a gzip file does not pass --check"
fi

mkdir -p "${work}/fifodir"
mkfifo "${work}/fifodir/pipe.log"
fifo_stage="${work}/fifo-stage"
set +e
timeout 5 "${stage}" "${fifo_stage}" "${work}/fifodir" >/tmp/fifo-stage.out 2>&1
fifo_code=$?
set -e
if [[ "${fifo_code}" -eq 124 ]]; then
  bad "fifo staging blocked on a read"
elif [[ "${fifo_code}" -eq 0 || -e "${fifo_stage}" ]]; then
  bad "fifo staging succeeded or left ${fifo_stage}"
elif [[ -p "${work}/fifodir/pipe.log" ]]; then
  ok "fifo is refused and was not opened"
else
  bad "fifo staging removed the source fifo"
fi

marked_fifo="${work}/marked-fifo"
mkdir -p "${marked_fifo}/payload"
printf 'sanitized\n' > "${marked_fifo}/SANITIZED"
mkfifo "${marked_fifo}/payload/pipe.log"
set +e
timeout 5 "${stage}" --check "${marked_fifo}" >/dev/null 2>&1
check_code=$?
set -e
if [[ "${check_code}" -eq 124 ]]; then
  bad "--check blocked on a fifo"
elif [[ "${check_code}" -eq 0 ]]; then
  bad "a fifo passed --check"
else
  ok "a fifo does not pass --check"
fi

python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1])' "${work}/node.sock"
sock_stage="${work}/sock-stage"
if "${stage}" "${sock_stage}" "${work}/node.sock"; then
  bad "socket staging exited 0"
elif [[ -e "${sock_stage}" ]]; then
  bad "socket staging left ${sock_stage}"
elif [[ -S "${work}/node.sock" ]]; then
  ok "socket is refused and was not opened"
else
  bad "socket staging removed the source socket"
fi

if (( fails > 0 )); then
  echo "${fails} case(s) failed" >&2
  exit 1
fi
