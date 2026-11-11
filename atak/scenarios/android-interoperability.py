#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Validate synthetic mission input; optionally request its import on a real ATAK device."""
import argparse
import hashlib
import json
from pathlib import Path
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
        if any(Path(n).is_absolute() or ".." in Path(n).parts for n in names):
            raise ValueError("unsafe member path")
        if sum(e.file_size for e in entries) > LIMIT:
            raise ValueError("expanded package exceeds 1 MiB")
        manifest_bytes = archive.read("MANIFEST/manifest.xml")
        if b"<!DOCTYPE" in manifest_bytes.upper():
            raise ValueError("DTD is not allowed")
        manifest = ET.fromstring(manifest_bytes)
        if manifest.tag != "MissionPackageManifest" or manifest.get("version") != "2":
            raise ValueError("expected MissionPackageManifest version 2")
        cot_names = [n for n in names if n.endswith(".cot")]
        if not cot_names:
            raise ValueError("scenario needs a CoT map marker")
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
            # Same import mechanism as atak/driver/drive.sh. No install, network
            # provisioning, permission bypass, recording, or UI success inference.
            adb("shell", "mkdir", "-p", "/sdcard/Download")
            adb("push", str(args.mission_package), "/sdcard/Download/atak-synthetic-scenario.dpk")
            adb("shell", "am", "force-stop", package)
            adb("shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
            adb("shell", "uiautomator", "dump", "/sdcard/android-scenario-ui.xml")
            (args.output / "ui.xml").write_bytes(adb("exec-out", "cat", "/sdcard/android-scenario-ui.xml"))
            (args.output / "screen.png").write_bytes(adb("exec-out", "screencap", "-p"))
            receipt.update(status="import-requested-unverified", execution="real-adb",
                           remaining=["accept import prompts", "verify both map markers", "share to connected peer and verify UID/coordinates", "verify mission attachment on device"])
    except Exception as error:
        receipt.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
