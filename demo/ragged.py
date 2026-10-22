#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Rewrite demo/tapes/*.tape so the typing is uneven, like a person's.

    ragged.py SOURCE_TAPE OUTPUT_TAPE

Each visible 'Type@<speed> "text"' line becomes short chunks with their own
speeds and pauses between them: words often go in one burst, flags, pipes and
quotes get a hesitation first, and a pipeline gets one longer think pause.
The Sleep before each Enter becomes 300-800 ms. Lines marked with
'# typo: <word>' get one corrected typo in that word (comments only).
Lines marked with '# fast' are typed quickly in one go (long commands).
The random seed is the tape's file name, so the schedule is the same on
every run, and demo/filters.py reads the generated tape to time captions.
"""

import random
import re
import sys
from pathlib import Path

NEIGHBORS = {
    "a": "s", "b": "v", "c": "x", "d": "s", "e": "w", "f": "d", "g": "f",
    "h": "g", "i": "u", "k": "j", "l": "k", "m": "n", "n": "m", "o": "i",
    "p": "o", "r": "e", "s": "a", "t": "r", "u": "y", "w": "q", "y": "t",
}


def ms(value):
    return f"{int(round(value))}ms"


def tokens(text):
    # Runs of spaces and runs of non-spaces, so word boundaries are kept.
    return re.findall(r"\s+|\S+", text)


def chunks_of(rng, word, burst=0.55):
    """Split one word into 1-4 character chunks, sometimes one burst."""
    if len(word) <= 8 and rng.random() < burst:
        return [(word, rng.uniform(40, 60))]
    out = []
    i = 0
    while i < len(word):
        size = rng.choice((1, 2, 2, 3, 3, 4))
        out.append((word[i:i + size], rng.uniform(45, 130)))
        i += size
    return out


def type_line(rng, text, typo_word):
    lines = []
    comment = text.startswith("#")
    pipe_seen = False
    typo_done = False
    for tok in tokens(text):
        if tok.isspace():
            lines.append(f'Type@{ms(rng.uniform(40, 90))} "{tok}"')
            if rng.random() < (0.1 if comment else 0.25):
                lines.append(f"Sleep {ms(rng.uniform(200, 500))}")
            continue
        first = tok[0]
        if not comment and first == "|" and not pipe_seen:
            pipe_seen = True
            lines.append(f"Sleep {ms(rng.uniform(750, 900))}")
        elif not comment and first in "-|'\"$>;" and not (lines and lines[-1].startswith("Sleep")):
            lines.append(f"Sleep {ms(rng.uniform(200, 600))}")
        if typo_word and not typo_done and tok == typo_word:
            typo_done = True
            cut = min(3, len(tok) - 1)
            wrong = NEIGHBORS.get(tok[cut].lower(), "e")
            lines.append(f'Type@{ms(rng.uniform(55, 90))} "{tok[:cut]}{wrong}"')
            lines.append(f"Sleep {ms(rng.uniform(300, 450))}")
            lines.append(f"Backspace@{ms(rng.uniform(90, 130))} 1")
            lines.append(f"Sleep {ms(rng.uniform(120, 220))}")
            pieces = chunks_of(rng, tok[cut:], 0.8 if comment else 0.55)
        else:
            pieces = chunks_of(rng, tok, 0.8 if comment else 0.55)
        for index, (piece, speed) in enumerate(pieces):
            if index and rng.random() < 0.4:
                lines.append(f"Sleep {ms(rng.uniform(60, 220))}")
            lines.append(f'Type@{ms(speed)} "{piece}"')
    if typo_word and not typo_done:
        raise SystemExit(f"typo word {typo_word!r} not found in {text!r}")
    return lines


def main():
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    rng = random.Random(source.name)
    shown = False
    typo_word = None
    fast = False
    out = []
    lines = source.read_text().splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if line == "Show":
            shown = True
        match = re.match(r'Type(?:@\S+)?\s+"(.*)"$', line)
        if line == "# fast":
            fast = True
            i += 1
            continue
        if line.startswith("# typo:"):
            typo_word = line.split(":", 1)[1].strip()
            i += 1
            continue
        if shown and match:
            text = match.group(1)
            if typo_word and not text.startswith("#"):
                raise SystemExit("typos are only allowed in comment lines")
            if fast:
                out.append(f'Type@{ms(rng.uniform(6, 10))} "{text}"')
            else:
                out.extend(type_line(rng, text, typo_word))
            typo_word = None
            fast = False
            # Replace the Sleep before Enter with a 300-800 ms pause.
            if i + 2 < len(lines) and lines[i + 1].startswith("Sleep ") and lines[i + 2].strip() == "Enter":
                i += 1
            out.append(f"Sleep {ms(rng.uniform(300, 800))}")
            i += 1
            continue
        out.append(raw)
        i += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
