#!/usr/bin/env python3
"""Fetch the source recordings for the minimal-pairs track.

Downloads individual word recordings from the Shtooka Project collection
"eng-balm-judith" (speaker: Judith Frank, London; licence: CC BY 3.0).
Runs on a GitHub Actions runner because this collection's hosts are not
reachable from every network. Falls back to the collection tar archive,
then to the same collection's files on Wikimedia Commons.

Stdlib only. Writes into public/audio/minimal-pairs/source/ and leaves a
fetch-report.json describing exactly what was downloaded from where.
"""

import io
import json
import os
import re
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

PAIRS = [
    ("sheep", "ship"), ("sit", "set"), ("men", "man"), ("full", "fool"),
    ("luck", "look"), ("rice", "rise"), ("thin", "tin"), ("they", "day"),
    ("wine", "vine"), ("hair", "air"), ("berry", "very"), ("cap", "cab"),
]
WORDS = [w for pair in PAIRS for w in pair]

OUT_DIR = os.path.join("public", "audio", "minimal-pairs", "source")

COLLECTION = "eng-balm-judith"
INDEX_URLS = [
    f"https://packs.shtooka.net/{COLLECTION}/flac/index.tags.txt",
    f"https://packs.shtooka.net/{COLLECTION}/ogg/index.tags.txt",
    f"https://packs.shtooka.net/{COLLECTION}/mp3/index.tags.txt",
    f"https://packs.shtooka.net/{COLLECTION}/index.tags.txt",
    f"http://packs.shtooka.net/{COLLECTION}/flac/index.tags.txt",
    f"http://packs.shtooka.net/{COLLECTION}/ogg/index.tags.txt",
]
TAR_URLS = [
    f"https://packs.shtooka.net/{COLLECTION}.tar",
    f"http://packs.shtooka.net/{COLLECTION}.tar",
    f"https://download.shtooka.net/{COLLECTION}.tar",
    f"http://download.shtooka.net/{COLLECTION}.tar",
]
EXTRA_FILES = ["readme.txt", "README.txt", "COPYRIGHT.txt", "license.txt", "LICENSE.txt"]

UA = {"User-Agent": "minimal-pairs-fetcher/1.0 (github.com/dariopicozzi/dariopicozzi.github.io)"}


def get(url, tries=3, timeout=60):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - report the last failure, whatever it was
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def parse_tags(text):
    """Parse a SWAC index.tags.txt into {section_name: {key: value}}."""
    entries = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            current = m.group(1).strip()
            entries.setdefault(current, {})
            continue
        if current is not None and "=" in line:
            k, v = line.split("=", 1)
            entries[current][k.strip()] = v.strip()
    return entries


def norm(s):
    return re.sub(r"[\s!?.,;:]+$", "", s.strip().lower())


def match_word(entries, word):
    """Return (section, tags, quality) for the entry whose text is `word`.

    quality: 'exact' if SWAC_TEXT is the bare word, 'prefixed' if it only
    matches after stripping a leading article/'to' (flagged for review).
    """
    exact, prefixed = [], []
    for section, tags in entries.items():
        text = norm(tags.get("SWAC_TEXT", ""))
        if not text:
            continue
        if text == word:
            exact.append((section, tags))
            continue
        for pre in ("a ", "an ", "the ", "to "):
            if text == pre + word:
                prefixed.append((section, tags))
                break
    if exact:
        return exact[0] + ("exact",)
    if prefixed:
        return prefixed[0] + ("prefixed",)
    return None, None, None


