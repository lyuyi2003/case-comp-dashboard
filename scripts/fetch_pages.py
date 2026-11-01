"""Step 1 of an update: find out which web pages have changed.

Run it with:  python scripts/fetch_pages.py

It visits every page the project depends on, boils each one down to plain text
and takes a fingerprint (a hash) of that text. A page with the same fingerprint
as last time hasn't changed, so Claude doesn't need to read it. That is what
keeps each update small.

The results go into .cache/:
  fetch-report.json   what happened to each page
  pages/              the text of the pages Claude should read

Run with --baseline to record today's fingerprints without flagging anything
as changed. Use that only when the data was verified by hand the same day.
"""

import hashlib
import io
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Imported here so that a broken setup stops the run straight away, instead of
# making every PDF look like a page that failed to load.
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rules import PROJECT_ROOT

# We say who we are. If a site refuses this, we respect that and don't disguise
# the request as a person's browser.
USER_AGENT = "CaseCompTracker/1.0 (personal student project)"
TIMEOUT_SECONDS = 25
MAX_WORKERS = 8
MIN_TEXT_LENGTH = 200

CACHE = PROJECT_ROOT / ".cache"
HASH_FILE = PROJECT_ROOT / "data" / "page-hashes.json"

BLOCK_MARKERS = ("_Incapsula_Resource", "Request unsuccessful", "Attention Required! | Cloudflare")
SKIPPED_TAGS = {"script", "style", "noscript", "svg", "template"}
BREAK_TAGS = {"p", "div", "li", "br", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}

# Listing pages are long and change constantly, so only the parts that mention
# competitions are compared.
COMPETITION_WORDS = re.compile(
    r"case[- ](competition|challenge|comp\b|study competition)"
    r"|consulting (competition|challenge)|strategy challenge|business challenge",
    re.IGNORECASE,
)
LINES_AROUND_A_MATCH = 3

RANDOM_CODE = re.compile(r"\b[0-9a-f]{16,}\b")
MIN_SENTENCE_WORDS = 6


