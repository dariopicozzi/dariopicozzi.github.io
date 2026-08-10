#!/usr/bin/env python3
"""Fetch the source recordings for the minimal-pairs track.

Downloads individual word recordings from the Shtooka Project collection
"eng-balm-judith" (speaker: Judith Frank, London; licence: CC BY 3.0).
Runs on a GitHub Actions runner because this collection's hosts are not
reachable from every network.

Sources, in order of preference:
 1. the collection archive, discovered by scraping shtooka.net /
    swac-collections.org download pages (FLAC originals);
 2. the same collection's files on Wikimedia Commons (En-uk-<word>.ogg),
    fetched with one batched API query and polite, 429-aware downloads.

Idempotent: words that already have a file in the source directory are
kept as they are. Stdlib only. Writes fetch-report.json with provenance.
"""

import io
import json
import os
import re
import socket
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

PAIRS = [
    ("sheep", "ship"), ("sit", "set"), ("men", "man"), ("full", "fool"),
    ("luck", "look"), ("rice", "rise"), ("thin", "tin"), ("they", "day"),
    ("wine", "vine"), ("hair", "air"), ("berry", "very"), ("cap", "cab"),
]
WORDS = [w for pair in PAIRS for w in pair]

OUT_DIR = os.path.join("public", "audio", "minimal-pairs", "source")
AUDIO_EXTS = (".flac", ".ogg", ".oga", ".mp3", ".wav")

DOWNLOAD_PAGES = [
    "https://shtooka.net/download.php",
    "http://shtooka.net/download.php",
    "http://swac-collections.org/download.php",
    "http://swac-collections.org/",
]
DIRECT_ARCHIVE_GUESSES = [
    "https://shtooka.net/packs/eng-balm-judith.tar",
    "http://swac-collections.org/packs/eng-balm-judith.tar",
]

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
SHTOOKA_CATEGORY = "Category:Audio files from Shtooka Project (English)"
POLITE_DELAY = 1.2  # s between consecutive Wikimedia requests

UA = {"User-Agent": "minimal-pairs-fetcher/2.0 (https://github.com/dariopicozzi/dariopicozzi.github.io; audio credits workflow)"}


def log(*args):
    print(*args, flush=True)


def get(url, tries=3, timeout=30):
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                wait = max(int(e.headers.get("Retry-After") or 0), 5 * attempt)
                log(f"  429 for {url}, waiting {wait}s")
                time.sleep(wait)
                continue
            if e.code == 404 or attempt == tries:
                raise
            time.sleep(2 * attempt)
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), socket.gaierror):
                raise  # dead DNS: retrying will not help
            last = e
            if attempt == tries:
                raise
            time.sleep(2 * attempt)
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
    for section, tags in entries.items():
        if norm(tags.get("SWAC_TEXT", "")) == word:
            return section, tags
    return None, None


def discover_archive_urls():
    urls = []
    for page in DOWNLOAD_PAGES:
        try:
            html = get(page, tries=1, timeout=20).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            log(f"download page unavailable: {page} ({e})")
            continue
        for href in re.findall(r"""href=["']([^"']+)["']""", html):
            if re.search(r"judith|eng-balm", href, re.I):
                urls.append(urllib.parse.urljoin(page, href))
        log(f"scraped {page}: {len(urls)} candidate link(s) so far")
    urls.extend(DIRECT_ARCHIVE_GUESSES)
    seen, ordered = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered


def entries_from_archive(blob, label):
    """Extract needed words from a tar/zip archive blob. Returns report entries."""
    if blob[:2] == b"PK":
        zf = zipfile.ZipFile(io.BytesIO(blob))
        names = zf.namelist()
        read = lambda n: zf.read(n)  # noqa: E731
    else:
        tf = tarfile.open(fileobj=io.BytesIO(blob))
        names = tf.getnames()
        read = lambda n: tf.extractfile(n).read()  # noqa: E731
    index_name = next((n for n in names if n.endswith("index.tags.txt")), None)
    if not index_name:
        log(f"  archive has no index.tags.txt ({label})")
        return {}
    entries = parse_tags(read(index_name).decode("utf-8", "replace"))
    prefix = os.path.dirname(index_name)
    got = {}
    for word in WORDS:
        section, tags = match_word(entries, word)
        if section is None:
            continue
        member = "/".join(p for p in (prefix, section.lstrip("./")) if p)
        if member not in names:
            member = next((n for n in names if n.endswith("/" + os.path.basename(section))), None)
            if member is None:
                continue
        ext = os.path.splitext(member)[1] or ".flac"
        dest = os.path.join(OUT_DIR, word + ext)
        with open(dest, "wb") as f:
            f.write(read(member))
        log(f"  {word}: archive:{member} -> {dest}")
        got[word] = {"status": "ok", "file": os.path.basename(dest),
                     "url": f"{label}#{member}", "match": "archive", "tags": tags}
    return got


def fetch_via_archives(missing):
    for url in discover_archive_urls():
        if not missing:
            break
        base = url.split("?")[0].lower()
        if not base.endswith((".tar", ".tar.gz", ".tgz", ".zip")):
            continue
        try:
            blob = get(url, tries=1, timeout=180)
        except Exception as e:  # noqa: BLE001
            log(f"archive unavailable: {url} ({e})")
            continue
        log(f"downloaded archive: {url} ({len(blob)} bytes)")
        try:
            return entries_from_archive(blob, url)
        except Exception as e:  # noqa: BLE001
            log(f"  archive unreadable: {e}")
    return {}


