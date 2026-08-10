#!/usr/bin/env python3
"""Fetch the source recordings for the minimal-pairs track.

Downloads individual word recordings from the Shtooka Project collection
"eng-balm-judith" (speaker: Judith Frank, London; licence: CC BY 3.0).
Runs on a GitHub Actions runner because this collection's hosts are not
reachable from every network.

Sources, in order of preference:
 1. a live collection archive, discovered by scraping shtooka.net and
    known mirror pages (FLAC originals);
 2. the Internet Archive's Wayback Machine snapshots of the retired
    packs.shtooka.net host (index + individual files, or the tar);
 3. the same collection's files on Wikimedia Commons (En-uk-<word>.ogg),
    fetched with batched API queries and polite, 429-aware downloads.

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
    "https://shtooka.net/",
    "https://shtooka.net/overview.php?lang=eng",
    "https://fsi-languages.yojik.eu/audiocollections/audiocollections.html",
]
DIRECT_ARCHIVE_GUESSES = [
    "https://shtooka.net/packs/eng-balm-judith.tar",
]

WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK_PATTERNS = [
    "packs.shtooka.net/eng-balm-judith*",
    "download.shtooka.net/eng-balm-judith*",
    "shtooka.net/packs/eng-balm-judith*",
]

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
SHTOOKA_CATEGORY = "Category:Audio files from Shtooka Project (English)"
POLITE_DELAY = 1.2  # s between consecutive Wikimedia requests

UA = {"User-Agent": "minimal-pairs-fetcher/3.0 (https://github.com/dariopicozzi/dariopicozzi.github.io; audio credits workflow)"}


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


def save_clip(word, ext, data):
    for old in os.listdir(OUT_DIR):
        if os.path.splitext(old)[0] == word and old.endswith(AUDIO_EXTS):
            os.remove(os.path.join(OUT_DIR, old))
    dest = os.path.join(OUT_DIR, word + ext)
    with open(dest, "wb") as f:
        f.write(data)
    return dest


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
    """Exact-text match only: the track needs the bare word as recorded."""
    for section, tags in entries.items():
        if norm(tags.get("SWAC_TEXT", "")) == word:
            return section, tags
    return None, None


# --- route 1: live archives ------------------------------------------------

def discover_archive_urls():
    urls = []
    for page in DOWNLOAD_PAGES:
        try:
            html = get(page, tries=1, timeout=20).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            log(f"download page unavailable: {page} ({e})")
            continue
        found = 0
        for href in re.findall(r"""href=["']([^"']+)["']""", html):
            if re.search(r"judith|eng-balm", href, re.I):
                urls.append(urllib.parse.urljoin(page, href))
                found += 1
        log(f"scraped {page}: {found} candidate link(s)")
    urls.extend(DIRECT_ARCHIVE_GUESSES)
    seen, ordered = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered


def entries_from_archive(blob, label, wanted):
    """Extract wanted words from a tar/zip archive blob. Returns report entries."""
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
    for word in wanted:
        section, tags = match_word(entries, word)
        if section is None:
            continue
        member = "/".join(p for p in (prefix, section.lstrip("./")) if p)
        if member not in names:
            member = next((n for n in names if n.endswith("/" + os.path.basename(section))), None)
            if member is None:
                continue
        ext = os.path.splitext(member)[1] or ".flac"
        dest = save_clip(word, ext, read(member))
        log(f"  {word}: archive:{member} -> {dest}")
        got[word] = {"status": "ok", "file": os.path.basename(dest),
                     "url": f"{label}#{member}", "match": "archive", "tags": tags}
    return got


def fetch_via_archives(missing):
    for url in discover_archive_urls():
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
            got = entries_from_archive(blob, url, missing)
            if got:
                return got
        except Exception as e:  # noqa: BLE001
            log(f"  archive unreadable: {e}")
    return {}


# --- route 2: Wayback Machine ----------------------------------------------

def cdx_snapshots(pattern):
    q = urllib.parse.urlencode({"url": pattern, "output": "json", "limit": "3000"})
    data = json.loads(get(f"{WAYBACK_CDX}?{q}", tries=3, timeout=90).decode("utf-8", "replace"))
    if not data:
        return []
    rows = [dict(zip(data[0], row)) for row in data[1:]]
    return [r for r in rows if r.get("statuscode") in ("200", "-")]


def wayback_bytes(timestamp, original, timeout=600):
    return get(f"https://web.archive.org/web/{timestamp}id_/{original}",
               tries=3, timeout=timeout)


def fetch_via_wayback(missing):
    got = {}
    for pattern in WAYBACK_PATTERNS:
        still = [w for w in missing if w not in got]
        if not still:
            break
        try:
            rows = cdx_snapshots(pattern)
        except Exception as e:  # noqa: BLE001
            log(f"wayback cdx failed for {pattern}: {e}")
            continue
        log(f"wayback: {len(rows)} snapshots for {pattern}")
        if not rows:
            continue
        rows.sort(key=lambda r: r["timestamp"], reverse=True)

        index_row = next((r for r in rows if r["original"].endswith("index.tags.txt")), None)
        if index_row:
            try:
                text = wayback_bytes(index_row["timestamp"], index_row["original"],
                                     timeout=90).decode("utf-8", "replace")
                entries = parse_tags(text)
                log(f"  archived index {index_row['original']}: {len(entries)} entries")
                with open(os.path.join(OUT_DIR, "index.tags.txt"), "w", encoding="utf-8") as f:
                    f.write(text)
                base = index_row["original"].rsplit("/", 1)[0] + "/"
                newest = {}
                for r in rows:
                    newest.setdefault(r["original"], r)
                for word in still:
                    section, tags = match_word(entries, word)
                    if section is None:
                        log(f"  not in archived index: {word}")
                        continue
                    original = urllib.parse.urljoin(base, section.lstrip("./"))
                    snap = newest.get(original) or {"timestamp": index_row["timestamp"],
                                                    "original": original}
                    try:
                        data = wayback_bytes(snap["timestamp"], snap["original"], timeout=120)
                    except Exception as e:  # noqa: BLE001
                        log(f"  wayback file fetch failed for {word}: {e}")
                        continue
                    ext = os.path.splitext(original)[1] or ".flac"
                    dest = save_clip(word, ext, data)
                    log(f"  {word}: wayback {original} -> {dest} ({len(data)} bytes)")
                    got[word] = {
                        "status": "ok", "file": os.path.basename(dest),
                        "url": f"https://web.archive.org/web/{snap['timestamp']}/{original}",
                        "match": "wayback", "tags": tags,
                    }
                    time.sleep(0.5)
            except Exception as e:  # noqa: BLE001
                log(f"  archived index route failed: {e}")

        still = [w for w in missing if w not in got]
        if not still:
            break
        archive_row = next((r for r in rows
                            if r["original"].split("?")[0].endswith((".tar", ".tar.gz", ".tgz", ".zip"))), None)
        if archive_row:
            try:
                blob = wayback_bytes(archive_row["timestamp"], archive_row["original"])
                log(f"  wayback archive {archive_row['original']} ({len(blob)} bytes)")
                got.update(entries_from_archive(
                    blob, f"wayback:{archive_row['original']}", still))
            except Exception as e:  # noqa: BLE001
                log(f"  wayback archive failed: {e}")
    return got


# --- route 3: Wikimedia Commons --------------------------------------------

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
            else:
                log(f"  exists but lacks Shtooka/Judith evidence: {title}")
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


def commons_inventory():
    """All plausibly-relevant Commons titles: Shtooka English category + En-uk- prefix."""
    titles = set()
    cont = {}
    while True:
        data = commons_api({"action": "query", "list": "categorymembers",
                            "cmtitle": SHTOOKA_CATEGORY, "cmnamespace": "6",
                            "cmlimit": "500", **cont})
        titles.update(m["title"] for m in data["query"]["categorymembers"])
        cont = data.get("continue") or {}
        if not cont:
            break
    cont = {}
    while True:
        data = commons_api({"action": "query", "list": "allpages",
                            "apnamespace": "6", "apprefix": "En-uk-",
                            "aplimit": "500", **cont})
        titles.update(p["title"] for p in data["query"]["allpages"])
        cont = data.get("continue") or {}
        if not cont:
            break
    return sorted(titles)


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
        log(f"inventory scan for: {', '.join(leftovers)}")
        try:
            inventory = commons_inventory()
            log(f"  inventory: {len(inventory)} files")
            with open(os.path.join(OUT_DIR, "commons-inventory.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(inventory) + "\n")
            extra = []
            for w in leftovers:
                pat = re.compile(rf"^File:En-(uk-)?{re.escape(w)}( \(\d+\))?\.(ogg|oga|flac)$", re.I)
                extra += [t for t in inventory if pat.match(t)]
            if extra:
                pages.update(commons_query_titles(extra))
                for w, picked in pick_commons_pages(pages, leftovers).items():
                    chosen[w] = picked
        except Exception as e:  # noqa: BLE001
            log(f"  inventory scan failed: {e}")

    got = {}
    for word, (title, page) in chosen.items():
        try:
            data = get(page["url"], tries=4)
        except Exception as e:  # noqa: BLE001
            log(f"download failed for {word} ({title}): {e}")
            continue
        time.sleep(POLITE_DELAY)
        ext = os.path.splitext(urllib.parse.urlparse(page["url"]).path)[1] or ".ogg"
        dest = save_clip(word, ext, data)
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

    for fetcher in (fetch_via_archives, fetch_via_wayback, fetch_via_commons):
        if not missing:
            break
        words_report.update(fetcher(missing))
        missing = [w for w in WORDS if w not in words_report]

    words_report.update(judith_flac_pass(words_report))
    if any(not os.path.exists(os.path.join(OUT_DIR, f"article-a-{w}.flac"))
           for w in ARTICLE_TEXTS.values()):
        fetch_article_clips()

    report = {"pairs": PAIRS, "words": words_report, "missing": missing}
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    if missing:
        survey()
    log(f"\ndone: {len(WORDS) - len(missing)}/{len(WORDS)} words available")
    if missing:
        log("missing: " + ", ".join(missing))


# --- survey: what could cover the words this collection lacks ---------------

SURVEY_PATH = os.path.join(OUT_DIR, "coverage-report.json")
ARTICLE_CLIPS = {  # Judith recordings that exist only with a spoken article
    "sheep": "File:En-uk-a sheep.ogg",
    "ship": "File:En-uk-a ship.ogg",
    "day": "File:En-uk-a day.ogg",
}


def cdx_query(params):
    q = urllib.parse.urlencode({"output": "json", "limit": "1000", **params})
    data = json.loads(get(f"{WAYBACK_CDX}?{q}", tries=3, timeout=90).decode("utf-8", "replace"))
    if not data:
        return []
    return [dict(zip(data[0], row)) for row in data[1:]]


def survey_shtooka_collections():
    """Coverage of every archived English Shtooka collection index."""
    out = {}
    try:
        rows = cdx_query({"url": "packs.shtooka.net*", "matchType": "prefix",
                          "filter": "original:.*index\\.tags\\.txt$",
                          "collapse": "urlkey"})
    except Exception as e:  # noqa: BLE001
        log(f"survey cdx failed: {e}")
        return out
    originals = sorted({r["original"] for r in rows
                        if "/eng" in r["original"] and r.get("statuscode") in ("200", "-")})
    log(f"survey: {len(originals)} archived English index files")
    for original in originals:
        snaps = [r for r in rows if r["original"] == original]
        snap = max(snaps, key=lambda r: r["timestamp"])
        try:
            entries = parse_tags(wayback_bytes(snap["timestamp"], original,
                                               timeout=90).decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            log(f"  index fetch failed {original}: {e}")
            continue
        glob_tags = entries.get("GLOBAL", {})
        texts = [norm(t.get("SWAC_TEXT", "")) for s, t in entries.items() if s != "GLOBAL"]
        coverage = {}
        for word in WORDS:
            if word in texts:
                coverage[word] = "exact"
            else:
                variants = sorted({t for t in texts
                                   if re.search(rf"\b{re.escape(word)}\b", t)})[:4]
                coverage[word] = variants or None
        exact = sum(1 for v in coverage.values() if v == "exact")
        out[original] = {
            "speaker": glob_tags.get("SWAC_SPEAK_NAME"),
            "gender": glob_tags.get("SWAC_SPEAK_GENDER"),
            "country": glob_tags.get("SWAC_SPEAK_LANG_COUNTRY"),
            "region": glob_tags.get("SWAC_SPEAK_LANG_REGION"),
            "license": glob_tags.get("SWAC_COLL_LICENSE"),
            "entries": len(texts), "exact_words": exact, "coverage": coverage,
        }
        log(f"  {original}: speaker={out[original]['speaker']} "
            f"({out[original]['gender']}, {out[original]['country']}) "
            f"exact {exact}/{len(WORDS)}")
    return out


def survey_commons_voices():
    """Existence of complete single-voice alternatives on Commons."""
    patterns = {
        "commons-en-us (Shtooka US)": lambda w: f"File:En-us-{w}.ogg",
        "commons-LL-Vealhurl (Lingua Libre UK)": lambda w: f"File:LL-Q1860 (eng)-Vealhurl-{w}.wav",
    }
    out = {}
    for label, make in patterns.items():
        titles = [make(w) for w in WORDS]
        try:
            pages = commons_query_titles(titles)
        except Exception as e:  # noqa: BLE001
            log(f"survey commons failed for {label}: {e}")
            continue
        coverage = {w: ("exact" if make(w).lower() in pages else None) for w in WORDS}
        exact = sum(1 for v in coverage.values() if v == "exact")
        out[label] = {"exact_words": exact, "coverage": coverage}
        log(f"  {label}: exact {exact}/{len(WORDS)}")
    return out


def fetch_article_clips():
    """Judith's 'a <word>' recordings, kept beside the bare-word files."""
    for word, title in ARTICLE_CLIPS.items():
        dest = os.path.join(OUT_DIR, f"article-a-{word}.ogg")
        if os.path.exists(dest) or os.path.exists(
                os.path.join(OUT_DIR, f"article-a-{word}.flac")):
            continue
        try:
            pages = commons_query_titles([title])
            page = pages.get(title.lower())
            if not page:
                log(f"article clip missing on commons: {title}")
                continue
            data = get(page["url"], tries=4)
            time.sleep(POLITE_DELAY)
            with open(dest, "wb") as f:
                f.write(data)
            log(f"article clip: {title} -> {dest} ({len(data)} bytes)")
        except Exception as e:  # noqa: BLE001
            log(f"article clip failed for {word}: {e}")