class TextExtractor(HTMLParser):
    """Keep the words on a page and drop its code and styling."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED_TAGS:
            self.skip_depth += 1
        elif tag in BREAK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIPPED_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif tag in BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def html_to_text(page):
    extractor = TextExtractor()
    extractor.feed(page)
    lines = (" ".join(line.split()) for line in "".join(extractor.parts).splitlines())
    return "\n".join(line for line in lines if line)


def pdf_to_text(body):
    # The PDF library prints long warnings about fonts that don't affect the text.
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    reader = PdfReader(io.BytesIO(body))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def relevant_lines(text):
    """Keep only the lines near a mention of a case competition."""
    lines = text.splitlines()
    keep = set()
    for number, line in enumerate(lines):
        if COMPETITION_WORDS.search(line):
            keep.update(range(number - LINES_AROUND_A_MATCH, number + LINES_AROUND_A_MATCH + 1))
    return "\n".join(lines[n] for n in sorted(keep) if 0 <= n < len(lines))


def meaningful_text(text):
    """Remove the parts of a page that change without anything really changing.

    Some sites add a random code on every visit or shuffle their menus. Facts
    are in sentences or contain a number, so those are the lines worth comparing.
    """
    kept = []
    for line in text.splitlines():
        line = RANDOM_CODE.sub("", line)
        if any(character.isdigit() for character in line) or len(line.split()) >= MIN_SENTENCE_WORDS:
            kept.append(line)
    return "\n".join(kept)


def fingerprint(text):
    """A short code that changes whenever the meaningful words change."""
    normalised = " ".join(meaningful_text(text).split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:24]


def is_blocked(text):
    return any(marker in text for marker in BLOCK_MARKERS)


def skip_reason(url, skip_rules):
    for rule in skip_rules:
        if url.startswith(rule["prefix"]):
            return rule["reason"]
    return None


def collect_pages(competitions, sources):
    """Build the list of pages to visit, with no page listed twice."""
    pages = {}

    def add(url, kind):
        pages.setdefault(url, {"url": url, "kind": kind, "ids": []})
        return pages[url]

    for record in competitions:
        urls = [source["url"] for source in record["source_urls"]]
        if record["official_url"]:
            urls.append(record["official_url"])
        for url in dict.fromkeys(urls):
            add(url, "source")["ids"].append(record["id"])

    for listing in sources["listings"]:
        page = add(listing["url"], listing["type"])
        page["name"] = listing["name"]
    return list(pages.values())


def page_state(old_hash, new_hash, listing_is_empty):
    if listing_is_empty and not old_hash:
        return "unchanged"
    if old_hash == new_hash:
        return "unchanged"
    return "changed"


def download(url):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read(), response.headers.get_content_type()


def read_page(page, old_hashes, skip_rules):
    """Visit one page and report what happened. Problems never stop the run."""
    url = page["url"]
    result = dict(page, state="failed", error=None, hash=None, file=None)

    reason = skip_reason(url, skip_rules)
    if reason:
        return dict(result, state="blocked", error=reason)

    try:
        body, content_type = download(url)
        if body.startswith(b"%PDF") or content_type == "application/pdf":
            text = pdf_to_text(body)
            is_scanned = len(text.strip()) < MIN_TEXT_LENGTH
            new_hash = hashlib.sha256(body).hexdigest()[:24] if is_scanned else fingerprint(text)
        else:
            text = html_to_text(body.decode("utf-8", errors="replace"))
            if is_blocked(body.decode("utf-8", errors="replace")):
                return dict(result, state="blocked", error="The site refused automated visitors")
            if len(text) < MIN_TEXT_LENGTH:
                return dict(result, error="The page has no readable text without a browser")
            new_hash = None

        is_listing = page["kind"] != "source"
        if is_listing:
            text = relevant_lines(text)
        if new_hash is None or is_listing:
            new_hash = fingerprint(text)

        old_hash = old_hashes.get(url)
        return dict(result, state=page_state(old_hash, new_hash, is_listing and not text), hash=new_hash, text=text)
    except HTTPError as error:
        return dict(result, error=f"HTTP {error.code}")
    except URLError as error:
        return dict(result, error=f"Could not connect: {error.reason}")
    except Exception as error:  # A strange page must not stop the whole update.
        return dict(result, error=f"{type(error).__name__}: {error}")


def save_page_text(result, number):
    """Write a changed page to a file and return the report entry."""
    text = result.pop("text", None)
    if result["state"] == "changed" and text:
        path = CACHE / "pages" / f"page-{number:03}.txt"
        path.write_text(f"Source: {result['url']}\n\n{text}", encoding="utf-8")
        result["file"] = path.relative_to(PROJECT_ROOT).as_posix()
    return result


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    baseline = "--baseline" in sys.argv
    competitions = load_json(PROJECT_ROOT / "data" / "competitions.json")["competitions"]
    sources = load_json(PROJECT_ROOT / "config" / "sources.json")
    old_hashes = load_json(HASH_FILE)

    (CACHE / "pages").mkdir(parents=True, exist_ok=True)
    for old_file in (CACHE / "pages").glob("*.txt"):
        old_file.unlink()

    pages = collect_pages(competitions, sources)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(lambda page: read_page(page, old_hashes, sources["skip"]), pages))

    if baseline:
        for result in results:
            result.pop("text", None)
            if result["hash"]:
                old_hashes[result["url"]] = result["hash"]
                result["state"] = "unchanged"
        with open(HASH_FILE, "w", encoding="utf-8") as f:
            json.dump(old_hashes, f, indent=2, sort_keys=True)
            f.write("\n")

    report = [save_page_text(result, number) for number, result in enumerate(results, 1)]
    with open(CACHE / "fetch-report.json", "w", encoding="utf-8") as f:
        json.dump({"date": date.today().isoformat(), "pages": report}, f, indent=2)

    counts = {}
    for page in report:
        counts[page["state"]] = counts.get(page["state"], 0) + 1
    print(f"Checked {len(report)} pages: {counts}")
    for page in report:
        if page["state"] == "changed":
            print(f"  changed: {page['url']}")


if __name__ == "__main__":
    main()
