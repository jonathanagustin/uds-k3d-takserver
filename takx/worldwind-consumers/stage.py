#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Stage the pinned production consumer slice with one explicit import patch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE,
                                   env=dict(os.environ, GIT_NO_LAZY_FETCH="1"), timeout=30)


def stage(source, output, lock, patch):
    """Reject changed consumed inputs; allow unrelated worktree changes."""
    source, output = Path(source).resolve(), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("output must not already exist")
    patch_bytes = patch.read_bytes()
    if digest(patch_bytes) != lock["patch_sha256"]:
        raise ValueError("patch hash mismatch")
    revision = git(source, "rev-parse", "HEAD").decode().strip()
    matches = [(name, p) for name, p in lock["profiles"].items() if p["revision"] == revision]
    if len(matches) != 1:
        raise ValueError("source revision is not a pinned TAKX profile")
    profile, definition = matches[0]
    frozen = {}
    for entry in definition["sources"]:
        rel = Path(entry["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("unsafe source path")
        path = source / rel
        if any(p.is_symlink() for p in [path, *path.parents]):
            raise ValueError("symlinked source is not accepted")
        committed = git(source, "show", f"{revision}:{rel.as_posix()}")
        if digest(committed) != entry["sha256"] or path.read_bytes() != committed:
            raise ValueError(f"source bytes differ from the pin: {rel}")
        frozen[rel] = committed
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".takx-consumers-", dir=output.parent) as temp:
        frozen_patch = Path(temp) / "consumer.patch"
        frozen_patch.write_bytes(patch_bytes)
        staged = Path(temp) / "sources"
        staged.mkdir()
        for rel, data in frozen.items():
            path = staged / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for flags in (["--check"], []):
            subprocess.run(["git", "apply", *flags, str(frozen_patch)], cwd=staged,
                           check=True, capture_output=True, timeout=30,
                           env=dict(os.environ, GIT_NO_LAZY_FETCH="1"))
        for entry in definition["sources"]:
            if digest((staged / entry["path"]).read_bytes()) != entry["staged_sha256"]:
                raise ValueError("patched source hash mismatch")
        receipt = {"profile": profile, "revision": revision,
                   "patch_sha256": lock["patch_sha256"], "sources": definition["sources"],
                   "native_or_client_acceptance": False}
        (staged / "staging-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        staged.rename(output)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads((HERE / "sources.lock.json").read_text())
    receipt = stage(args.source, args.output, lock, HERE.parent / "patches" / lock["patch"])
    print(json.dumps({"profile": receipt["profile"], "sources": len(receipt["sources"])}))


if __name__ == "__main__":
    main()
