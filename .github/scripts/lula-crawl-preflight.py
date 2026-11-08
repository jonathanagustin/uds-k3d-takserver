# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Fail closed before an explicitly authorized pinned Lula comment crawl."""
import base64
import json
import sys


def validate(pr, baseline, repository):
    if pr.get("state") != "open" or pr.get("draft"):
        raise ValueError("crawl requires an open, non-draft PR")
    if pr.get("head", {}).get("repo", {}).get("full_name") != repository:
        raise ValueError("crawl requires a same-repository PR")
    count = pr.get("changed_files")
    if type(count) is not int or not 0 <= count <= 30:
        raise ValueError("Lula 0.9.5 cannot cover more than 30 changed files")
    if baseline.get("type") != "file" or baseline.get("encoding") != "base64":
        raise ValueError("crawl requires the existing mapped baseline")
    contents = base64.b64decode(baseline.get("content", "").replace("\n", ""), validate=True)
    marker = b"0ba6e9e4-4061-5ff4-9c29-69bffbd3a489"
    if b"@lulaStart " + marker not in contents or b"@lulaEnd " + marker not in contents:
        raise ValueError("crawl requires the existing mapped baseline")


if __name__ == "__main__":
    try:
        with open(sys.argv[1]) as source:
            pr = json.load(source)
        with open(sys.argv[2]) as source:
            baseline = json.load(source)
        validate(pr, baseline, sys.argv[3])
    except (ValueError, KeyError, IndexError) as error:
        sys.exit(str(error))
