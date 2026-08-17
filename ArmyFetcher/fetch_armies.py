#!/usr/bin/env python3
"""Roster fetcher driver: scrape a datasheet source into w40k-sim JSON.

Requires: requests, beautifulsoup4  (pip install requests beautifulsoup4)

Two interchangeable parser libraries are selected with --source:
  * wahapedia (default) -> army_parse_wahapedia (one datasheets.html per
    faction; Legends and Space-Marines chapters split into separate files)
  * 40kapp             -> army_parse_40kapp (one page per unit; sub-factions
    discovered by crawling faction pages)
Each library exposes the same interface used here:
  BASE, DEFAULT_OUT, collect(src, faction=None, debug=False)
      -> yields (filename_stem, data_dict)

This file owns only the generic bits: the page source (live HTTP with an
optional raw-HTML dump, or offline replay from a dump), and writing the
yielded JSON files. All source-specific discovery/parsing lives in the
library.

Modes
-----
  python fetch_armies.py --faction aeldari                  # wahapedia (default)
  python fetch_armies.py --source 40kapp --faction tau-empire
  python fetch_armies.py --source 40kapp --dump site_dump   # save raw HTML
  python fetch_armies.py --from-dump site_dump ...          # offline replay

Output goes to the library's default dir (fetched_armies_wahapedia /
fetched_armies_40kapp) unless --out is given.
"""
import argparse
import json
import os
import re
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import army_parse_40kapp
import army_parse_wahapedia

SOURCES = {
    "wahapedia": army_parse_wahapedia,
    "40kapp": army_parse_40kapp,
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; w40k-roster-fetch/1.0)"}


def _url_to_path(url, root):
    """Map a page URL to a file path under 'root' (mirrors the URL path),
    consistent across sources: a trailing-slash directory URL -> .../index.html
    (Wahapedia nav pages); a URL that already has an extension is kept as-is
    (Wahapedia datasheets.html); an extensionless URL gets .html (40k.app
    faction/unit pages)."""
    path = urlparse(url).path
    if path.endswith("/"):
        return os.path.join(root, *path.strip("/").split("/"), "index.html")
    if os.path.splitext(path)[1]:
        return os.path.join(root, *path.strip("/").split("/"))
    stem = path.strip("/") or "index"
    return os.path.join(root, *stem.split("/")) + ".html"


class PageSource:
    """Uniform page source: live HTTP (optionally dumping raw HTML) or
    offline replay from a saved dump. get(url) -> BeautifulSoup."""

    def __init__(self, delay=0.7, dump_dir=None, from_dump=None):
        self.delay = delay
        self.dump_dir = dump_dir
        self.from_dump = from_dump
        self.session = None
        if not from_dump:
            import requests
            self.session = requests.Session()
            self._exc = requests.RequestException

    def get(self, url):
        """Return the page HTML for url, from the local cache/dump when available, else via a live fetch."""
        return BeautifulSoup(self.get_raw(url), "html.parser")

    def get_raw(self, url):
        """Raw HTML string for 'url' (from dump or network). Lets a library
        chunk-parse a huge page instead of building one giant tree."""
        if self.from_dump:
            path = _url_to_path(url, self.from_dump)
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        html = self._fetch_live(url)
        if self.dump_dir:
            path = _url_to_path(url, self.dump_dir)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(html)
        time.sleep(self.delay)
        return html

    def _fetch_live(self, url, retries=3):
        """Fetch url over HTTP with simple retry/backoff; returns the response text."""
        last = None
        for attempt in range(retries):
            try:
                r = self.session.get(url, headers=HEADERS, timeout=30)
                r.raise_for_status()
                return r.text
            except self._exc as exc:
                last = exc
                time.sleep(self.delay * (attempt + 2))
        raise RuntimeError(f"failed to fetch {url}: {last}")


