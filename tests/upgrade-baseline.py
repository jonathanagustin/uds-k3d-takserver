#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Resolve a published Release Please version reachable from main, never a dev tag."""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path


VERSION = re.compile(r"^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def releases(repository):
    page = 1
    while True:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}",
            headers={"Accept": "application/vnd.github+json"},
        )
        if os.environ.get("GH_TOKEN"):
            request.add_header("Authorization", "Bearer " + os.environ["GH_TOKEN"])
        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise RuntimeError("Release API did not return a release list")
        yield from batch
        if len(batch) < 100:
            return
        page += 1


def select_release(items):
    candidates = []
    for release in items:
        tag = release.get("tag_name", "")
        match = VERSION.fullmatch(tag)
        if not match or release.get("draft") or release.get("prerelease"):
            continue
        if not release.get("published_at"):
            continue
        candidates.append((tuple(map(int, match.groups())), tag, match))
    if not candidates:
        stable_tags = [tag for tag in git("tag", "--list").splitlines() if VERSION.fullmatch(tag)]
        if stable_tags:
            raise RuntimeError("Stable Git tags exist but no published Release Please release is available")
        return None
    _, tag, match = max(candidates, key=lambda candidate: candidate[0])
    ref = f"refs/tags/{tag}"
    # Never fall back to an older release if the latest baseline is invalid.
    commit = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "refs/remotes/origin/main"],
        check=True, capture_output=True,
    )
    manifest = json.loads(git("show", f"{ref}:.release-please-manifest.json"))
    version = ".".join(match.groups())
    if manifest.get(".") != version:
        raise RuntimeError(f"Release {tag} does not match its Release Please manifest")
    return {
        "tag": tag,
        "version": version,
        "commit": commit,
        "package": f"oci://ghcr.io/jonathanagustin/uds-k3d-takserver/takserver:{version}-upstream",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repository = os.environ.get("GITHUB_REPOSITORY", "jonathanagustin/uds-k3d-takserver")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise RuntimeError("Invalid repository name")
    subprocess.run(["git", "fetch", "origin", "main", "--tags"], check=True)
    baseline = select_release(releases(repository))
    args.output.write_text(json.dumps(baseline) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"available={str(baseline is not None).lower()}\n")
    if baseline is None:
        notice = "no released baseline yet; upgrade test not run"
        print(f"::notice::{notice}")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                summary.write(notice + "\n")
        return
    print(f"Upgrade baseline: {baseline['tag']} ({baseline['commit']})")
    print(f"Released package: {baseline['package']}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError, ValueError) as error:
        print(f"::error title=Upgrade baseline unavailable::{error}", file=sys.stderr)
        sys.exit(1)
