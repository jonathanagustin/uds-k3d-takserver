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
# These names are created at the checkout root, which is the workflow cwd.
# Remove them even when a later assertion fails. Refuse to clobber a
# pre-existing directory.
checkout_out="${root}/out"
checkout_bad="${root}/out-bad"
abs_log=""
if [[ -e "${checkout_out}" || -e "${checkout_bad}" ]]; then
  echo "checkout out/ already exists; refusing to reuse it" >&2
  exit 1
fi
trap 'rm -rf "${work}" "${checkout_out}" "${checkout_bad}" ${abs_log:+"${abs_log}"}' EXIT

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

# kubelet container aliases. docker cp of /var/log keeps
# containers/<pod>_<namespace>_<container>-<id>.log -> ../pods/.../<n>.log
# The pods file is the log. The alias must not be uploaded as a symlink.
kroot="${work}/k8s-log"
poddir="${kroot}/pods/cloudtak_cloudtak-78468f484c-kpr9j_uid/sso"
mkdir -p "${poddir}" "${kroot}/containers"
printf 'secret="%s"\n' "${sentinel}" > "${poddir}/0.log"
ln -s "../pods/cloudtak_cloudtak-78468f484c-kpr9j_uid/sso/0.log" \
  "${kroot}/containers/cloudtak-78468f484c-kpr9j_cloudtak_sso-hash.log"
kdest="${work}/k8s-stage"
if "${stage}" "${kdest}" "${kroot}"; then
  copied="$(find "${kdest}/payload" -type f -name 0.log -print -quit)"
  aliases="$(find -P "${kdest}/payload" -path '*/containers/*' -print)"
  if "${stage}" --check "${kdest}" \
    && [[ -n "${copied}" && ! -L "${copied}" ]] \
    && [[ -z "${aliases}" ]] \
    && ! find -P "${kdest}/payload" \( ! -type d ! -type f \) -print -quit | grep -q . \
    && ! grep -q "${sentinel}" "${copied}" \
    && grep -q 'secret="\[REDACTED\]"' "${copied}"; then
    ok "container alias is omitted and the pods log is redacted"
  else
    bad "container alias was not staged as the pods log"
  fi
else
  bad "container alias staging failed"
fi

# A link that is not the containers -> pods alias still fails closed,
# including one that stays inside the tree.
inside="${work}/inside-link"
mkdir -p "${inside}/pods/ns_pod_uid/c" "${inside}/other"
printf 'secret="%s"\n' "${sentinel}" > "${inside}/pods/ns_pod_uid/c/0.log"
ln -s "../pods/ns_pod_uid/c/0.log" "${inside}/other/alias.log"
inside_dest="${work}/inside-stage"
if "${stage}" "${inside_dest}" "${inside}"; then
  bad "non-alias internal symlink staging exited 0"
elif [[ -e "${inside_dest}" ]]; then
  bad "non-alias internal symlink staging left ${inside_dest}"
else
  ok "a symlink outside containers/ is refused"
fi

# containers/*.log is not a blanket exception. The target has to be the pods file.
notpods="${work}/notpods"
mkdir -p "${notpods}/pods/ns_pod_uid/c" "${notpods}/elsewhere" "${notpods}/containers"
printf 'secret="%s"\n' "${sentinel}" > "${notpods}/pods/ns_pod_uid/c/0.log"
printf 'secret="%s"\n' "${sentinel}" > "${notpods}/elsewhere/note.log"
ln -s "../elsewhere/note.log" "${notpods}/containers/note.log"
notpods_dest="${work}/notpods-stage"
if "${stage}" "${notpods_dest}" "${notpods}"; then
  bad "containers link outside pods staging exited 0"
elif [[ -e "${notpods_dest}" ]]; then
  bad "containers link outside pods staging left ${notpods_dest}"
else
  ok "a containers link is refused unless it names a pods file"
fi

dangling="${work}/dangling"
mkdir -p "${dangling}/pods/ns_pod_uid/c" "${dangling}/containers"
printf 'secret="%s"\n' "${sentinel}" > "${dangling}/pods/ns_pod_uid/c/0.log"
ln -s "../pods/ns_pod_uid/c/missing.log" "${dangling}/containers/missing.log"
dangling_dest="${work}/dangling-stage"
if "${stage}" "${dangling_dest}" "${dangling}"; then
  bad "dangling container alias staging exited 0"
