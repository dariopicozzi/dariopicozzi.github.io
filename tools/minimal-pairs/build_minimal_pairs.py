#!/usr/bin/env python3
"""Assemble the minimal-pairs listening track from the fetched recordings.

Input:  public/audio/minimal-pairs/source/  (see fetch_shtooka_sources.py)
Output: public/audio/minimal-pairs/minimal-pairs-judith.mp3 (+ .flac master)
        public/audio/minimal-pairs/CREDITS.txt

Each word is played twice (A A B B), with WORD_GAP between words inside a
pair and PAIR_GAP between pairs. The recordings themselves are untouched
apart from silence trimming at the edges, a few ms of anti-click fade and
a gentle per-clip level alignment — no time-stretching or pitch work.

Requires: numpy, soundfile (pip install numpy soundfile).
"""

import glob
import json
import os

import numpy as np
import soundfile as sf

BASE = os.path.join("public", "audio", "minimal-pairs")
SRC = os.path.join(BASE, "source")

WORD_GAP = 0.85   # s between words within a pair group (0.7-1 requested)
PAIR_GAP = 1.75   # s between pairs (1.5-2 requested)
LEAD, TAIL = 0.4, 1.0

TRIM_DB = -42.0        # trim threshold relative to clip peak
KEEP_HEAD, KEEP_TAIL = 0.030, 0.080  # s of natural room kept around the word
FADE = 0.008           # s anti-click fade at trim edges
MAX_ALIGN_DB = 4.0     # cap for per-clip loudness alignment
PEAK_CEIL = 0.95


def load_mono(path):
    data, rate = sf.read(path, always_2d=True)
    return data.mean(axis=1), rate


def trim(clip, rate):
    peak = np.abs(clip).max()
    if peak == 0:
        return clip
    thresh = peak * (10 ** (TRIM_DB / 20))
    idx = np.nonzero(np.abs(clip) > thresh)[0]
    start = max(0, idx[0] - int(KEEP_HEAD * rate))
    end = min(len(clip), idx[-1] + int(KEEP_TAIL * rate))
    out = clip[start:end].copy()
    n = min(int(FADE * rate), len(out) // 2)
    if n:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n))
        out[:n] *= ramp
        out[-n:] *= ramp[::-1]
    return out


def active_rms(clip):
    mag = np.abs(clip)
    voiced = clip[mag > mag.max() * 0.05]
    return np.sqrt(np.mean(voiced ** 2)) if len(voiced) else 0.0


def main():
    with open(os.path.join(SRC, "fetch-report.json"), encoding="utf-8") as f:
        report = json.load(f)
    pairs = [tuple(p) for p in report["pairs"]]
    words = [w for p in pairs for w in p]

    clips, rate = {}, None
    for word in words:
        matches = sorted(glob.glob(os.path.join(SRC, word + ".*")))
        matches = [m for m in matches if os.path.splitext(m)[1] in (".flac", ".ogg", ".mp3", ".wav")]
        if not matches:
            raise SystemExit(f"no source clip for '{word}' in {SRC}")
        clip, r = load_mono(matches[0])
        if rate is None:
            rate = r
        elif r != rate:
            raise SystemExit(f"sample-rate mismatch: {matches[0]} is {r}, expected {rate}")
        clips[word] = trim(clip, rate)

    # Gentle loudness alignment towards the median clip level.
    levels = {w: active_rms(c) for w, c in clips.items()}
    target = float(np.median([v for v in levels.values() if v > 0]))
    for word, clip in clips.items():
        if levels[word] <= 0:
            continue
        gain = np.clip(target / levels[word], 10 ** (-MAX_ALIGN_DB / 20), 10 ** (MAX_ALIGN_DB / 20))
        peak = np.abs(clip).max() * gain
        if peak > PEAK_CEIL:
            gain *= PEAK_CEIL / peak
        clips[word] = clip * gain

    def silence(seconds):
        return np.zeros(int(round(seconds * rate)))

    timeline, chunks, cursor = [], [silence(LEAD)], LEAD
    for i, (a, b) in enumerate(pairs):
        for j, word in enumerate((a, a, b, b)):
            clip = clips[word]
            timeline.append((word, cursor, len(clip) / rate))
            chunks.append(clip)
            cursor += len(clip) / rate
            if j < 3:
                chunks.append(silence(WORD_GAP))
                cursor += WORD_GAP
        gap = PAIR_GAP if i < len(pairs) - 1 else TAIL
        chunks.append(silence(gap))
        cursor += gap

    track = np.concatenate(chunks)
    print(f"track: {cursor:.1f}s at {rate} Hz, {len(pairs)} pairs")
    for word, start, dur in timeline:
        print(f"  {start:7.2f}s  {word:<6} ({dur:.2f}s)")

    speaker = "Judith Frank"
    for info in report["words"].values():
        name = (info.get("tags") or {}).get("SWAC_SPEAK_NAME")
        if name:
            speaker = name
            break
    src_desc = report.get("index_url") or report.get("tar_url") or "Shtooka Project"
    title = "English minimal pairs (each word twice)"
    album = "Shtooka Project - eng-balm-judith"
    licence = f"CC BY 3.0 - voice: {speaker}, Shtooka Project (eng-balm-judith). https://creativecommons.org/licenses/by/3.0/"

    flac_path = os.path.join(BASE, "minimal-pairs-judith.flac")
    mp3_path = os.path.join(BASE, "minimal-pairs-judith.mp3")
    sf.write(flac_path, track, rate)
    sf.write(mp3_path, track, rate)
    print(f"wrote {flac_path} ({os.path.getsize(flac_path)} bytes)")
    print(f"wrote {mp3_path} ({os.path.getsize(mp3_path)} bytes)")

    try:
        from mutagen.flac import FLAC
        from mutagen.id3 import COMM, ID3, TALB, TCOP, TIT2, TPE1

        id3 = ID3()
        id3.add(TIT2(encoding=3, text=title))
        id3.add(TPE1(encoding=3, text=speaker))
        id3.add(TALB(encoding=3, text=album))
        id3.add(TCOP(encoding=3, text=licence))
        id3.add(COMM(encoding=3, lang="eng", desc="licence", text=licence))
        id3.save(mp3_path)
        fl = FLAC(flac_path)
        fl["title"], fl["artist"], fl["album"] = [title], [speaker], [album]
        fl["copyright"], fl["license"] = [licence], ["https://creativecommons.org/licenses/by/3.0/"]
        fl.save()
        print("tagged mp3 + flac")
    except ImportError:
        print("mutagen not installed - files written without tags")
    with open(os.path.join(BASE, "CREDITS.txt"), "w", encoding="utf-8") as f:
        f.write(
            "English minimal pairs - listening track\n"
            "=======================================\n\n"
            "Voice: {speaker} (female speaker, London)\n"
            "Recordings: Shtooka Project, collection eng-balm-judith\n"
            "            {src}\n"
            "Licence:    Creative Commons Attribution 3.0 (CC BY 3.0)\n"
            "            https://creativecommons.org/licenses/by/3.0/\n\n"
            "The individual word recordings are unmodified apart from\n"
            "silence trimming and level alignment; they were sequenced into\n"
            "pairs with tools/minimal-pairs/build_minimal_pairs.py.\n\n"
            "Sequence (each word twice):\n{seq}\n".format(
                speaker=speaker,
                src=src_desc,
                seq="\n".join(f"  {a} - {b}" for a, b in pairs),
            )
        )
    print("wrote CREDITS.txt")


if __name__ == "__main__":
    main()
