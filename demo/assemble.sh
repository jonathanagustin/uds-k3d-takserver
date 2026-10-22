#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Join title cards, the terminal chapters, and the web walkthroughs into two
# videos: demo/out/demo.mp4 (deploy) and demo/out/demo-operate.mp4 (operate
# and trust). H.264, yuv420p, faststart, no audio, each under MAX_BYTES.
# Each gets a NAME-chapters.txt with the start time of every part.
# Also writes demo/out/poster.png and demo/out/preview.gif.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
out=demo/out
work="${out}/work"
rm -rf "${work}"
mkdir -p "${work}"

max_bytes="${MAX_BYTES:-9500000}"
fps=24
# Recorded content fills 1280x630. demo/filters.py adds the 90 px caption
# band below it, so every segment ends up 1280x720.
size=1280:630
band=0x11111b
# Card text keeps at least 8% of the width clear on each side.
text_max_w=1075
bg=0x1e1e2e
fg=0xcdd6f4
accent=0xcba6f7
title_font="$(fc-match -f '%{file}' 'DejaVu Sans:bold')"
mono_font="$(fc-match -f '%{file}' 'JetBrains Mono')"
# demo/record-browser.sh already trims the capture to the walkthrough's start.
web_trim="${WEB_TRIM:-0}"

# card NAME TITLE SUBTITLE [last]
# A card stays up long enough to read: one second plus three words per
# second of title and subtitle, at least 3 s, and at least 4 s for the last
# card. That time includes the fades. Font sizes shrink from 52 and 26 until
# the text fits text_max_w. The last card does not fade out, so the video
# ends on the full card.
card_fade=0.4
card() {
  local name="$1" last="${4:-}" words secs min=3 title_size sub_size fades
  printf '%s' "$2" > "${work}/${name}.title"
  printf '%s' "$3" > "${work}/${name}.sub"
  if [[ "${last}" = "last" ]]; then
    min=4
  fi
  words="$(cat "${work}/${name}.title" "${work}/${name}.sub" | wc -w)"
  secs="$(awk -v w="${words}" -v m="${min}" 'BEGIN { s = 1 + w / 3; if (s < m) s = m; printf "%.1f", s }')"
  title_size="$(python3 demo/filters.py fit "${title_font}" "${work}/${name}.title" 52 "${text_max_w}")"
  sub_size="$(python3 demo/filters.py fit "${mono_font}" "${work}/${name}.sub" 26 "${text_max_w}")"
  fades="fade=t=in:st=0:d=${card_fade}"
  if [[ "${last}" != "last" ]]; then
    fades="${fades},fade=t=out:st=$(awk "BEGIN{print ${secs}-${card_fade}}"):d=${card_fade}"
  fi
  echo "card ${name}: ${words} words, ${secs}s, title ${title_size}px, subtitle ${sub_size}px"
  ffmpeg -v error -y -f lavfi -i "color=c=${bg}:s=1280x720:r=${fps}:d=${secs}" \
    -vf "drawtext=fontfile=${title_font}:textfile=${work}/${name}.title:fontcolor=${fg}:fontsize=${title_size}:x=(w-text_w)/2:y=(h-text_h)/2-30,drawtext=fontfile=${mono_font}:textfile=${work}/${name}.sub:fontcolor=${accent}:fontsize=${sub_size}:x=(w-text_w)/2:y=(h/2)+40,${fades}" \
    -c:v libx264 -crf 16 -pix_fmt yuv420p "${work}/${name}.mp4"
}

# clip NAME SOURCE MODE TIMELINE [TRIM_START]
# MODE is terminal (TIMELINE is the tape) or web (TIMELINE is events.json).
clip() {
  local name="$1" src="$2" mode="$3" timeline="$4" start="${5:-0}"
  ffmpeg -v error -y -ss "${start}" -i "${src}" -an \
    -vf "scale=${size}:force_original_aspect_ratio=decrease,pad=${size}:(ow-iw)/2:(oh-ih)/2:color=${bg},fps=${fps},format=yuv420p" \
    -c:v libx264 -crf 16 "${work}/${name}-base.mp4"
  local secs effects
  secs="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "${work}/${name}-base.mp4")"
  effects="pad=1280:720:0:0:color=${band}"
  if [[ -f "${timeline}" ]]; then
    effects="$(python3 demo/filters.py "${mode}" "${timeline}" "${secs}" "${work}" "${title_font}" "${start}" "${work}/${name}-base.mp4")"
  fi
  ffmpeg -v error -y -i "${work}/${name}-base.mp4" -an \
    -vf "${effects},format=yuv420p" -c:v libx264 -crf 16 "${work}/${name}.mp4"
}

# build NAME PART... joins the parts into ${out}/NAME.mp4 under max_bytes and
# writes ${out}/NAME-chapters.txt (start time and caption of each part).
build() {
  local name="$1" list="${work}/$1-list.txt" chapters="${out}/$1-chapters.txt" at=0 part secs crf bytes
  shift
  : > "${list}"
  : > "${chapters}"
  for part in "$@"; do
    echo "file '$(pwd)/${work}/${part}.mp4'" >> "${list}"
    printf '%s %s\n' "$(awk -v t="${at}" 'BEGIN { printf "%d:%04.1f", t / 60, t % 60 }')" \
      "$(cat "${work}/${part}.title" 2>/dev/null || echo "${part}")" >> "${chapters}"
    secs="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "${work}/${part}.mp4")"
    at="$(awk -v a="${at}" -v s="${secs}" 'BEGIN { print a + s }')"
  done
  ffmpeg -v error -y -f concat -safe 0 -i "${list}" -c copy "${work}/${name}-joined.mp4"
  for crf in 26 28 30 32 34 36; do
    ffmpeg -v error -y -i "${work}/${name}-joined.mp4" -an \
      -c:v libx264 -preset slow -crf "${crf}" -profile:v high -pix_fmt yuv420p \
      -g $((fps * 4)) -movflags +faststart "${out}/${name}.mp4"
    bytes="$(stat -c%s "${out}/${name}.mp4")"
    echo "${name} crf ${crf}: ${bytes} bytes"
    if [[ "${bytes}" -le "${max_bytes}" ]]; then
      break
    fi
  done
  cat "${chapters}"
}

