#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Validate proposed Lula mappings and complete, declared source marker pairs."""

import re
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import yaml

MARKER = re.compile(r"^\s*(?:#|//|<!--)\s*@lula(Start|End)\s+(\S+)(?:\s*-->)?\s*$")


def check(root):
    root = Path(root).resolve()
    errors = []
    controls = {}
    mappings = {}
    for path in sorted((root / "compliance/controls").glob("*/*.yaml")):
        data = yaml.safe_load(path.read_text())
        identifier = data.get("id") if isinstance(data, dict) else None
        if not identifier or identifier in controls:
            errors.append(f"{path.relative_to(root)}: missing or duplicate control id")
            continue
        controls[identifier] = data
        for field in ("title", "family", "implementation_status", "control_implementation_narrative", "assessment_procedures"):
            if not data.get(field):
                errors.append(f"{identifier}: missing {field}")
        if not data.get("links"):
            errors.append(f"{identifier}: missing evidence links")
    if not controls:
        errors.append("no control definitions found")
    for path in sorted((root / "compliance/mappings").glob("*/*-mappings.yaml")):
        entries = yaml.safe_load(path.read_text())
        if not isinstance(entries, list) or not entries:
            errors.append(f"{path.relative_to(root)}: expected a nonempty mapping list")
            continue
        for mapping in entries:
            if not isinstance(mapping, dict):
                errors.append(f"{path.relative_to(root)}: mapping entries must be objects")
                continue
            identifier = mapping.get("uuid", "")
            try:
                if str(UUID(identifier)) != identifier:
                    raise ValueError("not a canonical UUID")
            except (ValueError, TypeError, AttributeError):
                errors.append(f"{path.relative_to(root)}: invalid mapping UUID {identifier!r}")
                continue
            if identifier in mappings:
                errors.append(f"duplicate mapping UUID {identifier}")
                continue
            if mapping.get("control_id") not in controls:
                errors.append(f"{identifier}: unknown control {mapping.get('control_id')}")
            if mapping.get("status") not in {"planned", "implemented", "verified"}:
                errors.append(f"{identifier}: invalid mapping status")
            if not mapping.get("justification"):
                errors.append(f"{identifier}: missing mapping justification")
            sources = set()
            for entry in mapping.get("source_entries") or []:
                location = entry.get("location") if isinstance(entry, dict) else None
                if not isinstance(location, str) or Path(location).is_absolute() or ".." in Path(location).parts:
                    errors.append(f"{identifier}: source must be a repository-relative path")
                    continue
                source = root / location
                if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(root):
                    errors.append(f"{identifier}: mapped file does not exist or is unsafe: {location}")
                sources.add(location)
            if not sources:
                errors.append(f"{identifier}: no mapped source files")
            mappings[identifier] = {"control": mapping.get("control_id"), "sources": sources}
    mapped_controls = {mapping["control"] for mapping in mappings.values()}
    for control in controls.keys() - mapped_controls:
        errors.append(f"{control}: no source mapping")
    # Include untracked files so local validation cannot overlook a newly added
    # source marker. Ignored build outputs and dependencies are not scanned.
    names = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           cwd=root, check=True, capture_output=True).stdout.decode().split("\0")
    pairs = set()
    for name in sorted(set(names) - {""}):
        source = root / name
        if source.is_symlink() or not source.is_file():
            continue
        try:
            lines = source.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        stack = []
        for line_number, line in enumerate(lines, 1):
            match = MARKER.fullmatch(line)
            if not match:
                continue
            kind, identifier = match.groups()
            if identifier not in mappings:
                errors.append(f"{name}:{line_number}: unknown marker UUID {identifier}")
            elif name not in mappings[identifier]["sources"]:
                errors.append(f"{name}:{line_number}: UUID {identifier} is not mapped to this file")
            if kind == "Start":
                if identifier in stack:
                    errors.append(f"{name}:{line_number}: nested duplicate start for {identifier}")
                stack.append(identifier)
            elif not stack or stack[-1] != identifier:
                errors.append(f"{name}:{line_number}: unmatched or crossing end for {identifier}")
            else:
                stack.pop()
                pairs.add((identifier, name))
        for identifier in stack:
            errors.append(f"{name}: missing end marker for {identifier}")
    for identifier, mapping in mappings.items():
        for source in mapping["sources"]:
            if (identifier, source) not in pairs:
                errors.append(f"{identifier}: no complete marker pair in {source}")
    return errors


if __name__ == "__main__":
    try:
        problems = check(Path(__file__).resolve().parents[2])
    except (OSError, yaml.YAMLError, subprocess.CalledProcessError) as error:
        print(f"compliance: cannot validate inputs: {error}", file=sys.stderr)
        sys.exit(1)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit(1)
    print("compliance: controls, mappings, and source marker pairs are valid")
