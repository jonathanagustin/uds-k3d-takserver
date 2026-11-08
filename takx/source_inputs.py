#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Verify pinned public source inputs and the integrity of a local build cache."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

ARTIFACTS = (
    "java/jcommoncommo.jar", "lib/libcommoncommo.a", "lib/libcommoncommojni.so",
    "lib/libssl.so.81.3", "lib/libcrypto.so.81.3",
)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def check_archive(path, entry):
    if path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
        raise ValueError(f"Source archive hash/size mismatch: {path}")


def verify_source(source, lock):
    top = subprocess.check_output(["git", "-C", str(source), "rev-parse", "--show-toplevel"], text=True).strip()
    if Path(top).resolve() != source.resolve():
        raise ValueError("ATAK source must be the root of its initialized Git worktree")
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != lock["atak_source"]["revision"]:
        raise ValueError("ATAK source revision does not match sources.lock.json")
    subprocess.run([
        "git", "-C", str(source), "diff", "--quiet", "HEAD", "--", "commoncommo",
        "takthirdparty/Makefile", "takthirdparty/host-detect.mk", "takthirdparty/mk",
        "takthirdparty/target-config", "takthirdparty/distfiles/*.patch",
    ], check=True)
    untracked = subprocess.check_output([
        "git", "-C", str(source), "ls-files", "--others", "--exclude-standard", "--",
        "commoncommo", "takthirdparty/Makefile", "takthirdparty/host-detect.mk",
        "takthirdparty/mk", "takthirdparty/target-config", "takthirdparty/distfiles/*.patch",
    ], text=True).splitlines()
    if untracked:
        raise ValueError(f"Untracked source/build inputs: {', '.join(untracked)}")
    header = (source / "commoncommo/core/include/commoversion.h").read_text()
    version = ".".join(re.findall(r"#define COMMO_(?:MAJOR|MINOR|PATCH)\s+(\d+)", header))
    if version != lock["commoncommo_version"]:
        raise ValueError("CommonCommo source version does not match the lock")


def materialize(source, cache, lock, offline=False):
    cache.mkdir(parents=True, exist_ok=True)
    for entry in lock["archives"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:2] != ("takthirdparty", "distfiles"):
            raise ValueError("Unexpected archive path in lock")
        revision = lock["atak_source"]["revision"]
        roots = ("https://raw.githubusercontent.com/", "https://media.githubusercontent.com/media/")
        allowed = tuple(root + f"TAK-Product-Center/atak-civ/{revision}/{entry['path']}" for root in roots)
        if entry["url"] not in allowed:
            raise ValueError("Archive URL is not the pinned official public source")
        destination = source / relative
        if destination.exists():
            with destination.open("rb") as stream:
                prefix = stream.read(256)
            if prefix.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
                expected = f"oid sha256:{entry['sha256']}\nsize {entry['bytes']}\n".encode()
                if expected not in prefix:
                    raise ValueError(f"LFS pointer does not match lock: {destination}")
            else:
                check_archive(destination, entry)
                continue
        cached = cache / entry["sha256"]
        if cached.exists():
            check_archive(cached, entry)
        elif offline:
            raise ValueError(f"Verified source archive not cached: {relative}")
        else:
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
                temporary = Path(output.name)
                try:
                    with urllib.request.urlopen(entry["url"], timeout=30) as response:
                        remaining = entry["bytes"] + 1
                        while remaining:
                            block = response.read(min(1024 * 1024, remaining))
                            if not block:
                                break
                            output.write(block)
                            remaining -= len(block)
                    output.flush()
                    check_archive(temporary, entry)
                    temporary.replace(cached)
                finally:
                    temporary.unlink(missing_ok=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(cached.read_bytes())
        check_archive(destination, entry)


def cache_key(lock_path, source, output, toolchain):
    lock = json.loads(lock_path.read_text())
    native_inputs = {field: lock[field] for field in ("atak_source", "commoncommo_version", "archives")}
    recipe = Path(__file__).with_name("build-commoncommo.sh")
    payload = {
        "native_inputs": native_inputs, "recipe": digest(recipe),
        "source": str(source.resolve()), "output": str(output.resolve()), "toolchain": toolchain,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def artifact_state(output, key):
    for name in ARTIFACTS:
        if not (output / name).is_file():
            raise FileNotFoundError(f"Missing native build output: {name}")
    files = sorted(
        path for directory in ("java", "lib") for path in (output / directory).rglob("*")
        if path.is_file() and (path.name.endswith((".a", ".jar")) or re.search(r"\.so(?:\.[0-9]+)*$", path.name))
    )
    return {"schema": 1, "key": key, "artifacts": {str(path.relative_to(output)): digest(path) for path in files}}



def lifecycle_error(reason):
    raise ValueError(f"{reason}; choose a fresh TAKX_BUILD_DIR")


def expected_start(key):
    return {"schema": 1, "key": key}


def read_state(path):
    try:
        state = json.loads(path.read_text())
    except (ValueError, OSError):
        lifecycle_error("Invalid build metadata")
    if not isinstance(state, dict):
        lifecycle_error("Invalid build metadata")
    return state


def cache_status(output, key):
    start_file = output / "build-inputs.json"
    complete_file = output / "build-state.json"
    if complete_file.exists():
        if not start_file.exists() or read_state(start_file) != expected_start(key):
            lifecycle_error("Completed prefix has a different or missing build input key")
        previous = read_state(complete_file)
        if previous.get("key") != key:
            lifecycle_error("Completed prefix was built with different inputs")
        try:
            current = artifact_state(output, key)
        except FileNotFoundError:
            lifecycle_error("Completed prefix has missing artifacts")
        if previous != current:
            lifecycle_error("Completed prefix artifact integrity mismatch")
        return "complete"
    if start_file.exists():
        if read_state(start_file) != expected_start(key):
            lifecycle_error("Interrupted prefix has different build inputs")
        return "resume"
    if output.exists() and any(output.iterdir()):
        lifecycle_error("Nonempty prefix has no recorded build start")
    return "new"


def start_cache(output, key):
    status = cache_status(output, key)
    if status == "complete":
        lifecycle_error("Prefix is already a completed build")
    if status == "new":
        output.mkdir(parents=True, exist_ok=True)
        (output / "build-inputs.json").write_text(json.dumps(expected_start(key), indent=2) + "\n")


def complete_cache(output, key):
    start_file = output / "build-inputs.json"
    if not start_file.exists() or read_state(start_file) != expected_start(key):
        lifecycle_error("No matching build start was recorded")
    if (output / "build-state.json").exists():
        cache_status(output, key)
        return
    state = artifact_state(output, key)
    (output / "build-state.json").write_text(json.dumps(state, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "cache-check", "cache-start", "cache-write"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=Path(__file__).with_name("sources.lock.json"))
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--toolchain", default="")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())
    verify_source(args.source, lock)
    if args.command == "verify":
        if args.cache is None:
            parser.error("verify requires --cache")
        materialize(args.source, args.cache, lock, args.offline)
        print(f"Verified ATAK {lock['atak_source']['revision']} / CommonCommo {lock['commoncommo_version']}")
        return
    if args.output is None:
        parser.error("cache commands require --output")
    key = cache_key(args.lock, args.source, args.output, args.toolchain)
    if args.command == "cache-check":
        sys.exit(0 if cache_status(args.output, key) == "complete" else 1)
    if args.command == "cache-start":
        start_cache(args.output, key)
    else:
        complete_cache(args.output, key)



if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        sys.exit(2)
