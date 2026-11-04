#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Turn one recorded segment into a styled 1920x1080 clip.

prepare RAW EVENTS OUT_VIDEO OUT_EVENTS [DEVICE_VIDEO DEVICE_START]
    For a browser recording. Crops Chrome's tab strip, covers the profile
    and menu buttons at the right end of the toolbar (the address bar stays),
    holds the last good frame over blank white pages and over "hold" ranges
    the walkthrough marked, and lays the phone's own screen recording
    (DEVICE_VIDEO, started at wall-clock DEVICE_START) over the ws-scrcpy
    view while the phone page is in front. Inside those phone stretches, a
    wait where nothing on screen changes for more than STALL seconds is cut
    to KEEP seconds, and the caption showing then gets an emerald speed-up
    tag. Writes the cut video and the events moved to match.
render MODE TIMELINE BASE OUT WORKDIR [OFFSET]
    MODE is terminal (TIMELINE is a generated tape) or web (TIMELINE is an
    events.json). BASE is the content, CONTENT_W x CONTENT_H. Zooms gently
    where the timeline asks, puts the content in the window frame on the
    canvas, and shows each caption as a lower-third.
join OUT PART...
    Joins the parts with short crossfades and prints where each starts.

The terminal timeline: '# caption: text' and '# zoom: ax,ay,factor' lines
apply to the next typed command and start when it presses Enter. Times come
from the tape: characters x typing speed, every Backspace, every Sleep.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style  # noqa: E402

FPS = style.FPS
CW, CH = style.CONTENT_W, style.CONTENT_H
EASE = 0.6
HOLD = 2.0
# A zoom stays gentle whatever the timeline asks for.
ZOOM_MAX = 1.15
# Phone stretches: a still screen longer than STALL is cut to KEEP.
STALL = 4.5
KEEP = 3.0
CROSSFADE = 0.3


def run(*args, **kw):
    return subprocess.run(list(args), check=True, capture_output=True, text=True, **kw)


def duration_of(video):
    return float(run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video).stdout)


def parse_ms(value):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s)", value)
    if not match:
        raise ValueError(f"bad duration {value}")
    number = float(match.group(1))
    return number / 1000 if match.group(2) == "ms" else number


def terminal_events(tape):
    default_speed = 0.075
    for line in Path("demo/settings.tape").read_text().splitlines():
        if line.startswith("Set TypingSpeed"):
            default_speed = parse_ms(line.split()[-1])
    t, shown, pending, events = 0.0, False, [], []
    for raw in Path(tape).read_text().splitlines():
        line = raw.strip()
        if line == "Show":
            shown = True
            continue
        if not shown:
            continue
        if line.startswith("# caption:") or line.startswith("# zoom:"):
            pending.append(line[2:])
            continue
        type_match = re.match(r'Type(?:@(\S+))?\s+"(.*)"$', line)
        if type_match:
            speed = parse_ms(type_match.group(1)) if type_match.group(1) else default_speed
            t += speed * len(type_match.group(2))
            continue
        if line.startswith("Sleep "):
            t += parse_ms(line.split()[1])
            continue
        back_match = re.match(r"Backspace(?:@(\S+))?(?:\s+(\d+))?$", line)
        if back_match:
            speed = parse_ms(back_match.group(1)) if back_match.group(1) else default_speed
            t += speed * int(back_match.group(2) or 1)
            continue
        if line == "Enter":
            for item in pending:
                kind, _, value = item.partition(":")
                events.append({"kind": kind.strip(), "at": t, "value": value.strip()})
            pending = []
    return events


# ---------------------------------------------------------------- prepare

def gray_frames(video, vf, size):
    """Raw 8-bit gray frames of VIDEO through VF, SIZE=(w, h), as bytes."""
    w, h = size
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vf", f"{vf},scale={w}:{h},format=gray",
                          "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
    n = w * h
    return [out[i:i + n] for i in range(0, len(out) - n + 1, n)]


def diffs(frames):
    """Mean absolute difference of each frame from the one before (0-255)."""
    out = [0.0]
    for a, b in zip(frames, frames[1:]):
        out.append(sum(abs(x - y) for x, y in zip(a, b)) / len(a))
    return out