# Video 1, Deploy: the standard UDS flow from this run's real deployment
# (demo/deploy.sh, recorded by the workflow), the Package CR, SSO sign-in,
# and the ATAK test device on the same server.
deploy_video=(v1)
card v1 "TAK Server on UDS: deploy" "Upstream TAK, packaged with Zarf, deployed on UDS Core"
if [[ -f "${out}/00-deploy-4.mp4" ]]; then
  for n in 1 2 3 4; do
    clip "d0${n}" "${out}/00-deploy-${n}.mp4" web "${out}/00-deploy-${n}-events.json" 0
    deploy_video+=("d0${n}")
  done
fi
card c02 "Package ready" "the UDS Operator turns one Package CR into policy, routes and SSO"
clip t02 "${out}/02-package-cr.mp4" terminal demo/out/tapes/02-package-cr.tape
card c06 "Sign in through UDS SSO" "TAK's web UI at takserver.uds.dev, Keycloak from UDS Core"
clip t06 "${out}/06-web.mp4" web "${out}/06-web-events.json" "${web_trim}"
deploy_video+=(c02 t02 c06 t06)
if [[ -f "${out}/08-atak.mp4" ]]; then
  card c08 "A real ATAK device on the same server" "ATAK-CIV in a KubeVirt VM, its TEST LOCATION marker in CloudTAK"
  clip t08 "${out}/08-atak.mp4" web "${out}/08-atak-events.json" "${web_trim}"
  deploy_video+=(c08 t08)
fi
card c99 "github.com/jonathanagustin/uds-k3d-takserver" "uds run test-install" last
deploy_video+=(c99)

# Video 2, Operate and trust.
operate_video=(v2)
card v2 "TAK Server on UDS: operate and trust" "air-gapped, policy-checked, verified, measured"
card c2a "Air-gapped install" "images from the in-cluster Zarf registry, SBOMs in the package"
clip t2a "${out}/02a-airgap.mp4" terminal demo/out/tapes/02a-airgap.tape
card c2b "Policy at work" "UDS admission policy on every pod, one narrow exemption"
clip t2b "${out}/02b-policy.mp4" terminal demo/out/tapes/02b-policy.tape
operate_video+=(c2a t2a c2b t2b)
if [[ -f "${out}/09-sync.mp4" ]]; then
  card c09 "CloudTAK and ATAK in sync" "a TEST MARKER and a TEST chat message, live"
  clip t09 "${out}/09-sync.mp4" web "${out}/09-sync-events.json" "${web_trim}"
  operate_video+=(c09 t09)
fi
card c03 "Secure by default" "mesh, generated network policy, signed releases with provenance"
clip t03 "${out}/03-secure.mp4" terminal demo/out/tapes/03-secure.tape
operate_video+=(c03 t03)
if [[ -f "${out}/10-operate-4.mp4" ]]; then
  card c10 "Footprint and self-healing" "live numbers from this run; TAK's messaging pod deleted"
  operate_video+=(c10)
  for n in 1 2 3 4 5; do
    if [[ -f "${out}/10-operate-${n}.mp4" ]]; then
      clip "e0${n}" "${out}/10-operate-${n}.mp4" web "${out}/10-operate-${n}-events.json" 0
      operate_video+=("e0${n}")
    fi
  done
fi
card c98 "What this does not prove" "phone is an Android VM; fixed TEST LOCATION; one-node k3d; no radio or degraded links"
card c97 "github.com/jonathanagustin/uds-k3d-takserver" "open issues track the known gaps" last
operate_video+=(c98 c97)

build demo "${deploy_video[@]}"
build demo-operate "${operate_video[@]}"

# Poster: the TAK landing page after sign-in, with its caption fully shown
# and before the zoom starts. Preview: six seconds of the Package CR chapter.
web_secs="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "${work}/t06.mp4")"
poster_at="$(python3 -c '
import json, sys
events = json.load(open(sys.argv[1]))
zooms = [e["at"] for e in events if e["kind"] == "zoom"]
at = zooms[0] - float(sys.argv[2]) + 0.7 if zooms else float(sys.argv[3]) - 1
print(f"{max(at, 0):.2f}")
' "${out}/06-web-events.json" "${web_trim}" "${web_secs}" 2>/dev/null || awk "BEGIN{print ${web_secs}-1}")"
ffmpeg -v error -y -ss "${poster_at}" -i "${work}/t06.mp4" -frames:v 1 "${out}/poster.png"
ffmpeg -v error -y -ss 4 -t 6 -i "${work}/t02.mp4" \
  -vf "fps=10,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=none" \
  "${out}/preview.gif"

ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height,pix_fmt,r_frame_rate "${out}/demo.mp4"
ffprobe -v error -show_entries format=duration,size "${out}/demo-operate.mp4"
ls -l "${out}"