def _parse_selection(text, factions):
    """Menu input -> list of chosen slugs. Accepts 'all', or a comma/space
    separated mix of list numbers (1-based) and slugs. Unknown tokens are
    ignored. Empty / 'all' selects every faction."""
    text = (text or "").strip().lower()
    if text in ("", "all", "a", "*"):
        return [s for s, _ in factions]
    by_slug = {s.lower(): s for s, _ in factions}
    chosen, seen = [], set()
    for tok in re.split(r"[\s,]+", text):
        slug = None
        if tok.isdigit() and 1 <= int(tok) <= len(factions):
            slug = factions[int(tok) - 1][0]
        elif tok in by_slug:
            slug = by_slug[tok]
        if slug and slug not in seen:
            seen.add(slug)
            chosen.append(slug)
    return chosen


def _choose_factions(factions):
    """Print the launch menu and return the chosen slugs from stdin."""
    print("\nAvailable factions:")
    for i, (slug, name) in enumerate(factions, 1):
        print(f"  {i:2}. {name}  ({slug})")
    print("  all. every faction")
    reply = input("\nWhich faction(s)? [numbers/slugs, or 'all']: ")
    return _parse_selection(reply, factions)


def main():
    """Command-line entry point: parse args (source, faction, dump/live, output dir) and write the fetched army JSON files."""
    cli = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("--source", choices=sorted(SOURCES), default="wahapedia",
                     help="datasheet source library (default: wahapedia)")
    cli.add_argument("--faction", action="append", default=[],
                     help="faction slug(s) to fetch, skipping the menu "
                     "(repeatable; 'all' for every faction)")
    cli.add_argument("--out", help="output directory "
                     "(default: the source's own dir)")
    cli.add_argument("--delay", type=float, default=0.7,
                     help="seconds between live requests (be polite)")
    cli.add_argument("--dump", metavar="DIR",
                     help="also save every fetched page's raw HTML under DIR")
    cli.add_argument("--from-dump", metavar="DIR", dest="from_dump",
                     help="work offline: read pages from a saved dump DIR")
    cli.add_argument("--debug", action="store_true",
                     help="verbose per-unit diagnostics to stderr")
    args = cli.parse_args()

    lib = SOURCES[args.source]
    out_dir = args.out or lib.DEFAULT_OUT
    os.makedirs(out_dir, exist_ok=True)
    src = PageSource(delay=args.delay, dump_dir=args.dump,
                     from_dump=args.from_dump)

    # 'fetch_all' uses the single-pass, globally-deduplicated path:
    # collect(faction=None) discovers every faction+sub-faction page once and
    # classifies main vs sub itself, so a page reachable from several parents
    # (e.g. a Space-Marines chapter linked both from /factions and from the
    # Space-Marines page) is crawled and parsed only once. Iterating slug by
    # slug would re-crawl each overlapping faction. See collect().
    if args.faction:                                    # non-interactive path
        fetch_all = "all" in args.faction
        chosen = None if fetch_all else list(dict.fromkeys(args.faction))
    else:
        chosen = _choose_factions(lib.list_factions(src))
        full = [s for s, _ in lib.list_factions(src)]
        fetch_all = chosen is not None and set(chosen) == set(full)
        if fetch_all:
            chosen = None
    if chosen is not None and not chosen:
        print("No faction selected.")
        return

    print(f"\nsource={args.source} -> {out_dir}/"
          + (" (offline dump)" if args.from_dump else ""))
    written = 0
    # jobs: None -> a single collect(None) that fetches everything at once;
    # otherwise one collect(slug) per chosen faction.
    jobs = [None] if fetch_all else chosen
    for faction in jobs:
        label = faction if faction else "all"
        try:
            for stem, data in lib.collect(src, faction, args.debug):
                n = len(data["armies"][0]["units"])
                if not n:
                    continue
                path = os.path.join(out_dir, f"{stem}.json")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=1, ensure_ascii=False)
                print(f"  wrote {path}  ({n} units)")
                written += 1
        except FileNotFoundError:
            print(f"  ({label}: not available - skipped)")
        except Exception as exc:                         # noqa: BLE001
            print(f"  ({label}: failed - {exc})")
    print(f"done: {written} file(s)")
    # Both parsers skip anything they cannot recognise; a long run scrolls
    # the individual warnings off the screen, so repeat the count here.
    if army_parse_40kapp.WARNINGS:
        print(f"{len(army_parse_40kapp.WARNINGS)} warning(s) - data was "
              f"skipped; scroll up for details")


if __name__ == "__main__":
    main()
