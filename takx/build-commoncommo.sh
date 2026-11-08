#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Opt-in Linux amd64 source build. This does not build or install TAKX.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_dir="$(realpath "${ATAK_SOURCE_DIR:-${here}/../upstream/atak-civ}")"
cache_root="${XDG_CACHE_HOME:-${HOME}/.cache}/uds-takserver/takx"
source_id="$(printf %s "${source_dir}" | sha256sum)"
source_id="${source_id:0:12}"
output="$(realpath -m "${TAKX_BUILD_DIR:-${cache_root}/build/${source_id}/commoncommo}")"
cache="$(realpath -m "${TAKX_CACHE_DIR:-${cache_root}/sources}")"
jobs="${TAKX_JOBS:-2}"
mode="${1:-build}"
if [[ "${mode}" != build && "${mode}" != --verify-only && "${mode}" != --smoke-only ]]; then
  echo "Usage: $0 [build|--verify-only|--smoke-only]" >&2
  exit 2
fi
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo "Supported target: Linux amd64" >&2; exit 1; }
[[ "${jobs}" =~ ^[12]$ ]] || { echo "TAKX_JOBS must be 1 or 2" >&2; exit 1; }
for path in "${source_dir}" "${output}"; do
  [[ "${path}" != *[[:space:]]* ]] || { echo "Upstream make requires source/output paths without whitespace" >&2; exit 1; }
done
verify=(python3 "${here}/source_inputs.py" verify --source "${source_dir}" --cache "${cache}")
if [[ "${TAKX_OFFLINE:-false}" == true ]]; then verify+=(--offline); fi
"${verify[@]}"
if [[ "${mode}" == --verify-only ]]; then exit 0; fi

: "${JAVA_HOME:?Set JAVA_HOME to a JDK 17 installation}"
for tool in make gcc g++ perl ant dos2unix patch tar pkg-config timeout install; do
  command -v "${tool}" >/dev/null || { echo "Missing build tool: ${tool}" >&2; exit 1; }
done
javac_version="$("${JAVA_HOME}/bin/javac" -version 2>&1)"
[[ "${javac_version}" == javac\ 17.* ]] || { echo "This foundation is tested with JDK 17" >&2; exit 1; }
toolchain="${javac_version};gcc=$(gcc -dumpfullversion);g++=$(g++ -dumpfullversion);$(ant -version)"
state=(python3 "${here}/source_inputs.py" --source "${source_dir}" --output "${output}" --toolchain "${toolchain}")
mkdir -p "${output}"
if [[ "${mode}" != --smoke-only ]]; then
  if "${state[@]}" cache-check; then
    echo "Verified local build cache; skipping native compilation"
  else
    cache_status=$?
    if [[ "${cache_status}" != 1 ]]; then exit "${cache_status}"; fi
    "${state[@]}" cache-start
    # The upstream core buildstamp runs git from the copied sources. Keep its
    # identity tied to ATAK even when the output is outside that checkout.
    export GIT_DIR
    GIT_DIR="$(git -C "${source_dir}" rev-parse --absolute-git-dir)"
    export GIT_WORK_TREE="${source_dir}"
    make_source=(make -C "${source_dir}/takthirdparty" TARGET=linux-amd64 BUILD_TYPE=release "TARGET_OUTDIR=${output}")
    : > "${output}/build.log"
    run() {
      if ! "$@" >> "${output}/build.log" 2>&1; then
        tail -n 25 "${output}/build.log" >&2
        return 1
      fi
    }
    # Serial package installs avoid the upstream multi-output OpenSSL install
    # race. No more than two compiler jobs run in any following stage.
    for package in zlib libiconv libxml2 openssl nghttp2 curl ngtcp2 libmicrohttpd; do
      echo "Building ${package}"
      run "${make_source[@]}" -j1 "${package}"
    done
    run "${make_source[@]}" -j1 "${output}/host-protobuf/protobuf/.unpacked"
    if [[ ! -f "${output}/host-protobuf/.built" ]]; then
      (
        cd "${output}/host-protobuf/protobuf"
        run env DIST_LANG=cpp ./configure "--prefix=${output}/host-protobuf"
        run make "-j${jobs}"
        run make -j1 install
      )
      touch "${output}/host-protobuf/.built"
    fi
    "${output}/host-protobuf/bin/protoc" --version
    run "${make_source[@]}" -j1 "${output}/protobuf/.configured"
    # CommonCommo needs the real same-version protobuf-lite library and public
    # headers, not a second build of all protoc language generators.
    run make -C "${output}/protobuf/src" "-j${jobs}" libprotobuf-lite.la
    run make -C "${output}/protobuf/src" -j1 install-nobase_includeHEADERS
    install -m 644 "${output}/protobuf/src/.libs/libprotobuf-lite.a" "${output}/lib/libprotobuf-lite.a"
    run "${make_source[@]}" "-j${jobs}" "${output}/lib/libcommoncommo.a"
    mkdir -p "${output}/java"
    run "${make_source[@]}" "-j${jobs}" "${output}/lib/libcommoncommojni.so"
  fi
fi

# The Ant JAR uses its internal initializer. Manual JNI preloading would
# reenter initialization; constructing Commo follows the intended contract.
mkdir -p "${output}/smoke-classes"
"${JAVA_HOME}/bin/javac" --release 17 -classpath "${output}/java/jcommoncommo.jar" \
  -d "${output}/smoke-classes" "${here}/CommonCommoSmoke.java"
LD_LIBRARY_PATH="${output}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
  timeout 30 "${JAVA_HOME}/bin/java" "-Djava.library.path=${output}/lib" \
  -cp "${output}/java/jcommoncommo.jar:${output}/smoke-classes" CommonCommoSmoke
if [[ "${mode}" != --smoke-only ]]; then "${state[@]}" cache-write; fi
printf 'CommonCommo 1.17.2 artifacts: %s/{java,lib}\n' "${output}"
