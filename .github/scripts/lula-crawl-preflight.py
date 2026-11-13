# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Fail closed before an explicitly authorized pinned Lula comment crawl."""
import argparse
import base64
import json
from pathlib import Path
import re
import sys


class UnsupportedFileCount(ValueError):
    pass


def validate(pr, baseline, repository):
    if pr.get("state") != "open" or pr.get("draft") is not False:
        raise ValueError("crawl requires an open, non-draft PR")
    if pr.get("head", {}).get("repo", {}).get("full_name") != repository:
        raise ValueError("crawl requires a same-repository PR")
    if pr.get("base", {}).get("ref") != "main":
        raise ValueError("crawl requires a main-target PR")
    count = pr.get("changed_files")
    if type(count) is not int or count < 0:
        raise ValueError("Lula 0.9.5 cannot cover more than 30 changed files")
    if (baseline.get("type") != "file" or baseline.get("encoding") != "base64"
            or baseline.get("path") != "charts/takserver/files/config/CoreConfig.xml"):
        raise ValueError("crawl requires the existing mapped baseline")
    contents = base64.b64decode(baseline.get("content", "").replace("\n", ""), validate=True)
    # Substrings alone do not prove an existing block: reversed markers or
    # marker text inside an XML value would pass without a crawler-visible pair.
    marker = rb"0ba6e9e4-4061-5ff4-9c29-69bffbd3a489"
    pattern = rb"^\s*<!--\s*@lula(Start|End)\s+" + marker + rb"\s*-->\s*$"
    opened = False
    pairs = 0
    for kind in re.findall(pattern, contents, re.MULTILINE):
        if (kind == b"Start") == opened:
            raise ValueError("crawl requires the existing mapped baseline")
        opened = kind == b"Start"
        pairs += kind == b"End"
    if opened or not pairs:
        raise ValueError("crawl requires the existing mapped baseline")
    if count > 30:
        raise UnsupportedFileCount("Lula 0.9.5 cannot cover more than 30 changed files")


def snapshot(pr, repository):
    """Bind validated sources; the crawler refuses a changed PR before posting."""
    shas = [pr.get(side, {}).get("sha") for side in ["base", "head"]]
    if any(not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in shas):
        raise ValueError("crawl requires exact source commits")
    return {"repository": repository, "baseSHA": shas[0], "headSHA": shas[1],
            "changedFiles": pr["changed_files"]}


def evaluate(pr, baseline, repository, automatic=False):
    binding = snapshot(pr, repository)
    try:
        validate(pr, baseline, repository)
    except UnsupportedFileCount:
        if automatic:
            return None
        raise
    return binding


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("repository")
    parser.add_argument("binding", type=Path, nargs="?")
    parser.add_argument("--automatic", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        with args.pr.open() as source:
            pr = json.load(source)
        with args.baseline.open() as source:
            baseline = json.load(source)
        binding = evaluate(pr, baseline, args.repository, args.automatic)
        if binding is None:
            print("Lula automatic crawl skipped: unsupported_changed_file_count")
        elif args.binding:
            with args.binding.open("x") as output:
                json.dump(binding, output)
        if binding is not None:
            print("Lula source binding: " + json.dumps(binding, sort_keys=True))
        if args.github_output:
            with args.github_output.open("a") as output:
                output.write("ready=" + ("true" if binding is not None else "false") + "\n")
    except (ValueError, KeyError, IndexError) as error:
        sys.exit(str(error))
