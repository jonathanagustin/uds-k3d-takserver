#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compile the complete pinned public Kernel port module with real desktop adapters.

This opt-in, local test neither downloads inputs nor initializes native libraries.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REVISION = "9f6893dd657feacc35ec5de03dad721c2e44170e"
PATCH_NAME = "0001-kernel-remove-unused-colorfilter-import.patch"
PATCH_HASH = "dfafe9c5c670e4a2d62194ac1d6722e1b77b4e94d0d9ec494af6193c88cea2dc"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Clean pinned official ATAK checkout")
    parser.add_argument("--classpath-dir", type=Path, required=True, help="The five locked public JARs")
    parser.add_argument("--parcel-consumer", action="store_true", help="Also roundtrip the unchanged Kernel Icon consumer")
    args = parser.parse_args()
    source = args.source.resolve()
    observed = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if observed != REVISION:
        parser.error("ATAK source revision differs from the pinned public source")
    modules = ["takkernel/annotation/src/main/java", "takkernel/port/src/main/java", "takkernel/port/src/jre/java"]
    if args.parcel_consumer:
        modules.append("takkernel/engine/src/main/java/com/atakmap/coremap/maps/assets/Icon.java")
    subprocess.run(["git", "-C", str(source), "diff", "--exit-code", "HEAD", "--", *modules], check=True)
    untracked = subprocess.check_output(
        ["git", "-C", str(source), "ls-files", "--others", "--exclude-standard", "--", *modules], text=True
    )
    if untracked.strip():
        parser.error("Unexpected untracked files in consumed upstream source directories")
    jars = []
    lock = json.loads((HERE / "port-classpath.lock.json").read_text())
    for name, entry in lock.items():
        jar = args.classpath_dir.resolve() / name
        if not jar.is_file() or sha256(jar) != entry["sha256"]:
            parser.error(f"Missing or mismatched locked classpath input: {name}")
        jars.append(str(jar))
    patch = ROOT / "takx/patches" / PATCH_NAME
    if sha256(patch) != PATCH_HASH:
        parser.error("Kernel source patch differs from the reviewed test input")
    tracked = subprocess.check_output(
        ["git", "-C", str(source), "ls-files", "-z", "--", *modules]
    ).decode().split("\0")
    java_paths = [Path(name) for name in tracked if name.endswith(".java")]
    if len(java_paths) != 83 + int(args.parcel_consumer):
        parser.error("Expected all 77 port and six annotation source files")
    with tempfile.TemporaryDirectory(prefix="uds-takx-port-") as temporary:
        stage = Path(temporary)
        for relative in java_paths:
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, destination)
        subprocess.run(
            ["patch", "--batch", "--fuzz=0", "-p1", "-i", str(patch)],
            cwd=stage, check=True, stdout=subprocess.DEVNULL
        )
        upstream = sorted(p for module in modules[:3] for p in (stage / module).rglob("*.java"))
        compat = sorted((HERE / "src/main/java").rglob("*.java"))
        consumer_inputs = []
        if args.parcel_consumer:
            consumer_inputs = [str(stage / modules[-1]), str(HERE / "src/test/java/ParcelCompatibilityTest.java")]
        classes = stage / "classes"
        classes.mkdir()
        subprocess.run(
            ["javac", "--release", "11", "-cp", os.pathsep.join(jars), "-d", str(classes),
             *map(str, upstream), *map(str, compat), *consumer_inputs,
             str(HERE / "src/test/java/PortRuntimeTest.java")], check=True
        )
        runtime = subprocess.check_output(
            ["java", "-Djava.awt.headless=true", "-cp", os.pathsep.join([str(classes), *jars]),
             "PortRuntimeTest"], text=True
        ).strip()
        parcel_runtime = None
        if args.parcel_consumer:
            parcel_runtime = subprocess.check_output(
                ["java", "-cp", os.pathsep.join([str(classes), *jars]), "ParcelCompatibilityTest"], text=True).strip()
        print(json.dumps({
            "parcel_icon_runtime": parcel_runtime,
            "atak_revision": observed,
            "upstream_java_files": len(upstream),
            "compat_java_files": len(compat),
            "classpath_sha256": {name: entry["sha256"] for name, entry in lock.items()},
            "patch_sha256": sha256(patch),
            "compat_sha256": {str(p.relative_to(HERE)): sha256(p) for p in compat},
            "java_release": 11,
            "complete_public_port_java_compile": "pass",
            "port_utilities_runtime": runtime,
            "native_rendering_or_full_client_acceptance": False,
        }, indent=2))


if __name__ == "__main__":
    main()
