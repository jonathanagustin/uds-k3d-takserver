#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Inspect compiled consumer calls with javap; never initialize classes or load GL."""
import argparse
import subprocess


def verify(text):
    required = (
        "gov/nasa/worldwind/util/OGLTextRenderer.getOrCreateTextRenderer:",
        "gov/nasa/worldwind/render/TextRenderer.begin3DRendering:()V",
        "gov/nasa/worldwind/render/TextRenderer.setColor:(Ljava/awt/Color;)V",
        "gov/nasa/worldwind/render/TextRenderer.draw:(Ljava/lang/String;II)V",
        "gov/nasa/worldwind/render/TextRenderer.end3DRendering:()V",
    )
    if not all(call in text for call in required):
        raise ValueError("compiled consumer is missing required real NASA renderer calls")
    if "com/jogamp/opengl/util/awt/TextRenderer" in text:
        raise ValueError("compiled consumer still references JOGL TextRenderer")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classes", required=True)
    parser.add_argument("--javap", default="javap")
    args = parser.parse_args()
    result = subprocess.run([args.javap, "-classpath", args.classes, "-c", "-p",
                             "gov.takx.platform.globe.AOverlayLayer"],
                            check=True, capture_output=True, text=True, timeout=30)
    verify(result.stdout)
    print(result.stdout)


if __name__ == "__main__":
    main()