def chrome_rows(raw, at):
    """Tab strip height, toolbar bottom row, and the toolbar colour, read from
    the column near the right edge of one frame."""
    w = int(run("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width",
                "-of", "csv=p=0", raw).stdout)
    col = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", raw, "-frames:v", "1",
                          "-vf", f"crop=1:200:{w - 6}:0,format=rgb24", "-f", "rawvideo", "-"],
                         check=True, capture_output=True).stdout
    px = [tuple(col[i:i + 3]) for i in range(0, len(col), 3)]

    def far(a, b):
        return sum(abs(x - y) for x, y in zip(a, b)) > 24

    tab = next((y for y in range(1, len(px)) if far(px[y], px[0])), 0)
    bar = next((y for y in range(tab + 2, len(px)) if far(px[y], px[tab + 4])), tab + 56)
    color = "0x%02x%02x%02x" % px[min(tab + 4, len(px) - 1)]
    return tab, bar, color


def blank_ranges(video, top):
    """Frame ranges where nearly the whole page (below TOP) is white."""
    crop = f"crop=iw:ih-{top}:0:{top}," if top > 0 else ""
    out = run("ffmpeg", "-v", "error", "-i", video, "-vf",
              f"{crop}signalstats,metadata=print:key=lavfi.signalstats.YLOW:file=-", "-f", "null", "-").stdout
    frames, frame = [], None
    for line in out.splitlines():
        m = re.match(r"frame:(\d+)", line)
        if m:
            frame = int(m.group(1))
            continue
        m = re.search(r"YLOW=([\d.]+)", line)
        if m and frame is not None and float(m.group(1)) >= 230:
            frames.append(frame)
    return merge([(f, f) for f in frames])


def merge(ranges):
    out = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out if a > 0]


def hold_chain(ranges, label_in, label_out):
    if not ranges:
        return f"[{label_in}]null[{label_out}]"
    stages = []
    for i, (first, last) in enumerate(ranges):
        src = f"[{label_in}]" if i == 0 else f"[h{i}]"
        dst = f"[{label_out}]" if i == len(ranges) - 1 else f"[h{i + 1}]"
        stages.append(f"{src}split[m{i}][r{i}];[m{i}][r{i}]freezeframes=first={first}:last={last}:replace={first - 1}{dst}")
    return ";".join(stages)


def phone_intervals(events, duration):
    out, on = [], None
    for e in events:
        if e["kind"] == "phone-on" and on is None:
            on = e
        elif e["kind"] == "phone-off" and on is not None:
            out.append((on["at"], e["at"], on["value"]))
            on = None
    if on is not None:
        out.append((on["at"], duration, on["value"]))
    return out


def align(device, raw, box, intervals, guess, top):
    """Seconds to add to device-video time to get recording time: the guess
    from the wall clocks, refined by matching on-screen changes."""
    x, y, w, h = box
    sw, sh = 18, 32
    try:
        cap = diffs(gray_frames(raw, f"fps={FPS},crop={w}:{h}:{x}:{y + top}", (sw, sh)))
        dev = diffs(gray_frames(device, f"fps={FPS}", (sw, sh)))
    except subprocess.CalledProcessError:
        return guess
    best, best_score = guess, -1.0
    span = int(3 * FPS)
    base = int(round(guess * FPS))
    idx = [i for a, b, _ in intervals for i in range(int(a * FPS), int(b * FPS)) if i < len(cap)]
    if len(idx) < FPS * 3:
        return guess
    for lag in range(base - span, base + span + 1):
        pairs = [(cap[i], dev[i - lag]) for i in idx if 0 <= i - lag < len(dev)]
        if len(pairs) < FPS * 3:
            continue
        ma = sum(p[0] for p in pairs) / len(pairs)
        mb = sum(p[1] for p in pairs) / len(pairs)
        num = sum((a - ma) * (b - mb) for a, b in pairs)
        da = sum((a - ma) ** 2 for a, _ in pairs) ** 0.5
        db = sum((b - mb) ** 2 for _, b in pairs) ** 0.5
        score = num / (da * db) if da and db else 0
        if score > best_score:
            best, best_score = lag / FPS, score
    print(f"phone: device video offset {best:+.2f}s (clock guess {guess:+.2f}s, match {best_score:.2f})", file=sys.stderr)
    return best if best_score >= 0.2 else guess


