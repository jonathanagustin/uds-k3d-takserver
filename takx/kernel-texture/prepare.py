#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Create a hash-bound feature source overlay; no build, download or source-tree mutation."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess

HERE = Path(__file__).resolve().parent

def digest(data):
    return hashlib.sha256(data).hexdigest()

def regular_bytes(path, limit=2 * 1024 * 1024):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ValueError("bounded regular source file required")
    # Do not follow a link substituted between the lstat and open.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("regular source file required")
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("source file exceeds bound")
    return data

def source_path(root, name):
    parts = PurePosixPath(name).parts
    if not parts or PurePosixPath(name).is_absolute() or ".." in parts or "\\" in name or parts[:3] != ("takkernel", "engine", "src"):
        raise ValueError("unexpected feature source path")
    current = root
    for part in parts[:-1]:
        current /= part
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise ValueError("source parent must be a real directory")
    return root.joinpath(*parts)

def verify_files(root, files, field):
    for name, entry in files.items():
        expected = entry[field]
        path = source_path(root, name)
        if expected is None:
            if path.exists() or path.is_symlink():
                raise ValueError("new feature file already exists")
        elif digest(regular_bytes(path)) != expected:
            raise ValueError("feature source image differs: " + name)

def load_contract():
    lock = json.loads(regular_bytes(HERE / "source.lock.json"))
    patch = regular_bytes(HERE / "texture-fill.patch")
    if digest(patch) != lock["patch_sha256"]:
        raise ValueError("feature patch differs")
    if lock["source_commit"] != "9f6893dd657feacc35ec5de03dad721c2e44170e" or lock["actual_kernel_version"] != "8.30.5":
        raise ValueError("unexpected source identity")
    return lock, patch

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--git", default="git")
    parser.add_argument("--patch", default="patch")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    output = args.output.absolute()
    lock, patch = load_contract()
    head = subprocess.check_output([args.git, "-C", str(source), "rev-parse", "HEAD"], timeout=10).decode().strip()
    if head != lock["source_commit"]:
        raise ValueError("official source revision differs")
    verify_files(source, lock["files"], "before_sha256")
    output.mkdir(mode=0o700)  # Refuse all previous output, including symlinks.
    try:
        for name, entry in lock["files"].items():
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry["before_sha256"] is not None:
                target.write_bytes(regular_bytes(source / name))
        completed = subprocess.run([args.patch, "--batch", "--fuzz=0", "-p1", "-i", str(HERE / "texture-fill.patch")], cwd=output, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        (output / "patch.log").write_bytes(completed.stdout)
        if completed.returncode:
            raise ValueError("feature patch failed; private output retained")
        verify_files(output, lock["files"], "after_sha256")
        receipt = {"source_commit": head, "patch_sha256": digest(patch), "files": lock["files"], "overlay_only": True, "native_build": False, "feature_acceptance": False}
        (output / "prepared.json").write_text(json.dumps(receipt, indent=2) + "\n")
    except BaseException:
        # Preserve failed preparation evidence, never emit a success receipt.
        (output / "prepared.json").unlink(missing_ok=True)
        raise

if __name__ == "__main__":
    main()
