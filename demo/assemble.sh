#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Join title cards, the terminal chapters, and the web walkthrough into
# demo/out/demo.mp4: H.264, yuv420p, faststart, no audio, under MAX_BYTES.
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
  if [ "${last}" = "last" ]; then
    min=4
  fi
  words="$(cat "${work}/${name}.title" "${work}/${name}.sub" | wc -w)"
  secs="$(awk -v w="${words}" -v m="${min}" 'BEGIN { s = 1 + w / 3; if (s < m) s = m; printf "%.1f", s }')"
  title_size="$(python3 demo/filters.py fit "${title_font}" "${work}/${name}.title" 52 "${text_max_w}")"
  sub_size="$(python3 demo/filters.py fit "${mono_font}" "${work}/${name}.sub" 26 "${text_max_w}")"
  fades="fade=t=in:st=0:d=${card_fade}"
  if [ "${last}" != "last" ]; then
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
  if [ -f "${timeline}" ]; then
    effects="$(python3 demo/filters.py "${mode}" "${timeline}" "${secs}" "${work}" "${title_font}" "${start}" "${work}/${name}-base.mp4")"
  fi
  ffmpeg -v error -y -i "${work}/${name}-base.mp4" -an \
    -vf "${effects},format=yuv420p" -c:v libx264 -crf 16 "${work}/${name}.mp4"
}

card c00 "TAK Server on UDS" "Upstream TAK, packaged with Zarf, running on UDS Core"
card c01 "Packaging an upstream app for UDS" "Zarf package and UDS bundle"
clip t01 "${out}/01-package.mp4" terminal demo/out/tapes/01-package.tape
card c02 "Integrating with the platform" "the UDS Package custom resource"
clip t02 "${out}/02-package-cr.mp4" terminal demo/out/tapes/02-package-cr.tape
card c03 "Secure by default" "mesh, generated policies, SSO, CI checks"
clip t03 "${out}/03-secure.mp4" terminal demo/out/tapes/03-secure.tape
card c04 "Running and healthy" "clustered TAK on k3d"
clip t04 "${out}/04-running.mp4" terminal demo/out/tapes/04-running.tape
card c05 "Other clusters (scaffolds)" "OpenTofu for EKS, RKE2 and AKS"
clip t05 "${out}/05-clusters.mp4" terminal demo/out/tapes/05-clusters.tape
card c06 "SSO into the TAK web UI" "Keycloak from UDS Core, in a real Chrome window"
clip t06 "${out}/06-web.mp4" web "${out}/06-web-events.json" "${web_trim}"
card c99 "github.com/jonathanagustin/uds-k3d-takserver" "uds run test-install" last

list="${work}/list.txt"
: > "${list}"
for part in c00 c01 t01 c02 t02 c03 t03 c04 t04 c05 t05 c06 t06 c99; do
  echo "file '$(pwd)/${work}/${part}.mp4'" >> "${list}"
done
ffmpeg -v error -y -f concat -safe 0 -i "${list}" -c copy "${work}/joined.mp4"

for crf in 26 28 30 32 34 36; do
  ffmpeg -v error -y -i "${work}/joined.mp4" -an \
    -c:v libx264 -preset slow -crf "${crf}" -profile:v high -pix_fmt yuv420p \
    -g $((fps * 4)) -movflags +faststart "${out}/demo.mp4"
  bytes="$(stat -c%s "${out}/demo.mp4")"
  echo "crf ${crf}: ${bytes} bytes"
  if [ "${bytes}" -le "${max_bytes}" ]; then
    break
  fi
done

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
ls -l "${out}"