elif [[ -e "${dangling_dest}" ]]; then
  bad "dangling container alias staging left ${dangling_dest}"
else
  ok "a dangling container alias is refused"
fi

external="${work}/external"
mkdir -p "${external}/pods/ns_pod_uid/c" "${external}/containers"
printf 'kept\n' > "${external}/pods/ns_pod_uid/c/0.log"
ln -s "${outside}/hid.log" "${external}/containers/evil.log"
external_dest="${work}/external-stage"
if "${stage}" "${external_dest}" "${external}"; then
  bad "external container symlink staging exited 0"
elif [[ -e "${external_dest}" ]]; then
  bad "external container symlink staging left ${external_dest}"
elif [[ "$(cat "${outside}/hid.log")" != "secret=\"${sentinel}\"" ]]; then
  bad "external container symlink modified the outside target"
else
  ok "an external container symlink is refused and the target is unchanged"
fi

# pods/ itself is a symlink, so the alias would leave the tree.
escaped="${work}/escaped"
mkdir -p "${escaped}/containers" "${outside}/via/ns/c"
printf 'secret="%s"\n' "${sentinel}" > "${outside}/via/ns/c/0.log"
ln -s "${outside}/via" "${escaped}/pods"
ln -s "../pods/ns/c/0.log" "${escaped}/containers/via.log"
escaped_dest="${work}/escaped-stage"
if "${stage}" "${escaped_dest}" "${escaped}"; then
  bad "pods symlink staging exited 0"
elif [[ -e "${escaped_dest}" ]]; then
  bad "pods symlink staging left ${escaped_dest}"
elif [[ "$(cat "${outside}/via/ns/c/0.log")" != "secret=\"${sentinel}\"" ]]; then
  bad "pods symlink staging modified the outside target"
else
  ok "a pods symlink is not followed"
fi

mkfifo "${outside}/pipe.log"
held="${work}/held"
mkdir -p "${held}/pods/ns_pod_uid/c" "${held}/containers"
printf 'kept\n' > "${held}/pods/ns_pod_uid/c/0.log"
ln -s "${outside}/pipe.log" "${held}/containers/held.log"
held_dest="${work}/held-stage"
set +e
timeout 5 "${stage}" "${held_dest}" "${held}" >/tmp/held-stage.out 2>&1
held_code=$?
set -e
if [[ "${held_code}" -eq 124 ]]; then
  bad "external fifo symlink was opened"
elif [[ "${held_code}" -eq 0 || -e "${held_dest}" ]]; then
  bad "external fifo symlink staging succeeded or left ${held_dest}"
elif [[ -p "${outside}/pipe.log" ]]; then
  ok "an external fifo symlink is refused and was not opened"
else
  bad "external fifo symlink staging removed the fifo"
fi

# The workflow step sets no working-directory, so cwd is the checkout, and
# it runs ./.github/scripts/stage-sanitized-logs.sh. A relative directory
# must stay payload/<that-name>, not payload/<absolute-checkout>/<name>.
# Kubelet 1.32 stores the alias text as the absolute CRI path
# filepath.Join(LogDirectory, LogPath), which is /var/log/pods/... .
rel_dest="${work}/rel-stage"
if (
  cd "${root}"
  mkdir -p out/pods/ns_pod_uid/c out/containers
  printf 'secret="%s"\n' "${sentinel}" > out/pods/ns_pod_uid/c/0.log
  ln -s "../pods/ns_pod_uid/c/0.log" out/containers/relative.log
  ln -s "/var/log/pods/ns_pod_uid/c/0.log" out/containers/absolute.log
  ./.github/scripts/stage-sanitized-logs.sh "${rel_dest}" out
); then
  copied="${rel_dest}/payload/out/pods/ns_pod_uid/c/0.log"
  if [[ -f "${copied}" && ! -L "${copied}" ]] \
    && [[ ! -e "${rel_dest}/payload${root}" ]] \
    && [[ -z "$(find -P "${rel_dest}/payload" \( ! -type d ! -type f \) -print -quit)" ]] \
    && ! grep -q "${sentinel}" "${copied}" \
    && grep -q 'secret="\[REDACTED\]"' "${copied}"; then
    ok "relative out keeps payload/out and both alias forms redact the pods log"
  else
    bad "relative out landed at $(find "${rel_dest}/payload" -type f -print | head -n 5)"
  fi