def stall_cuts(video, intervals):
    """(start, end) seconds to cut: still stretches inside phone intervals."""
    out = run("ffmpeg", "-v", "error", "-i", video, "-vf",
              "scale=480:-2,mpdecimate=hi=768:lo=320:frac=0.33,metadata=print:file=-", "-f", "null", "-").stdout
    kept = [float(m.group(1)) for m in re.finditer(r"pts_time:([\d.]+)", out)]
    cuts = []
    for a, b in zip(kept, kept[1:] + [duration_of(video)]):
        if b - a <= STALL:
            continue
        for s, e, _ in intervals:
            lo, hi = max(a, s), min(b, e)
            if hi - lo > STALL:
                cuts.append((lo + KEEP, hi))
    return cuts


def remap(t, cuts):
    shift = 0.0
    for a, b in cuts:
        if t >= b:
            shift += b - a
        elif t > a:
            return a - shift
    return t - shift


def prepare(raw, events_file, out_video, out_events, device=None, device_start=None):
    events = json.loads(Path(events_file).read_text())
    duration = duration_of(raw)
    tab, bar, bar_color = chrome_rows(raw, min(2.0, duration / 2))
    w = int(run("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width",
                "-of", "csv=p=0", raw).stdout)
    tops = [int(e["value"]) for e in events if e["kind"] == "chrome-top"]
    page_top = (tops[0] if tops else bar) - tab
    dpr = next((float(e["value"]) for e in events if e["kind"] == "dpr"), 1.0)
    print(f"chrome: tab strip {tab}px, toolbar to {bar}px, page from {page_top}px after the crop", file=sys.stderr)

    holds = blank_ranges(raw, tops[0] if tops else 0)
    for e in events:
        if e["kind"] == "hold":
            holds.append((max(1, int(float(e["value"]) * FPS)), int(e["at"] * FPS) + 2))
    holds = merge(holds)
    for a, b in holds:
        print(f"holding frame {a - 1} over frames {a}-{b}", file=sys.stderr)

    # Chrome tints its toolbar from the policy's theme colour with a strong
    # blue. Most of that saturation is taken out so it reads as slate.
    tool_h = (max(bar - tab, 2) + 1) // 2 * 2
    graph = [f"[0:v]fps={FPS},crop=iw:ih-{tab}:0:{tab},"
             f"drawbox=x={w - 112}:y=0:w=112:h={max(bar - tab, 1)}:color={bar_color}:t=fill,split[t0][t1];"
             f"[t1]crop=iw:{tool_h}:0:0,hue=s=0.3[t2];[t0][t2]overlay=0:0[c0]",
             hold_chain(holds, "c0", "c1")]
    inputs = ["-i", raw]
    last = "c1"
    phones = phone_intervals(events, duration)
    if device and Path(device).is_file() and phones:
        try:
            box = [round(float(v) * dpr) for v in phones[0][2].split(",")]
            start_wall = float(next(e["value"] for e in events if e["kind"] == "start"))
            guess = float(Path(device_start).read_text().strip()) - start_wall if device_start else 0.0
            offset = align(device, raw, box, phones, guess, tops[0] if tops else bar)
            x, y, bw, bh = box
            radius = round(34 * dpr)
            mask = out_video + ".phone-mask.png"
            from PIL import Image, ImageDraw
            m = Image.new("L", (bw, bh), 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, bw - 1, bh - 1), radius, fill=255)
            m.save(mask)
            enable = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b, _ in phones)
            shift = (f"setpts=PTS-STARTPTS+{offset:.3f}/TB" if offset >= 0
                     else f"trim=start={-offset:.3f},setpts=PTS-STARTPTS")
            inputs += ["-i", device]
            graph.append(
                f"[1:v]fps={FPS},{shift},scale={bw}:{bh}:flags=lanczos,format=rgba[dv];"
                f"movie={mask},format=gray,loop=loop=-1:size=1,setpts=N/{FPS}/TB[dm];[dv][dm]alphamerge[dev];"
                f"[{last}][dev]overlay=x={x}:y={y + page_top}:enable='{enable}':eof_action=pass:shortest=0[c2]")
            last = "c2"
        except (OSError, ValueError, StopIteration, subprocess.CalledProcessError) as err:
            print(f"phone: device recording not used: {err}", file=sys.stderr)
            graph, inputs, last = graph[:2], inputs[:2], "c1"
    first = out_video + ".p1.mp4"
    enc = ["-t", f"{duration:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
           "-pix_fmt", "yuv420p", first]
    try:
        run("ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", f"[{last}]", *enc)
    except subprocess.CalledProcessError as err:
        if last != "c2":
            raise
        # The device recording could not be laid over: keep the browser view.
        print(f"phone: device recording not used: {err.stderr.strip()[-300:]}", file=sys.stderr)
        run("ffmpeg", "-v", "error", "-y", "-i", raw, "-filter_complex", ";".join(graph[:2]), "-map", "[c1]", *enc)

    cuts = stall_cuts(first, phones) if phones else []
    if cuts:
        keep = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in cuts)
        run("ffmpeg", "-v", "error", "-y", "-i", first, "-vf",
            f"select='not({keep})',setpts=N/{FPS}/TB", "-an", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "14", "-pix_fmt", "yuv420p", out_video)
        Path(first).unlink()
        for a, b in cuts:
            print(f"cut a still stretch {a:.1f}-{b:.1f}s ({b - a:.1f}s)", file=sys.stderr)
    else:
        Path(first).rename(out_video)
    moved = []
    for e in events:
        e = dict(e)
        e["at"] = round(remap(float(e["at"]), cuts), 3)
        moved.append(e)
    for a, b in cuts:
        factor = (b - a + KEEP) / KEEP
        moved.append({"kind": "speedup", "at": round(remap(a, cuts), 3), "value": f"{factor:.0f}× faster"})
    moved.sort(key=lambda e: e["at"])
    Path(out_events).write_text(json.dumps(moved, indent=2))


