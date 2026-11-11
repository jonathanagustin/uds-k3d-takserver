#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Record a short terminal command and check the production media pipeline."""
import argparse
import contextlib
import io
import importlib.util
import json
import os
import re
import shlex
from pathlib import Path
import subprocess
import sys

DEMO = Path(__file__).resolve().parents[1]


def check_terminal_dependencies():
    ttyd = subprocess.check_output(['ttyd','--version'],text=True,timeout=10).strip()
    if not re.fullmatch(r'ttyd version 1\.7\.7(?:-[a-f0-9]+)?',ttyd):
        raise ValueError('unexpected ttyd release; VHS requires at least 1.7.2')
    vhs = subprocess.check_output(['vhs','--version'],text=True,timeout=10).strip()
    if not re.fullmatch(r'vhs version v?0\.12\.1(?: \([a-f0-9]+\))?',vhs):
        raise ValueError('unexpected VHS release')
    # Pinned VHS 0.12.1 checks its real ffmpeg/ttyd/shell dependencies before
    # reading stdin. Empty input must reach precisely this post-check error;
    # no browser, recording, output file or remote publishing is started.
    probe = subprocess.run(['vhs','-'],input='',capture_output=True,text=True,timeout=10,
                           env={**os.environ,'NO_COLOR':'1','VHS_PUBLISH':'false'})
    if probe.returncode!=1 or probe.stdout.strip()!='no input provided' or probe.stderr:
        raise ValueError('VHS dependency preflight failed before recording')
    return {'ttyd':ttyd,'vhs':vhs,'vhs_dependency_check':'passed before EOF rejection'}


def probe_video(path, width, height, minimum, maximum):
    result = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,width,height,pix_fmt,r_frame_rate:format=duration',
        '-of', 'json', str(path)], timeout=10)
    video = json.loads(result)
    stream = video['streams'][0]
    if (stream['codec_name'] != 'h264' or stream['width'] != width or stream['height'] != height or
            stream['pix_fmt'] != 'yuv420p' or stream['r_frame_rate'] != '30/1' or
            not minimum <= float(video['format']['duration']) <= maximum):
        raise ValueError('media output differs: ' + path.name)
    return video


def record_vhs(output, run_media):
    """Record a harmless command with the same tape settings as real chapters."""
    tape, video, exit_file = output/'vhs.tape', output/'vhs.mp4', output/'vhs.exit'
    command = "printf 'VHS terminal preflight\\n'; printf '%s\\n' \"$?\" > " + shlex.quote(str(exit_file))
    # v0.12.1's official root CLI accepts a tape and --output/--publish.
    # VHS_PUBLISH=true can override the flag, so disable both publication paths.
    # Source and Type@ use the same syntax as demo/tapes and settings.tape.
    tape.write_text('Source ' + json.dumps(str(DEMO/'settings.tape')) + '\n' +
                    'Output ' + json.dumps(str(video)) + '\n' +
                    'Type@1ms ' + json.dumps(command) + '\nEnter\nSleep 2s\n')
    previous = os.environ.get('VHS_PUBLISH')
    os.environ['VHS_PUBLISH'] = 'false'
    try:
        run_media(['vhs', '--publish=false', '--output', str(video), str(tape)], seconds=45)
    finally:
        if previous is None:
            os.environ.pop('VHS_PUBLISH', None)
        else:
            os.environ['VHS_PUBLISH'] = previous
    if exit_file.read_text().strip() != '0':
        raise ValueError('recorded VHS command failed')
    return tape, video


def check(output):
    terminal = check_terminal_dependencies()
    output.mkdir()
    # Short synthetic inputs must fail quickly; do not impose this on production recordings.
    os.environ['DEMO_MEDIA_COMMAND_SECONDS'] = '45'
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
    video = probe_video(framed, 1920, 1080, 3, 5)
    vhs_tape, vhs_video = record_vhs(output, renderer.run_media)
    vhs = probe_video(vhs_video, style.CONTENT_W, style.CONTENT_H, 1.5, 6)
    vhs_base, vhs_framed = output/'vhs-base.mp4', output/'vhs-framed.mp4'
    renderer.run_media(['ffmpeg', '-v', 'error', '-y', '-i', str(vhs_video), '-an',
        '-vf', f'scale={size}:force_original_aspect_ratio=decrease:flags=lanczos,pad={size}:(ow-iw)/2:(oh-ih)/2:color={style.BG},fps={style.FPS},format=yuv420p',
        '-c:v', 'libx264', '-crf', '16', str(vhs_base)])
    subprocess.run([sys.executable, str(DEMO/'filters.py'), 'render', 'terminal', str(vhs_tape),
                    str(vhs_base), str(vhs_framed), str(work)], check=True, timeout=60)
    vhs_frame = probe_video(vhs_framed, 1920, 1080, 1.5, 6)
    # Exercise the production two-clip crossfade/concat code, not assemble.sh's
    # cluster-specific chapter list or its long final delivery encode.
    import filters
    joined = output/'joined.mp4'
    starts = io.StringIO()
    with contextlib.redirect_stdout(starts):
        filters.join(str(joined), [str(framed), str(vhs_framed)])
    expected = float(video['format']['duration']) + float(vhs_frame['format']['duration']) - filters.CROSSFADE
    joined_video = probe_video(joined, 1920, 1080, expected - .2, expected + .2)
    chapter_starts = [float(value) for value in starts.getvalue().splitlines()]
    if len(chapter_starts) != 2 or chapter_starts[0] != 0 or abs(chapter_starts[1] -
            (float(video['format']['duration']) - filters.CROSSFADE)) > .1:
        raise ValueError('production join chapter timing differs')
    receipt = {'terminal_dependencies':terminal, 'agg':version, 'synthetic_only':True,
               'actual_terminal_recording':True, 'vhs_recorded_exit':0,
               'pipeline':'real asciicast renderer, VHS recording, style, filters, crossfade join and ffmpeg',
               'video':video, 'vhs_video':vhs, 'joined_video':joined_video,
               'chapter_starts':chapter_starts, 'bytes':joined.stat().st_size}
    (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    check(args.output)
