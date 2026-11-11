#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Copy one Demo Video run's posters, stills and chapter times into the docs.

    demo/sync-assets.py RUN_ID

For a new capture use RUN_ID --capture-attempt N, then review a pull request
with the result. This selects demo-video-attempt-N; the legacy invocation selects
demo-video. It does not publish or change the selected release URL. It downloads
the capture artifact (needs gh) and:

- copies the two video posters and each chapter clip's poster to
  docs-site/public/demo/ (the clips themselves stay on the demo release; the
  docs site build copies them, see docs-site/scripts/sync-docs.mjs)
- copies the stills to docs-site/public/demo/screens/ as WebP
- rewrites the two chapter lists and lengths in the README's Demo section

The stills, the clips and the videos all come from the same recording, so
the docs cannot show a different version than the videos do.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "docs-site" / "public" / "demo"
SMALL = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"}


def title(text):
    """'2. Build the Zarf package: upstream chart' -> 'Build the Zarf Package'."""
    text = re.sub(r"^\d+\.\s*", "", text.strip()).split(":")[0].strip()
    words = text.split()
    return " ".join(
        w if (i and w.lower() in SMALL) or not w[:1].islower() or any(c.isdigit() for c in w) else w[:1].upper() + w[1:]
        for i, w in enumerate(words)
    )


def chapters(path):
    """Chapter lines for the README: '- m:ss Title'.

    Leaves out the opening title card, the closing repository card, and the
    captions inside a chapter, except the numbered deploy steps.
    """
    out = []
    for line in path.read_text().splitlines():
        match = re.match(r"^(\d+):(\d+(?:\.\d+)?) (\s*)(.+)$", line)
        if not match:
            continue
        minutes, seconds, indent, name = int(match.group(1)), int(float(match.group(2))), match.group(3), match.group(4)
        if (minutes, seconds) == (0, 0) or name.startswith("github.com/"):
            continue
        if indent and not re.match(r"\d+\.", name):
            continue
        # Card titles are already title case; deploy step captions are not.
        out.append(f"- {minutes}:{seconds:02d} {title(name) if indent else name}")
    return out


def duration(video):
    seconds = float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
            check=True, capture_output=True, text=True,
        ).stdout
    )
    return max(1, round(seconds / 60))


def update_readme(section, chapter_lines, minutes):
    readme = ROOT / "README.md"
    text = readme.read_text()
    start = text.index(f"### {section}\n")
    end = text.index("[Download", start)
    block = text[start:end]
    block = re.sub(r"\d+ min\.", f"{minutes} min.", block, count=1)
    block = re.sub(
        r"(<summary>Chapters</summary>\n\n)(.*?)(\n\n</details>)",
        lambda m: m.group(1) + "\n".join(chapter_lines) + m.group(3),
        block,
        count=1,
        flags=re.S,
    )
    readme.write_text(text[:start] + block + text[end:])


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id')
    parser.add_argument('--capture-attempt', default='')
    args = parser.parse_args()
    run_id = args.run_id
    if not re.fullmatch(r'[1-9][0-9]*', run_id) or (args.capture_attempt and not re.fullmatch(r'[1-9][0-9]*', args.capture_attempt)):
        raise SystemExit('Expected positive run and capture attempt IDs')
    artifact = 'demo-video-attempt-' + args.capture_attempt if args.capture_attempt else 'demo-video'
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["gh", "run", "download", run_id, "--repo", "jonathanagustin/uds-takserver",
             "--name", artifact, "--dir", tmp],
            check=True,
        )
        art = Path(tmp)
        (PUBLIC / "screens").mkdir(parents=True, exist_ok=True)
        for name in ("demo-deploy.jpg", "demo-operate-and-trust.jpg"):
            shutil.copy(art / name, PUBLIC / name)
        for poster in sorted((art / "clips").glob("demo-clip-*.jpg")):
            shutil.copy(poster, PUBLIC / poster.name)
            print(f"poster {poster.name}")
        for still in sorted((art / "shots").glob("*.webp")):
            shutil.copy(still, PUBLIC / "screens" / still.name)
            print(f"still screens/{still.name}")
        update_readme("Deploy", chapters(art / "demo-chapters.txt"), duration(art / "demo.mp4"))
        update_readme("Operate and Trust", chapters(art / "demo-operate-chapters.txt"), duration(art / "demo-operate.mp4"))
    print("README chapters updated. The README players are GitHub user-attachments:")
    print("drag the new demo-deploy.mp4 and demo-operate-and-trust.mp4 into a GitHub comment box")
    print("and replace the two https://github.com/user-attachments/assets/ lines with the new URLs.")


if __name__ == "__main__":
    main()