# ----------------------------------------------------------------- render

def zoom_filter(at, ax, ay, factor):
    factor = min(factor, ZOOM_MAX)
    up = f"clip((it-{at:.3f})/{EASE},0,1)"
    down = f"clip((it-{at + EASE + HOLD:.3f})/{EASE},0,1)"
    z = f"1+{factor - 1:.3f}*({up}*{up}*(3-2*{up})-{down}*{down}*(3-2*{down}))"
    return (f"scale={CW * 2}:{CH * 2}:flags=lanczos,"
            f"zoompan=z='{z}':x='{ax}*(iw-iw/zoom)':y='{ay}*(ih-ih/zoom)':d=1:s={CW}x{CH}:fps={FPS}")


def split_caption(text):
    """'Label (real time 2m 05s, shown about 9x faster)' -> ('Label', '9× faster · 2m 05s real')."""
    m = re.match(r"^(.*?)\s*\(real time ([^,)]+)(?:, shown about (\d+)x faster)?\)$", text)
    if not m:
        return text, ""
    label, real, faster = m.groups()
    return label, (f"{faster}× faster · {real} real" if faster else "")


def still_src(path, fmt="rgba"):
    """An endless stream of one image, at FPS, made on demand."""
    return f"movie={path},format={fmt},loop=loop=-1:size=1,setpts=N/{FPS}/TB"


