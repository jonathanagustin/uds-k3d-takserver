#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Join title cards, the terminal chapters, and the web walkthroughs into two
# 1920x1080, 30 fps videos, with 0.3 s crossfades between parts: demo/out/demo.mp4 (deploy) and demo/out/demo-operate.mp4 (operate
# and trust). H.264, yuv420p, faststart, no audio, each under MAX_BYTES.
# Each gets a NAME-chapters.txt with the start time of every part.
# Also writes demo/out/poster.png and demo/out/preview.gif, one short clip
# per chapter cut from the same parts (demo/out/clips/demo-clip-*.mp4, each
# with a .jpg poster) for the doc pages, and WebP copies of the stills the
# tapes and walkthroughs saved (demo/out/shots/*.webp).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
out=demo/out
work="${out}/work"
rm -rf "${work}"
mkdir -p "${work}"

max_bytes="${MAX_BYTES:-9500000}"
# The look (canvas, palette, fonts, frame, cards, lower-thirds) is in
# demo/style.py; demo/filters.py styles each segment with it.
fps=30
# Each recording is fitted into the window frame's content area.
size=1632:840
bg=0x0F172A
# demo/record-browser.sh already trims the capture to the walkthrough's start.
web_trim="${WEB_TRIM:-0}"
# No fallback fonts: stop here if Inter or JetBrains Mono is missing.
python3 demo/style.py fonts

# card NAME TITLE SUBTITLE [last]
# A title card holds for 3.5 s between its crossfades (demo/filters.py join
# fades 0.3 s into and out of each part; between two cards it fades the first
# card's text out before the next one's comes in). The last card holds a
# little longer.
card() {
  local name="$1" last="${4:-}" secs=4.1
  printf '%s' "$2" > "${work}/${name}.title"
  if [[ "${last}" = "last" ]]; then
    secs=4.5
  fi
  python3 demo/style.py card "${work}/${name}.png" "$2" "$3"
  echo "card ${name}: ${secs}s"
  ffmpeg -v error -y -loop 1 -framerate "${fps}" -i "${work}/${name}.png" -t "${secs}" \
    -c:v libx264 -crf 16 -pix_fmt yuv420p "${work}/${name}.mp4"
}

# clip NAME SOURCE MODE TIMELINE [TRIM_START]
# MODE is terminal (TIMELINE is the tape), web (a browser recording and its
# events.json) or cast (a rendered asciicast and its events.json).
clip() {
  local name="$1" src="$2" mode="$3" timeline="$4" start="${5:-0}" device
  if [[ "${mode}" = web && -f "${timeline}" ]]; then
    # The phone's own screen recording, when the run made one.
    device="demo/out/atak/$(basename "${src%.mp4}")-device.mp4"
    python3 demo/filters.py prepare "${src}" "${timeline}" "${work}/${name}-prep.mp4" "${work}/${name}-prep.json" \
      ${device:+"${device}"} ${device:+"${device%.mp4}.start"}
    src="${work}/${name}-prep.mp4"
    timeline="${work}/${name}-prep.json"
  fi
  ffmpeg -v error -y -ss "${start}" -i "${src}" -an \
    -vf "scale=${size}:force_original_aspect_ratio=decrease:flags=lanczos,pad=${size}:(ow-iw)/2:(oh-ih)/2:color=${bg},fps=${fps},format=yuv420p" \
    -c:v libx264 -crf 14 "${work}/${name}-base.mp4"
  python3 demo/filters.py render "${mode}" "${timeline}" "${work}/${name}-base.mp4" "${work}/${name}.mp4" "${work}" "${start}"
  # A web or cast clip whose first event is a caption gets that caption,
  # without the "(real time ...)" note, as its chapter title. Other clips
  # follow a card and get no chapter of their own. Caption chapters are
  # indented under the card chapter they belong to.
  if [[ "${mode}" != terminal && -f "${timeline}" ]]; then
    python3 -c '
import json, re, sys
events = json.load(open(sys.argv[1]))
captions = [e for e in events if e["kind"] == "caption"]
if captions and captions[0]["at"] <= 0.5:
    print("  " + re.sub(r"\s*\(real time[^)]*\)$", "", captions[0]["value"]), end="")
' "${timeline}" > "${work}/${name}.title"
    [[ -s "${work}/${name}.title" ]] || rm -f "${work}/${name}.title"
  fi
}

