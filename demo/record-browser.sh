#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Record a Playwright walkthrough in a real, headed Google Chrome window:
# its tab strip, address bar, and padlock are in the video. Chrome runs on
# an Xvfb display the size of the content area and ffmpeg captures that
# display with x11grab.
#
# usage: demo/record-browser.sh NAME SPEC
#   NAME  writes demo/out/NAME.mp4 and demo/out/NAME-events.json
#   SPEC  walkthrough under tests/demo, for example tour.demo.ts
#
# Environment:
#   DEMO_HOSTS      hosts the walkthrough opens. Each must pass TLS
#                   verification (system CAs plus DEMO_TRUST_CAS) first.
#   DEMO_TRUST_CAS  PEM files of CA certificates for this Chrome to trust.
#                   They go into the NSS store of a HOME used only for the
#                   recording. Chrome never runs with certificate errors
#                   ignored.
#   DEMO_DISPLAY    X display number, default 99.
#
# The walkthrough's start() mark carries its wall-clock time. ffmpeg logs
# the wall-clock time of its first frame. The capture is trimmed so the
# video and the events share time zero.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
name="$1"
spec="$2"
width=1280
height=630
fps=24
display=":${DEMO_DISPLAY:-99}"
out="$(pwd)/demo/out"
work="${out}/browser-${name}"
rm -rf "${work}"
mkdir -p "${work}/home" "${work}/profile"

# Trust: one NSS database for this recording's HOME.
nssdb="${work}/home/.pki/nssdb"
mkdir -p "${nssdb}"
certutil -d "sql:${nssdb}" -N --empty-password
bundle="${work}/ca-bundle.pem"
cat /etc/ssl/certs/ca-certificates.crt > "${bundle}"
for file in ${DEMO_TRUST_CAS:-}; do
  rm -f "${work}"/ca-part-*.pem
  awk -v prefix="${work}/ca-part-" '/-----BEGIN CERTIFICATE-----/ { n++ } n { print > (prefix n ".pem") }' "${file}"
  for part in "${work}"/ca-part-*.pem; do
    nick="$(openssl x509 -in "${part}" -noout -subject -nameopt multiline | sed -n 's/^ *commonName *= *//p')"
    certutil -d "sql:${nssdb}" -A -t "C,," -n "${nick:-$(basename "${part}")}" -i "${part}"
    cat "${part}" >> "${bundle}"
  done
done
rm -f "${work}"/ca-part-*.pem
echo "CAs trusted in the recording's NSS store:"
certutil -d "sql:${nssdb}" -L

for host in ${DEMO_HOSTS:-}; do
  if ! result="$(openssl s_client -connect "${host}:443" -servername "${host}" -verify_hostname "${host}" \
    -CAfile "${bundle}" -verify_return_error < /dev/null 2>&1)"; then
    echo "${result}" | tail -n 20 >&2
    echo "${host}: the certificate does not verify, so Chrome would not show a padlock." >&2
    exit 1
  fi
  echo "${host}: $(grep -m1 'Verify return code' <<< "${result}")"
  grep '^depth=' <<< "${result}" | sed 's/^/  /'
done

Xvfb "${display}" -screen 0 "${width}x${height}x24" -nolisten tcp > "${work}/xvfb.log" 2>&1 &
xvfb=$!
ffmpeg_pid=""
# shellcheck disable=SC2317,SC2329 # runs from the EXIT trap
cleanup() {
  if [ -n "${ffmpeg_pid}" ] && kill -0 "${ffmpeg_pid}" 2> /dev/null; then
    kill -INT "${ffmpeg_pid}"
    wait "${ffmpeg_pid}" || true
  fi
  kill "${xvfb}" 2> /dev/null || true
}
trap cleanup EXIT
for _ in $(seq 50); do
  if [ -S "/tmp/.X11-unix/X${display#:}" ]; then
    break
  fi
  sleep 0.1
done

# -draw_mouse 0: Playwright drives the page over CDP, so the X pointer sits
# still. The walkthrough draws its own cursor in the page.
ffmpeg -nostdin -y -f x11grab -draw_mouse 0 -framerate "${fps}" -video_size "${width}x${height}" -i "${display}" \
  -c:v libx264 -preset veryfast -crf 14 -pix_fmt yuv420p "${work}/screen.mkv" > "${work}/ffmpeg.log" 2>&1 &
ffmpeg_pid=$!
for _ in $(seq 100); do
  if grep -q 'start: [0-9]' "${work}/ffmpeg.log"; then
    break
  fi
  sleep 0.1
done

status=0
(
  cd tests
  corepack pnpm install --frozen-lockfile --silent
  DISPLAY="${display}" \
    DEMO_WINDOW="${width},${height}" \
    DEMO_BROWSER_HOME="${work}/home" \
    DEMO_BROWSER_PROFILE="${work}/profile" \
    DEMO_EVENTS="${work}/events.json" \
    corepack pnpm exec playwright test --config playwright.demo.config.ts "${spec}"
) || status=$?

kill -INT "${ffmpeg_pid}"
wait "${ffmpeg_pid}" || true
ffmpeg_pid=""

if [ ! -f "${work}/events.json" ]; then
  echo "The walkthrough wrote no events." >&2
  exit 1
fi
offset="$(python3 - "${work}/events.json" "${work}/ffmpeg.log" << 'PY'
import json, re, sys
events = json.load(open(sys.argv[1]))
started = float(next(e["value"] for e in events if e["kind"] == "start"))
capture = float(re.search(r"start: ([\d.]+)", open(sys.argv[2]).read()).group(1))
print(f"{max(started - capture, 0):.3f}")
PY
)"
# Chrome can take a few seconds to put its first frame on the display, after
# the page is ready. Skip those single-colour frames too, and move the
# events back by the same amount.
lead="$(ffmpeg -v error -ss "${offset}" -t 15 -i "${work}/screen.mkv" -vf "signalstats,metadata=print:file=-" -f null - \
  | awk '/pts_time/ { t = $3; sub("pts_time:", "", t) } /YMIN=/ { split($0, a, "="); low = a[2] } /YMAX=/ { split($0, a, "="); if (a[2] - low > 16) { print t; exit } }')"
lead="${lead:-0}"
echo "Trimming ${offset}s from the start of the capture, then ${lead}s before Chrome's first frame."
ffmpeg -v error -y -ss "$(awk "BEGIN { print ${offset} + ${lead} }")" -i "${work}/screen.mkv" -an -c:v libx264 -crf 14 -pix_fmt yuv420p "${out}/${name}.mp4"
python3 - "${work}/events.json" "${lead}" "${out}/${name}-events.json" << 'PY'
import json, sys
events = json.load(open(sys.argv[1]))
lead = float(sys.argv[2])
for event in events:
    event["at"] = round(max(float(event["at"]) - lead, 0), 3)
json.dump(events, open(sys.argv[3], "w"), indent=2)
PY
exit "${status}"