def commons_api(params):
    q = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2", "maxlag": "5"})
    data = json.loads(get(f"{COMMONS_API}?{q}", tries=4).decode("utf-8"))
    time.sleep(POLITE_DELAY)
    return data


def candidate_titles(word):
    return [f"File:En-uk-{word}.ogg", f"File:En-{word}.ogg"]


def pick_commons_pages(pages_by_title, words):
    """Choose one Commons page per word, requiring Shtooka/Judith evidence."""
    chosen = {}
    for word in words:
        best = None
        for title in candidate_titles(word):
            page = pages_by_title.get(title.lower())
            if page is None:
                continue
            text = page.get("wikitext", "").lower()
            is_uk = title.lower().startswith("file:en-uk-")
            judith = "judith" in text or "eng-balm" in text
            shtooka = "shtooka" in text
            if judith or (is_uk and shtooka):
                score = (2 if judith else 1) + (1 if is_uk else 0)
                if best is None or score > best[0]:
                    best = (score, title, page)
        if best:
            chosen[word] = best[1:]
    return chosen


def commons_query_titles(titles):
    pages_by_title = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        data = commons_api({
            "action": "query", "titles": "|".join(chunk),
            "prop": "imageinfo|revisions", "iiprop": "url",
            "rvprop": "content", "rvslots": "main",
        })
        for page in data.get("query", {}).get("pages", []):
            if page.get("missing") or "imageinfo" not in page:
                continue
            try:
                wikitext = page["revisions"][0]["slots"]["main"]["content"]
            except (KeyError, IndexError):
                wikitext = ""
            pages_by_title[page["title"].lower()] = {
                "title": page["title"],
                "url": page["imageinfo"][0]["url"],
                "wikitext": wikitext,
            }
    return pages_by_title


def fetch_via_commons(missing):
    titles = [t for w in missing for t in candidate_titles(w)]
    try:
        pages = commons_query_titles(titles)
    except Exception as e:  # noqa: BLE001
        log(f"commons batch query failed: {e}")
        return {}
    log(f"commons: {len(pages)} of {len(titles)} candidate titles exist")
    chosen = pick_commons_pages(pages, missing)

    leftovers = [w for w in missing if w not in chosen]
    if leftovers:
        log(f"category scan for: {', '.join(leftovers)}")
        try:
            members, cont = [], {}
            while True:
                data = commons_api({
                    "action": "query", "list": "categorymembers",
                    "cmtitle": SHTOOKA_CATEGORY, "cmnamespace": "6",
                    "cmlimit": "500", **cont,
                })
                members += [m["title"] for m in data["query"]["categorymembers"]]
                cont = data.get("continue")
                if not cont:
                    break
            log(f"  category has {len(members)} files")
            extra = []
            for w in leftovers:
                pat = re.compile(rf"^File:En-(uk-)?{re.escape(w)}( \(\d+\))?\.(ogg|oga|flac)$", re.I)
                extra += [t for t in members if pat.match(t)]
            if extra:
                pages.update(commons_query_titles(extra))
                for w, picked in pick_commons_pages(pages, leftovers).items():
                    chosen[w] = picked
        except Exception as e:  # noqa: BLE001
            log(f"  category scan failed: {e}")

    got = {}
    for word, (title, page) in chosen.items():
        try:
            data = get(page["url"], tries=4)
        except Exception as e:  # noqa: BLE001
            log(f"download failed for {word} ({title}): {e}")
            continue
        time.sleep(POLITE_DELAY)
        ext = os.path.splitext(urllib.parse.urlparse(page["url"]).path)[1] or ".ogg"
        dest = os.path.join(OUT_DIR, word + ext)
        with open(dest, "wb") as f:
            f.write(data)
        log(f"{word}: commons {title} -> {dest} ({len(data)} bytes)")
        got[word] = {"status": "ok", "file": os.path.basename(dest),
                     "url": page["url"], "match": "commons", "commons_title": title}
    return got


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    report_path = os.path.join(OUT_DIR, "fetch-report.json")
    previous = {}
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as f:
            previous = json.load(f).get("words", {})

    words_report = {}
    for word in WORDS:
        existing = [f for f in os.listdir(OUT_DIR)
                    if os.path.splitext(f)[0] == word and f.endswith(AUDIO_EXTS)]
        if existing:
            entry = previous.get(word, {"status": "ok", "match": "existing"})
            entry["file"] = existing[0]
            entry["status"] = "ok"
            words_report[word] = entry

    missing = [w for w in WORDS if w not in words_report]
    log(f"already present: {len(words_report)}; to fetch: {len(missing)}")

    if missing:
        words_report.update(fetch_via_archives(missing))
        missing = [w for w in WORDS if w not in words_report]
    if missing:
        words_report.update(fetch_via_commons(missing))
        missing = [w for w in WORDS if w not in words_report]

    report = {"pairs": PAIRS, "words": words_report, "missing": missing}
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log(f"\ndone: {len(WORDS) - len(missing)}/{len(WORDS)} words available")
    if missing:
        log("missing: " + ", ".join(missing))


if __name__ == "__main__":
    sys.exit(main())