# build NAME PART... joins the parts with crossfades into ${out}/NAME.mp4
# under max_bytes and writes ${out}/NAME-chapters.txt (start time and title
# of each card and captioned clip).
build() {
  local name="$1" chapters="${out}/$1-chapters.txt" crf bytes i=0 at
  shift
  local files=()
  for part in "$@"; do
    files+=("${work}/${part}.mp4")
  done
  mapfile -t starts < <(python3 demo/filters.py join "${work}/${name}-joined.mp4" "${files[@]}")
  : > "${chapters}"
  for part in "$@"; do
    at="${starts[${i}]}"
    if [[ -s "${work}/${part}.title" ]]; then
      printf '%s %s\n' "$(awk -v t="${at}" 'BEGIN { printf "%d:%04.1f", t / 60, t % 60 }')" \
        "$(cat "${work}/${part}.title")" >> "${chapters}"
    fi
    i=$((i + 1))
  done
  # Screen recordings are mostly still: veryslow with -tune animation and
  # keyframes every 10 s keep 1080p sharp within max_bytes.
  for crf in 24 26 28 30 32 34; do
    ffmpeg -v error -y -i "${work}/${name}-joined.mp4" -an \
      -c:v libx264 -preset veryslow -tune animation -crf "${crf}" -profile:v high -pix_fmt yuv420p \
      -g $((fps * 10)) -movflags +faststart "${out}/${name}.mp4"
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
card v1 "Deploy" "Upstream TAK, packaged with Zarf, deployed on UDS Core"
if [[ -f "${out}/00-deploy-4.mp4" ]]; then
  for n in 1 2 3 4; do
    clip "d0${n}" "${out}/00-deploy-${n}.mp4" cast "${out}/00-deploy-${n}-events.json" 0
    deploy_video+=("d0${n}")
  done
fi
card c02 "Package Ready" "the UDS Operator turns one Package CR into policy, routes and SSO"
clip t02 "${out}/02-package-cr.mp4" terminal demo/out/tapes/02-package-cr.tape
card c06 "Sign In through UDS SSO" "TAK's web UI at takserver.uds.dev, Keycloak from UDS Core"
clip t06 "${out}/06-web.mp4" web "${out}/06-web-events.json" "${web_trim}"
deploy_video+=(c02 t02 c06 t06)
if [[ -f "${out}/07-user.mp4" ]]; then
  card c07 "CloudTAK for Regular Users" "a non-admin group signs in to the map; TAK's admin UI stays admin-only"
  clip t07 "${out}/07-user.mp4" web "${out}/07-user-events.json" "${web_trim}"
  deploy_video+=(c07 t07)
fi
if [[ -f "${out}/08-atak.mp4" ]]; then
  card c08 "A Real ATAK Device on the Same Server" "ATAK-CIV in a KubeVirt VM, its TEST LOCATION marker in CloudTAK"
  clip t08 "${out}/08-atak.mp4" web "${out}/08-atak-events.json" "${web_trim}"
  deploy_video+=(c08 t08)
fi
card c99 "Get started" "uds run test-install" last
deploy_video+=(c99)

# Video 2, Operate and trust.
operate_video=(v2)
card v2 "Operate and Trust" "air-gapped, policy-checked, verified, measured"
card c2a "Air-Gapped Install" "images from the in-cluster Zarf registry, SBOMs in the package"
clip t2a "${out}/02a-airgap.mp4" terminal demo/out/tapes/02a-airgap.tape
card c2b "Policy at Work" "UDS admission policy on every pod, one narrow exemption"
clip t2b "${out}/02b-policy.mp4" terminal demo/out/tapes/02b-policy.tape
operate_video+=(c2a t2a c2b t2b)
if [[ -f "${out}/09-sync.mp4" ]]; then
  card c09 "CloudTAK and ATAK in Sync" "a TEST MARKER and a TEST chat message, live"
  clip t09 "${out}/09-sync.mp4" web "${out}/09-sync-events.json" "${web_trim}"
  operate_video+=(c09 t09)
fi
card c03 "Secure by Default" "mesh, generated network policy, signed releases with provenance"
clip t03 "${out}/03-secure.mp4" terminal demo/out/tapes/03-secure.tape
operate_video+=(c03 t03)
# demo/upgrade.sh, recorded last on a new cluster. Without it there is no
# card: a chapter title with nothing after it says nothing.
if [[ -f "${out}/11-upgrade-5.mp4" ]]; then
  card c96 "Upgrades from the Last Signed Release" "install the verified release, upgrade in place, keep certificates and data"
  operate_video+=(c96)
  for n in 1 2 3 4 5; do
    clip "u0${n}" "${out}/11-upgrade-${n}.mp4" cast "${out}/11-upgrade-${n}-events.json" 0
    operate_video+=("u0${n}")
  done
fi
if [[ -f "${out}/10-operate-4.mp4" ]]; then
  card c10 "Footprint and Self-Healing" "live numbers from this run; TAK's messaging pod deleted"
  operate_video+=(c10)
  for n in 1 2 3 4 5; do
    if [[ -f "${out}/10-operate-${n}.mp4" ]]; then
      clip "e0${n}" "${out}/10-operate-${n}.mp4" cast "${out}/10-operate-${n}-events.json" 0
      operate_video+=("e0${n}")
    fi
  done
fi
card c98 "What This Does Not Prove" "Android VM phone · fixed TEST LOCATION · one-node k3d · no radio or degraded links"
card c97 "Explore the project" "open issues track the known gaps" last
operate_video+=(c98 c97)

build demo "${deploy_video[@]}"
build demo-operate "${operate_video[@]}"

# chapter SLUG PART... joins one chapter's parts (its card first) into
# ${out}/clips/demo-clip-SLUG.mp4 for the doc page about it, with a poster
# two seconds after the card. Parts that were not recorded are skipped, and
# so is a chapter with only its card.
mkdir -p "${out}/clips"
chapter() {
  local slug="$1" part card_secs files=()
  shift
  for part in "$@"; do
    if [[ -f "${work}/${part}.mp4" ]]; then
      files+=("${work}/${part}.mp4")
    fi
  done
  if [[ "${#files[@]}" -lt 2 ]]; then
    echo "clip ${slug}: not recorded, skipped"
    return 0
  fi
  python3 demo/filters.py join "${work}/clip-${slug}-joined.mp4" "${files[@]}" > /dev/null
  ffmpeg -v error -y -i "${work}/clip-${slug}-joined.mp4" -an \
    -c:v libx264 -preset slow -crf 28 -profile:v high -pix_fmt yuv420p \
    -g $((fps * 4)) -movflags +faststart "${out}/clips/demo-clip-${slug}.mp4"
  card_secs="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "${work}/$1.mp4")"
  ffmpeg -v error -y -ss "$(awk -v c="${card_secs}" 'BEGIN { print c + 2 }')" -i "${out}/clips/demo-clip-${slug}.mp4" \
    -frames:v 1 -q:v 3 "${out}/clips/demo-clip-${slug}.jpg"
  echo "clip ${slug}: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "${out}/clips/demo-clip-${slug}.mp4")s"
}
chapter deploy v1 d01 d02 d03 d04
chapter package-ready c02 t02
chapter sso c06 t06
chapter cloudtak-user c07 t07
chapter atak-device c08 t08
chapter airgap c2a t2a
chapter policy c2b t2b
chapter sync c09 t09
chapter secure c03 t03
chapter upgrade c96 u01 u02 u03 u04 u05
chapter self-healing c10 e01 e02 e03 e04 e05

# The stills, in the window frame on the canvas background, as WebP for the
# docs (lossless: they are mostly text).
for shot in "${out}"/shots/*.png; do
  [[ -f "${shot}" ]] || continue
  python3 demo/style.py still "${shot}" "${work}/still.png"
  ffmpeg -v error -y -i "${work}/still.png" -c:v libwebp -lossless 1 -compression_level 6 "${shot%.png}.webp"
  echo "still $(basename "${shot%.png}"): $(stat -c%s "${shot%.png}.webp") bytes"
done
# The two videos' posters, as the docs site shows them.
ffmpeg -v error -y -ss 1.5 -i "${out}/demo.mp4" -frames:v 1 -q:v 3 "${out}/demo-deploy.jpg"
ffmpeg -v error -y -ss 1.5 -i "${out}/demo-operate.mp4" -frames:v 1 -q:v 3 "${out}/demo-operate-and-trust.jpg"

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
