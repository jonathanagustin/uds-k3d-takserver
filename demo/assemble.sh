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
size=1280:720
bg=0x1e1e2e
fg=0xcdd6f4
accent=0xcba6f7
title_font="$(fc-match -f '%{file}' 'DejaVu Sans:bold')"
mono_font="$(fc-match -f '%{file}' 'JetBrains Mono')"

# card NAME SECONDS TITLE SUBTITLE
card() {
  local name="$1" secs="$2"
  printf '%s' "$3" > "${work}/${name}.title"
  printf '%s' "$4" > "${work}/${name}.sub"
  ffmpeg -v error -y -f lavfi -i "color=c=${bg}:s=1280x720:r=${fps}:d=${secs}" \
    -vf "drawtext=fontfile=${title_font}:textfile=${work}/${name}.title:fontcolor=${fg}:fontsize=52:x=(w-text_w)/2:y=(h-text_h)/2-30,drawtext=fontfile=${mono_font}:textfile=${work}/${name}.sub:fontcolor=${accent}:fontsize=26:x=(w-text_w)/2:y=(h/2)+40,fade=t=in:st=0:d=0.3,fade=t=out:st=$(awk "BEGIN{print ${secs}-0.3}"):d=0.3" \
    -c:v libx264 -crf 16 -pix_fmt yuv420p "${work}/${name}.mp4"
}

# clip NAME SOURCE [TRIM_START]
clip() {
  local name="$1" src="$2" start="${3:-0}"
  ffmpeg -v error -y -ss "${start}" -i "${src}" -an \
    -vf "scale=${size}:force_original_aspect_ratio=decrease,pad=${size}:(ow-iw)/2:(oh-ih)/2:color=${bg},fps=${fps},format=yuv420p" \
    -c:v libx264 -crf 16 "${work}/${name}.mp4"
}

card c00 3.5 "TAK Server on UDS" "Upstream TAK, packaged with Zarf, running on UDS Core"
card c01 2.5 "1  Upstream app, packaged for UDS" "Zarf package + UDS bundle"
clip t01 "${out}/01-package.mp4"
card c02 2.5 "2  Platform integration" "the UDS Package custom resource"
clip t02 "${out}/02-package-cr.mp4"
card c03 2.5 "3  Secure by default" "mesh, generated policies, SSO, CI gates"
clip t03 "${out}/03-secure.mp4"
card c04 2.5 "4  Running and healthy" "clustered TAK on k3d"
clip t04 "${out}/04-running.mp4"
card c05 2.5 "5  Same package, other clusters" "EKS, RKE2 and AKS scaffolds"
clip t05 "${out}/05-clusters.mp4"
card c06 2.5 "6  Keycloak SSO to the TAK web UI" "recorded with Playwright"
clip t06 "${out}/06-web.webm" 0.4
card c99 4 "github.com/jonathanagustin/uds-k3d-takserver" "uds run test-install"

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

# Poster: the last frame of the web walkthrough. Preview: six seconds of the
# Package CR chapter.
web_secs="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "${work}/t06.mp4")"
ffmpeg -v error -y -ss "$(awk "BEGIN{print ${web_secs}-1}")" -i "${work}/t06.mp4" -frames:v 1 "${out}/poster.png"
ffmpeg -v error -y -ss 4 -t 6 -i "${work}/t02.mp4" \
  -vf "fps=10,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=none" \
  "${out}/preview.gif"

ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height,pix_fmt,r_frame_rate "${out}/demo.mp4"
ls -l "${out}"