def render(mode, timeline, base, out, workdir, offset=0.0):
    work = Path(workdir)
    duration = duration_of(base)
    if mode == "terminal":
        events = terminal_events(timeline) if Path(timeline).is_file() else []
    else:
        events = json.loads(Path(timeline).read_text()) if Path(timeline).is_file() else []
    for e in events:
        e["at"] = float(e["at"]) - offset
    under, over, mask = (work / "frame-under.png", work / "frame-over.png", work / "frame-mask.png")
    if not under.is_file():
        run(sys.executable, str(Path(__file__).with_name("style.py")), "frame", str(under), str(over), str(mask))
    content = [f"[0:v]fps={FPS}"]
    zooms = [e for e in events if e["kind"] == "zoom"]
    if zooms:
        ax, ay, factor = (float(v) for v in str(zooms[0]["value"]).split(","))
        at = min(zooms[0]["at"] + 0.8, max(duration - 2 * EASE - HOLD, 0))
        content.append(zoom_filter(at, ax, ay, factor))
    content.append(f"format=rgba[c];{still_src(mask, 'gray')}[m];[c][m]alphamerge[cm]")
    # Still images come from movie sources inside the graph: they are made
    # on demand, so they never queue up ahead of the recording.
    graph = [",".join(content),
             f"{still_src(under)}[u];[u][cm]overlay={style.CONTENT_X}:{style.CONTENT_Y}:shortest=1[b0];"
             f"{still_src(over)}[o];[b0][o]overlay=0:0:shortest=1[b1]"]
    inputs = ["-i", base]
    marks = [e for e in events if e["kind"] in ("caption", "caption-clear")]
    speedups = [e for e in events if e["kind"] == "speedup"]
    stem = Path(timeline).stem
    last, n = "b1", 4
    for i, e in enumerate(marks):
        if e["kind"] != "caption":
            continue
        start = max(e["at"] + 0.3, 0.0)
        end = marks[i + 1]["at"] if i + 1 < len(marks) else duration
        end = min(end - 0.2, duration - 0.2)
        if end - start < 1.0:
            continue
        text, tag = split_caption(e["value"])
        sped = [s for s in speedups if start - 0.5 <= s["at"] <= end]
        if sped and not tag:
            tag = sped[0]["value"]
        png = work / f"{stem}-lower-{i}.png"
        x, y = run(sys.executable, str(Path(__file__).with_name("style.py")), "lower", str(png), text, tag).stdout.split()
        fade = 0.25
        graph.append(
            f"{still_src(png)},fade=t=in:st={start:.3f}:d={fade}:alpha=1,"
            f"fade=t=out:st={end - fade:.3f}:d={fade}:alpha=1[l{n}];"
            f"[{last}][l{n}]overlay={x}:{y}:shortest=1:enable='between(t,{start:.3f},{end:.3f})'[b{n}]")
        last, n = f"b{n}", n + 1
    run("ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", f"[{last}]",
        "-t", f"{duration:.3f}", "-an", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), out)


# ------------------------------------------------------------------- join

def frames_of(video):
    out = run("ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
              "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", video).stdout
    return int(out.strip())


def join(out, parts):
    """Joins PARTS with CROSSFADE-second crossfades and prints the start time
    of each part in the joined video. Each crossfade is made on its own from
    the end of one part and the start of the next, then the pieces are
    concatenated, so no part waits in memory for the one before it."""
    fade = round(CROSSFADE * FPS)
    tmp = Path(out + ".parts")
    tmp.mkdir(exist_ok=True)
    enc = ["-an", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(FPS)]
    counts = [frames_of(p) for p in parts]
    pieces, starts, at = [], [], 0
    for i, (part, n) in enumerate(zip(parts, counts)):
        first = fade if i > 0 else 0
        last = n - fade if i + 1 < len(parts) else n
        starts.append((at - (fade if i > 0 else 0)) / FPS)
        body = tmp / f"{i:03d}-body.mp4"
        run("ffmpeg", "-v", "error", "-y", "-i", part, "-vf",
            f"fps={FPS},trim=start_frame={first}:end_frame={last},setpts=PTS-STARTPTS", *enc, str(body))
        pieces.append(body)
        at += last - first
        if i + 1 < len(parts):
            mix = tmp / f"{i:03d}-fade.mp4"
            run("ffmpeg", "-v", "error", "-y", "-i", part, "-i", parts[i + 1], "-filter_complex",
                f"[0:v]fps={FPS},trim=start_frame={n - fade},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p,setsar=1[a];"
                f"[1:v]fps={FPS},trim=end_frame={fade},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p,setsar=1[b];"
                f"[a][b]xfade=transition=fade:duration={CROSSFADE}:offset=0", *enc, str(mix))
            pieces.append(mix)
            at += fade
    listing = tmp / "list.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in pieces))
    run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", out)
    for p in tmp.iterdir():
        p.unlink()
    tmp.rmdir()
    for t in starts:
        print(f"{t:.3f}")

def main():
    cmd = sys.argv[1]
    if cmd == "prepare":
        prepare(*sys.argv[2:6], *(sys.argv[6:8] if len(sys.argv) > 7 else []))
    elif cmd == "render":
        mode, timeline, base, out, workdir = sys.argv[2:7]
        render(mode, timeline, base, out, workdir, float(sys.argv[7]) if len(sys.argv) > 7 else 0.0)
    elif cmd == "join":
        join(sys.argv[2], sys.argv[3:])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
