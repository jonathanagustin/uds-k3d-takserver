#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Build a project GDAL data JAR using one hash-locked public source archive."""

import argparse
import fnmatch
import hashlib
import json
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "resources.lock.json"
MANIFEST = (
    "Manifest-Version: 1.0\r\n"
    "Implementation-Title: uds-takserver GDAL data resources\r\n"
    "Implementation-Version: 0.1.0\r\n"
    "GDAL-Source-Version: 2.4.4\r\n\r\n"
).encode("ascii")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def checked_member(archive, name, expected):
    members = [member for member in archive.getmembers() if member.name == name]
    if len(members) != 1 or not members[0].isfile():
        raise ValueError(f"Expected one regular source member: {name}")
    member = members[0]
    if member.size != expected["bytes"]:
        raise ValueError(f"Source member size mismatch: {name}")
    with archive.extractfile(member) as stream:
        data = stream.read()
    if sha256(data) != expected["sha256"]:
        raise ValueError(f"Source member SHA-256 mismatch: {name}")
    return data


def source_resources(path, lock):
    # Verify the whole archive before parsing it or creating any output.
    if path.stat().st_size != lock["archive"]["bytes"]:
        raise ValueError("GDAL source archive size mismatch")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != lock["archive"]["sha256"]:
            raise ValueError("GDAL source archive SHA-256 mismatch")
    shared = json.loads((ROOT.parent / "sources.lock.json").read_text())
    for key in ("url", "sha256", "bytes"):
        if shared["archives"]["gdal"][key] != lock["archive"][key]:
            raise ValueError("GDAL resource and Java recipes no longer share the locked source")
    with tarfile.open(path, "r:gz") as archive:
        notices = {name: checked_member(archive, name, expected)
                   for name, expected in lock["source_notices"].items()}
        if lock["selection"]["source_install_statement"] not in notices["./gdal/GNUmakefile"].decode():
            raise ValueError("Public source install manifest does not establish the declared resource selection")
        prefix = lock["selection"]["directory"]
        names = []
        for member in archive.getmembers():
            if not member.name.startswith(prefix):
                continue
            name = member.name.removeprefix(prefix)
            if "/" in name or name.startswith(".") or not fnmatch.fnmatchcase(name, lock["selection"]["glob"]):
                continue
            if not member.isfile():
                raise ValueError("Data install selection contains a non-regular member")
            names.append(name)
        if len(names) != len(set(names)) or set(names) != set(lock["resources"]):
            raise ValueError("Public source install selection differs from the locked resource inventory")
        data = {name: checked_member(archive, prefix + name, expected)
                for name, expected in sorted(lock["resources"].items())}
        license_text = notices["./gdal/LICENSE.TXT"]
    # The public native packaging recipe lists data-directory names, including
    # the index itself because shell redirection creates it before `ls -1`.
    data["gdaldata.files"] = "".join(name + "\n" for name in sorted([*data, "gdaldata.files"])).encode("ascii")
    return data, license_text


def build(archive_path, output):
    lock = json.loads(LOCK.read_text())
    data, license_text = source_resources(archive_path, lock)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    jar = output / lock["project_artifact"]
    entries = {"gdal/data/" + name: value for name, value in data.items()}
    entries.update({"META-INF/MANIFEST.MF": MANIFEST,
                    "META-INF/licenses/GDAL-LICENSE.txt": license_text})
    # STORED entries avoid zlib-version differences. Timestamps, permissions,
    # platform markers, ordering and manifest bytes are explicitly fixed.
    with zipfile.ZipFile(jar, "w", compression=zipfile.ZIP_STORED) as target:
        for name, value in sorted(entries.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            target.writestr(info, value)
    (output / "GDAL-LICENSE.txt").write_bytes(license_text)
    receipt = {
        "schema": 1, "scope": lock["scope"],
        "source": {"repository": lock["repository"], "revision": lock["revision"],
                   "archive": lock["archive"]},
        "recipe_sha256": sha256(Path(__file__).read_bytes()),
        "lock_sha256": sha256(LOCK.read_bytes()),
        "source_install_manifest": lock["source_notices"]["./gdal/GNUmakefile"],
        "resources": {name: {"sha256": sha256(value), "bytes": len(value)}
                      for name, value in sorted(data.items())},
        "artifact": {"file": jar.name, "sha256": sha256(jar.read_bytes()), "bytes": jar.stat().st_size},
        "license_sha256": sha256(license_text),
        "native_or_client_acceptance": False,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Built {jar.name}: {len(data)} project resource entries; no native code")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="official GDAL source archive from the existing GIS Java lock")
    parser.add_argument("--output", type=Path, required=True, help="new empty output directory")
    args = parser.parse_args()
    build(args.archive.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
