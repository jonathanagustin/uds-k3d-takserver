#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Acquire hash-locked historical footage and render a bounded UI preview."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "inputs.lock.json"
MAX_DOWNLOAD = 256 * 1024 * 1024
SCENES = (
    ("CloudTAK map", "demo-clip-cloudtak-user.mp4", 27, 4),
    ("Create a map marker", "demo-clip-sync.mp4", 43.5, 6),
    ("Share a feature", "demo-clip-sync.mp4", 58, 6.5),
    ("TAK Server status", "demo-clip-sso.mp4", 18.3, 3.5),
    ("Shared marker", "demo-clip-sync.mp4", 74, 6),
)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(path, expected):
    if not path.is_file() or digest(path) != expected:
        raise ValueError(f"SHA-256 mismatch: {path.name}; input was not accepted")


def acquire(item, cache):
    """Never use a changed cached file or replace it silently with a download."""
    path = cache / item["file"]
    if path.exists():
        verify(path, item["sha256"])
        return path
    request = urllib.request.Request(item["url"], headers={"User-Agent": "uds-takserver-ui-reel"})
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as temporary:
        staging = Path(temporary.name)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.geturl().split(":", 1)[0] != "https":
                    raise ValueError("Input redirected away from HTTPS")
                count = 0
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > MAX_DOWNLOAD:
                        raise ValueError("Input exceeds the 256 MiB acquisition limit")
                    temporary.write(chunk)
            temporary.flush()
            verify(staging, item["sha256"])
            staging.replace(path)
        finally:
            staging.unlink(missing_ok=True)
    return path


def tool_version(name):
    return subprocess.check_output([name, "-version"], text=True).splitlines()[0]


def run(command, directory):
    subprocess.run(command, cwd=directory, check=True, timeout=180)


def render(cache, output, offline=False):
    lock = json.loads(LOCK.read_text())
    cache.mkdir(parents=True, exist_ok=True)
    items = [*lock["sources"], lock["font"]]
    for item in items:
        if offline:
            verify(cache / item["file"], item["sha256"])
        else:
            acquire(item, cache)
    versions = {name: tool_version(name) for name in ("ffmpeg", "ffprobe")}
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be empty; use a new directory for each edit")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ui-reel-") as temporary:
        work = Path(temporary)
        with zipfile.ZipFile(cache / lock["font"]["file"]) as archive:
            for name, member in lock["font"]["members"].items():
                if archive.getinfo(member).file_size > 2 * 1024 * 1024:
                    raise ValueError("Font archive member exceeds the 2 MiB limit")
                (work / name).write_bytes(archive.read(member))
        for index, (label, name, start, length) in enumerate(SCENES):
            # Relative, fixed names prevent FFmpeg filter/concat path escaping.
            filters = [
                "crop=1632:784:144:134", "scale=1856:-2:flags=lanczos",
                "pad=1920:1080:32:112:color=0x0B1220",
                "drawtext=fontfile=font-title.ttf:text='TAK Server on UDS':fontsize=30:fontcolor=0xF8FAFC:x=40:y=32",
                f"drawtext=fontfile=font-label.ttf:text='{label}':fontsize=25:fontcolor=0x22D3EE:x=w-tw-40:y=35",
                "drawtext=fontfile=font-label.ttf:text='UI EDIT PREVIEW  /  RECORDED DEMO FOOTAGE':fontsize=17:fontcolor=0x94A3B8:x=40:y=1033",
                "fade=t=in:st=0:d=0.12", f"fade=t=out:st={length-.12}:d=0.12",
                "fps=30", "format=yuv420p",
            ]
            run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", str(cache / name),
                 "-t", str(length), "-an", "-vf", ",".join(filters), "-filter_threads", "2",
                 "-threads", "2", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                 f"part{index}.mp4"], work)
        (work / "parts.txt").write_text("".join(f"file 'part{i}.mp4'\n" for i in range(len(SCENES))))
        video = output / "uds-takserver-ui-preview.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "1", "-i", "parts.txt",
             "-c", "copy", "-movflags", "+faststart", str(video)], work)
        run(["ffmpeg", "-v", "error", "-y", "-ss", "5", "-i", str(video), "-frames:v", "1",
             str(output / "poster.jpg")], work)
        run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf",
             "fps=5/26,scale=480:-1,tile=5x1", "-frames:v", "1", str(output / "review-strip.jpg")], work)
        shutil.copyfile(work / "Inter-LICENSE.txt", output / "Inter-LICENSE.txt")
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
        "-of", "json", str(video)], text=True))
    streams = probe["streams"]
    if (len(streams) != 1 or streams[0].get("codec_type") != "video"
            or streams[0].get("codec_name") != "h264"
            or (streams[0].get("width"), streams[0].get("height")) != (1920, 1080)
            or abs(float(probe["format"]["duration"]) - 26) > .05):
        raise ValueError("Output failed the 26-second, silent 1080p H.264 contract")
    manifest = {
        "purpose": lock["description"], "source_inputs": lock,
        "recipe_sha256": digest(Path(__file__)), "lock_sha256": digest(LOCK),
        "tool_versions": versions,
        "scenes": [{"label": label, "source": name, "start_seconds": start, "duration_seconds": length}
                   for label, name, start, length in SCENES],
        "outputs": [{"file": path.name, "sha256": digest(path), "bytes": path.stat().st_size}
                    for path in sorted(output.iterdir()) if path.is_file()],
        "probe": probe,
        "acceptance": "Historical footage edit only; no new deployment, TAKX, or live interoperability acceptance",
    }
    (output / "edit-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Rendered {video.name}: 26 seconds, 1920x1080, recorded footage")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT.parent / "out/ui-reel-inputs")
    parser.add_argument("--output", type=Path, default=ROOT.parent / "out/ui-reel")
    parser.add_argument("--offline", action="store_true", help="require all locked inputs in cache; never download")
    args = parser.parse_args()
    render(args.cache.resolve(), args.output.resolve(), args.offline)


if __name__ == "__main__":
    main()