def survey():
    try:
        tars = sorted({r["original"] for r in cdx_query(
            {"url": "download.shtooka.net*", "matchType": "prefix",
             "filter": "original:.*\\.tar$", "collapse": "urlkey"})
            if r.get("statuscode") in ("200", "-")})
    except Exception as e:  # noqa: BLE001
        log(f"tar listing failed: {e}")
        tars = []
    log(f"archived tars: {len(tars)} " + " ".join(tars[:20]))
    report = {"archived_tars": tars,
              "shtooka_collections": survey_shtooka_collections(),
              "commons_voices": survey_commons_voices()}
    with open(SURVEY_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log(f"wrote {SURVEY_PATH}")


# --- Judith FLAC originals from the archived collection tar -----------------

JUDITH_TAR_PATTERN = "download.shtooka.net/eng-balm-judith*"
ARTICLE_TEXTS = {"a sheep": "sheep", "a ship": "ship", "a day": "day"}


def judith_flac_pass(words_report):
    """Fetch the archived FLAC tar once: upgrade bare words to the lossless
    originals and extract the 'a <word>' clips the collection has instead
    of bare nouns. Skips entirely when nothing is left to upgrade."""
    needs_upgrade = [w for w, e in words_report.items()
                     if not e.get("file", "").endswith(".flac")]
    articles_missing = [w for w in ARTICLE_TEXTS.values()
                        if not os.path.exists(os.path.join(OUT_DIR, f"article-a-{w}.flac"))]
    if not needs_upgrade and not articles_missing:
        return {}
    try:
        rows = cdx_snapshots(JUDITH_TAR_PATTERN)
    except Exception as e:  # noqa: BLE001
        log(f"judith tar cdx failed: {e}")
        return {}
    row = next((r for r in sorted(rows, key=lambda r: r["timestamp"], reverse=True)
                if r["original"].split("?")[0].endswith("_flac.tar")), None)
    if row is None:
        log("no archived flac tar for eng-balm-judith")
        return {}
    try:
        blob = wayback_bytes(row["timestamp"], row["original"])
    except Exception as e:  # noqa: BLE001
        log(f"judith tar fetch failed: {e}")
        return {}
    label = f"wayback:{row['original']}"
    log(f"judith flac tar: {row['original']} ({len(blob)} bytes)")
    got = entries_from_archive(blob, label, WORDS)

    tf = tarfile.open(fileobj=io.BytesIO(blob))
    names = tf.getnames()
    index_name = next((n for n in names if n.endswith("index.tags.txt")), None)
    if index_name is None:
        return got
    entries = parse_tags(tf.extractfile(index_name).read().decode("utf-8", "replace"))
    prefix = os.path.dirname(index_name)
    for text, word in ARTICLE_TEXTS.items():
        section = next((s for s, t in entries.items()
                        if norm(t.get("SWAC_TEXT", "")) == text), None)
        if section is None:
            log(f"  article text not in index: {text!r}")
            continue
        member = "/".join(p for p in (prefix, section.lstrip("./")) if p)
        if member not in names:
            member = next((n for n in names if n.endswith("/" + os.path.basename(section))), None)
            if member is None:
                continue
        dest = os.path.join(OUT_DIR, f"article-a-{word}.flac")
        with open(dest, "wb") as f:
            f.write(tf.extractfile(member).read())
        log(f"  article clip: {text!r} -> {dest}")
    return got


if __name__ == "__main__":
    sys.exit(main())