def fetch_via_index():
    for index_url in INDEX_URLS:
        try:
            text = get(index_url).decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            print(f"index unavailable: {index_url} ({e})")
            continue
        entries = parse_tags(text)
        if not entries:
            print(f"index empty/unparsable: {index_url}")
            continue
        print(f"using index: {index_url} ({len(entries)} entries)")
        base = index_url.rsplit("/", 1)[0] + "/"
        report = {"index_url": index_url, "entry_count": len(entries), "words": {}}
        with open(os.path.join(OUT_DIR, "index.tags.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        ok = True
        for word in WORDS:
            section, tags, quality = match_word(entries, word)
            if section is None:
                print(f"MISSING in index: {word}")
                report["words"][word] = {"status": "missing"}
                ok = False
                continue
            rel = section.lstrip("./")
            url = urllib.parse.urljoin(base, urllib.parse.quote(rel))
            ext = os.path.splitext(rel)[1] or ".flac"
            dest = os.path.join(OUT_DIR, word + ext)
            try:
                data = get(url)
                with open(dest, "wb") as f:
                    f.write(data)
                print(f"{word}: {url} -> {dest} ({len(data)} bytes, match={quality})")
                report["words"][word] = {
                    "status": "ok", "file": os.path.basename(dest), "url": url,
                    "match": quality, "bytes": len(data), "tags": tags,
                }
            except Exception as e:  # noqa: BLE001
                print(f"FAILED download {word}: {url} ({e})")
                report["words"][word] = {"status": "download-failed", "url": url}
                ok = False
        for name in EXTRA_FILES:
            try:
                data = get(urllib.parse.urljoin(base, name), tries=1, timeout=20)
                with open(os.path.join(OUT_DIR, "collection-" + name.lower()), "wb") as f:
                    f.write(data)
                print(f"saved collection file: {name}")
            except Exception:  # noqa: BLE001
                pass
        return report, ok
    return None, False


def fetch_via_tar():
    for tar_url in TAR_URLS:
        try:
            blob = get(tar_url, tries=2, timeout=300)
        except Exception as e:  # noqa: BLE001
            print(f"tar unavailable: {tar_url} ({e})")
            continue
        print(f"downloaded tar: {tar_url} ({len(blob)} bytes)")
        tf = tarfile.open(fileobj=io.BytesIO(blob))
        names = tf.getnames()
        index_name = next((n for n in names if n.endswith("index.tags.txt")), None)
        if not index_name:
            print("tar has no index.tags.txt")
            continue
        entries = parse_tags(tf.extractfile(index_name).read().decode("utf-8", "replace"))
        prefix = os.path.dirname(index_name)
        report = {"tar_url": tar_url, "entry_count": len(entries), "words": {}}
        ok = True
        for word in WORDS:
            section, tags, quality = match_word(entries, word)
            if section is None:
                report["words"][word] = {"status": "missing"}
                ok = False
                continue
            member = os.path.join(prefix, section.lstrip("./")) if prefix else section
            try:
                data = tf.extractfile(member).read()
            except Exception:  # noqa: BLE001
                cand = next((n for n in names if n.endswith("/" + os.path.basename(section))), None)
                if not cand:
                    report["words"][word] = {"status": "not-in-tar", "member": member}
                    ok = False
                    continue
                data = tf.extractfile(cand).read()
                member = cand
            ext = os.path.splitext(member)[1] or ".flac"
            dest = os.path.join(OUT_DIR, word + ext)
            with open(dest, "wb") as f:
                f.write(data)
            print(f"{word}: tar:{member} -> {dest} ({len(data)} bytes, match={quality})")
            report["words"][word] = {
                "status": "ok", "file": os.path.basename(dest), "url": f"{tar_url}#{member}",
                "match": quality, "bytes": len(data), "tags": tags,
            }
        return report, ok
    return None, False


COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def fetch_from_commons(word):
    """Fallback: find this word's recording from the same collection on Commons."""
    titles = "|".join(f"File:En-{v}{word}.ogg" for v in ("", "uk-", "us-"))
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "titles": titles,
        "prop": "imageinfo|revisions", "iiprop": "url|extmetadata",
        "rvprop": "content", "rvslots": "main",
    })
    data = json.loads(get(f"{COMMONS_API}?{q}").decode("utf-8"))
    for page in data.get("query", {}).get("pages", {}).values():
        if "imageinfo" not in page:
            continue
        try:
            wikitext = page["revisions"][0]["slots"]["main"]["*"]
        except (KeyError, IndexError):
            wikitext = ""
        blob_l = wikitext.lower()
        if "shtooka" not in blob_l or not ("judith" in blob_l or "eng-balm" in blob_l):
            continue
        url = page["imageinfo"][0]["url"]
        dest = os.path.join(OUT_DIR, word + ".ogg")
        with open(dest, "wb") as f:
            f.write(get(url))
        print(f"{word}: commons {page['title']} -> {dest}")
        return {"status": "ok", "file": os.path.basename(dest), "url": url,
                "match": "commons", "commons_title": page["title"]}
    return None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    report, ok = fetch_via_index()
    if report is None:
        report, ok = fetch_via_tar()
    if report is None:
        report, ok = {"words": {}}, False
    if not ok:
        for word in WORDS:
            if report["words"].get(word, {}).get("status") == "ok":
                continue
            try:
                got = fetch_from_commons(word)
            except Exception as e:  # noqa: BLE001
                got = None
                print(f"commons fallback failed for {word}: {e}")
            if got:
                report["words"][word] = got
    report["pairs"] = PAIRS
    missing = [w for w in WORDS if report["words"].get(w, {}).get("status") != "ok"]
    report["missing"] = missing
    with open(os.path.join(OUT_DIR, "fetch-report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\ndone: {len(WORDS) - len(missing)}/{len(WORDS)} words fetched")
    if missing:
        print("missing:", ", ".join(missing))


if __name__ == "__main__":
    sys.exit(main())
