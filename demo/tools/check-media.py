#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Render a short synthetic clip through the real terminal and branded frame pipeline."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

DEMO = Path(__file__).resolve().parents[1]


def check(output):
    output.mkdir()
    version = subprocess.check_output(['agg', '--version'], text=True, timeout=10).strip()
    if version != 'agg 1.9.0':
        raise ValueError('unexpected terminal renderer')
    sys.path.insert(0, str(DEMO))
    spec = importlib.util.spec_from_file_location('checked_renderer', DEMO/'render-cast.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    cast = output/'synthetic.cast'
    rows = [{'version':2, 'width':132, 'height':34},
            [0, 'o', renderer.PROMPT+'printf media-preflight\r\n'],
            [.2, 'o', 'UDS TAK Server media preflight\r\n'],
            [.4, 'o', renderer.PROMPT]]
    cast.write_text('\n'.join(json.dumps(row) for row in rows)+'\n')
    prefix = output/'clip'
    subprocess.run([sys.executable, str(DEMO/'render-cast.py'), str(cast), str(prefix), 'Media preflight::1'],
                   env={**os.environ, 'CAST_HOLD':'3'}, check=True, timeout=60)
    work = output/'frame'
    work.mkdir()
    framed = output/'framed.mp4'
    import style
    base = output/'base.mp4'
    size = f'{style.CONTENT_W}:{style.CONTENT_H}'
    # The same contain-and-pad filter used by assemble.sh before the frame/caption pass.
    renderer.run_media(['ffmpeg', '-v', 'error', '-y', '-i', str(output/'clip-1.mp4'), '-an',
        '-vf', f'scale={size}:force_original_aspect_ratio=decrease:flags=lanczos,pad={size}:(ow-iw)/2:(oh-ih)/2:color={style.BG},fps={style.FPS},format=yuv420p',
        '-c:v', 'libx264', '-crf', '16', str(base)])
    subprocess.run([sys.executable, str(DEMO/'filters.py'), 'render', 'web', str(output/'clip-1-events.json'),
                    str(base), str(framed), str(work)], check=True, timeout=60)
    from PIL import Image
    synthetic_image = output/'synthetic.png'
    Image.new('RGB', (640,360), (15,23,42)).save(synthetic_image)
    still = output/'styled-still.png'
    subprocess.run([sys.executable, str(DEMO/'style.py'), 'still', str(synthetic_image), str(still)],
                   check=True, timeout=30)
    with Image.open(still) as image:
        if image.format != 'PNG' or image.width < 640 or image.height < 360:
            raise ValueError('styled still dimensions differ')
    result = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,width,height,pix_fmt,r_frame_rate:format=duration',
        '-of', 'json', str(framed)], timeout=10)
    video = json.loads(result)
    stream = video['streams'][0]
    if (stream['codec_name'] != 'h264' or stream['width'] != 1920 or stream['height'] != 1080 or
            stream['pix_fmt'] != 'yuv420p' or stream['r_frame_rate'] != '30/1' or
            not 3 <= float(video['format']['duration']) <= 5):
        raise ValueError('synthetic media output differs')
    receipt = {'agg':version, 'synthetic_only':True, 'pipeline':'real render-cast, style frame, filters and ffmpeg',
               'video':video, 'bytes':framed.stat().st_size}
    (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    check(args.output)