else
  bad "relative out staging failed"
fi
rm -rf "${checkout_out}"

# Same cwd and invocation as the workflow, with an absolute /tmp source.
# The upload step reads payload/tmp, so the absolute path must be preserved.
abs_log="$(mktemp -d /tmp/uds-containerd-logs.XXXXXX)"
mkdir -p "${abs_log}/pods/ns_pod_uid/c" "${abs_log}/containers"
printf 'secret="%s"\n' "${sentinel}" > "${abs_log}/pods/ns_pod_uid/c/0.log"
ln -s "/var/log/pods/ns_pod_uid/c/0.log" "${abs_log}/containers/cloudtak.log"
abs_dest="${work}/abs-stage"
if (
  cd "${root}"
  ./.github/scripts/stage-sanitized-logs.sh "${abs_dest}" "${abs_log}"
); then
  copied="${abs_dest}/payload${abs_log}/pods/ns_pod_uid/c/0.log"
  if [[ -f "${copied}" && ! -L "${copied}" ]] \
    && [[ "${copied}" == "${abs_dest}/payload/tmp/"* ]] \
    && [[ -z "$(find -P "${abs_dest}/payload" \( ! -type d ! -type f \) -print -quit)" ]] \
    && ! grep -q "${sentinel}" "${copied}" \
    && grep -q 'secret="\[REDACTED\]"' "${copied}"; then
    ok "absolute /tmp source stays under payload/tmp and the kubelet alias is redacted"
  else
    bad "absolute source was not staged at payload${abs_log}"
  fi
else
  bad "absolute /tmp source staging failed"
fi

# An absolute alias that is not /var/log/pods must not be opened.
abs_bad="${work}/abs-bad"
mkdir -p "${abs_bad}/pods/ns_pod_uid/c" "${abs_bad}/containers"
printf 'kept\n' > "${abs_bad}/pods/ns_pod_uid/c/0.log"
ln -s "/etc/passwd" "${abs_bad}/containers/host.log"
abs_bad_dest="${work}/abs-bad-stage"
if "${stage}" "${abs_bad_dest}" "${abs_bad}"; then
  bad "absolute host symlink staging exited 0"
elif [[ -e "${abs_bad_dest}" ]]; then
  bad "absolute host symlink staging left ${abs_bad_dest}"
elif [[ ! -f /etc/passwd ]]; then
  bad "absolute host symlink removed /etc/passwd"
else
  ok "an absolute host path is refused and was not used as the log"
fi

# /var/log/pods/../../.. escapes after the prefix rewrite. It must not open
# the fifo that the escaped path names.
fifo_abs="$(readlink -f "${outside}/pipe.log")"
escape_text="/var/log/pods/../../../${fifo_abs#/}"
escape_tree="${work}/escape-abs"
mkdir -p "${escape_tree}/pods/ns_pod_uid/c" "${escape_tree}/containers"
printf 'kept\n' > "${escape_tree}/pods/ns_pod_uid/c/0.log"
ln -s "${escape_text}" "${escape_tree}/containers/escape.log"
escape_dest="${work}/escape-abs-stage"
set +e
timeout 5 "${stage}" "${escape_dest}" "${escape_tree}" >/tmp/escape-abs.out 2>&1
escape_code=$?
set -e
if [[ "${escape_code}" -eq 124 ]]; then
  bad "absolute /var/log/pods escape opened the fifo"
elif [[ "${escape_code}" -eq 0 || -e "${escape_dest}" ]]; then
  bad "absolute /var/log/pods escape staging succeeded or left ${escape_dest}"
elif [[ -p "${outside}/pipe.log" ]]; then
  ok "an absolute /var/log/pods path that leaves the tree is refused"
else
  bad "absolute /var/log/pods escape removed the fifo"
fi

if (( fails > 0 )); then
  echo "${fails} case(s) failed" >&2
  exit 1
fi
