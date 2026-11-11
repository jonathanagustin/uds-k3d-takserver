#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Validate synthetic mission input; optionally stage it for manual import on a real ATAK device."""
import argparse
import hashlib
import json
import stat
from pathlib import Path, PurePosixPath
import subprocess
import xml.etree.ElementTree as ET
import zipfile

LIMIT = 1024 * 1024


def inspect_package(path):
    if path.stat().st_size > LIMIT:
        raise ValueError("scenario package exceeds 1 MiB")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or len(names) > 32:
            raise ValueError("duplicate or excessive entries")
        for entry in entries:
            name = entry.orig_filename
            parts = name.split("/")
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if (name != entry.filename or "\\" in name or ":" in name
                    or any(ord(c) < 32 or ord(c) == 127 for c in name)
                    or PurePosixPath(name).is_absolute()
                    or any(part in ("", ".", "..") for part in parts)):
                raise ValueError("unsafe member path")
            if entry.flag_bits & 1 or kind not in (0, stat.S_IFREG):
                raise ValueError("encrypted or special ZIP entry")
            if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError("unsupported ZIP compression")
        if sum(e.file_size for e in entries) > LIMIT:
            raise ValueError("expanded package exceeds 1 MiB")
        manifest_bytes = archive.read("MANIFEST/manifest.xml")
        if b"<!DOCTYPE" in manifest_bytes.upper():
            raise ValueError("DTD is not allowed")
        manifest = ET.fromstring(manifest_bytes)
        if manifest.tag != "MissionPackageManifest" or manifest.get("version") != "2":
            raise ValueError("expected MissionPackageManifest version 2")
        # This is admission for our synthetic scenario, not a replacement
        # implementation of the official generic mission package reader.
        contents = manifest.findall("Contents/Content")
        references = [content.get("zipEntry") for content in contents]
        payloads = set(names) - {"MANIFEST/manifest.xml"}
        if (len(references) != len(set(references)) or set(references) != payloads
                or any(content.get("ignore", "false") != "false" for content in contents)):
            raise ValueError("scenario manifest must list each existing payload exactly once")
        cot_names = [n for n in names if n.endswith(".cot")]
        if not cot_names or "files/README.txt" not in references:
            raise ValueError("scenario needs a CoT marker and README attachment")
        for content in contents:
            parameters = {p.get("name"): p.get("value") for p in content.findall("Parameter")}
            if (content.get("zipEntry").endswith(".cot")
                    and parameters.get("isCoT") != "true"):
                raise ValueError("CoT payload must declare isCoT=true")
        markers = []
        for name in cot_names:
            payload = archive.read(name)
            if b"<!DOCTYPE" in payload.upper():
                raise ValueError("DTD is not allowed")
            event = ET.fromstring(payload)
            uid = event.get("uid", "")
            contact = event.find("detail/contact")
            point = event.find("point")
            if (event.tag != "event" or not uid.startswith("synthetic-")
                    or contact is None or "TEST" not in contact.get("callsign", "")
                    or point is None):
                raise ValueError("every marker must be explicitly synthetic and TEST labelled")
            lat, lon = float(point.get("lat")), float(point.get("lon"))
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("invalid coordinates")
            markers.append({"uid": uid, "callsign": contact.get("callsign"), "lat": lat, "lon": lon})
    return {"package_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "markers": markers}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission-package", required=True, type=Path)
    parser.add_argument("--device", help="explicit already-provisioned adb serial; absent means offline validation only")
    parser.add_argument("--output", required=True, type=Path, help="fresh evidence directory")
    args = parser.parse_args()
    receipt = inspect_package(args.mission_package)
    args.output.mkdir(parents=True, exist_ok=False)
    receipt.update(status="offline-input-valid", execution="not-run")
    try:
        if args.device:
            def adb(*command):
                return subprocess.run(["adb", "-s", args.device, *command], check=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45).stdout
            if adb("get-state").strip() != b"device":
                raise RuntimeError("adb device is not ready")
            package = "com.atakmap.app.civ"
            installed = adb("shell", "pm", "path", package).decode().strip()
            if not installed.startswith("package:"):
                raise RuntimeError("ATAK-CIV must already be installed")
            receipt["apk_path"] = installed
            # Stage the file only. Startup is not an import acknowledgement.
            # The existing driver uses a restart plus interactive prompt taps;
            # we do not infer that arbitrary packages are auto-imported.
            adb("shell", "mkdir", "-p", "/sdcard/Download")
            adb("push", str(args.mission_package), "/sdcard/Download/atak-synthetic-scenario.dpk")
            adb("shell", "uiautomator", "dump", "/sdcard/android-scenario-ui.xml")
            (args.output / "ui.xml").write_bytes(adb("exec-out", "cat", "/sdcard/android-scenario-ui.xml"))
            (args.output / "screen.png").write_bytes(adb("exec-out", "screencap", "-p"))
            receipt.update(status="staged-for-manual-import", execution="real-adb",
                           remaining=["open ATAK Import and select Download/atak-synthetic-scenario.dpk", "accept import prompts", "verify synthetic map marker", "share to connected peer and verify UID/coordinates", "verify mission attachment on device"])
    except Exception as error:
        receipt.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
