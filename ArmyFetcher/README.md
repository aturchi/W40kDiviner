# ArmyFetcher

A command-line **roster scraper** for the [W40kDiviner](../README.md) suite. It
downloads Warhammer 40,000 (11th ed.) datasheets from a public source and writes
them directly in the **native `w40k-sim/6` JSON** format the W40kDiviner programs
read.

**What it does:** It automatially downloads unit descriptios for the various 
W40k armies and populates JSONS for later use with attack analyzer and game
assistant.

**What it does NOT:** It creates **unusable abilities** populated only with a text
description. You must properly create ability effects with the profile editor if
you want to use them in the above programs. Also consider that
**weapons are automatically placed on the first model**. This is a limitation of
the engine that can't interpretate the loadout text in a robust way. You must
manually move them to the other unit's moodels, if you want (programs works the
same if they are all on the first one, that's mostly aesetics). Finally consider
that there may be errors in the sources that you must manually correct.

Two interchangeable parser back-ends are provided and produce **identical**
output for the same unit, which doubles as a built-in cross-check:

| `--source` | Site | Notes |
|---|---|---|
| `wahapedia` *(default)* | <https://wahapedia.ru> | One `datasheets.html` per faction; Legends and Space-Marines chapters are separated offline. |
| `40kapp` | <https://www.40k.app> | One page per unit; no legends; sub-factions discovered by crawling faction pages |

Both back-ends feed the **same** build layer, so a unit shared between the two
sources comes out with identical syntax and characteristics (in theory).

**WARNING:** If the websites change something, you have to change the
corresponding parser code. That should be obvious, however it's always worth
mentioning... Please ask Claude before asking me :-)

---

## Requirements

- **Python 3.8+**
- `requests` and `beautifulsoup4`:

  ```bash
  pip install requests beautifulsoup4
  ```

---

## Usage

Run from inside the `ArmyFetcher/` folder:

```bash
# Interactive: pick faction(s) from a numbered menu (wahapedia by default)
python3 fetch_armies.py

# Non-interactive: name the faction slug(s), skipping the menu
python3 fetch_armies.py --faction aeldari
python3 fetch_armies.py --source 40kapp --faction tau-empire

# Every faction at once
python3 fetch_armies.py --faction all

# Save every fetched page's raw HTML (for offline reuse / debugging)
python3 fetch_armies.py --source 40kapp --dump site_dump --faction tau-empire

# Work fully offline, replaying a saved dump (no network)
python3 fetch_armies.py --from-dump site_dump --faction tau-empire
```

### Options

| Option | Meaning |
|---|---|
| `--source {wahapedia,40kapp}` | Datasheet source library (default `wahapedia`). |
| `--faction SLUG` | Faction slug to fetch, skipping the menu. **Repeatable**; use `all` for every faction. |
| `--out DIR` | Output directory (default: the source's own dir, see below). |
| `--delay SECONDS` | Seconds between live requests — be polite to the servers (default `0.7`). |
| `--dump DIR` | Also save every fetched page's raw HTML under `DIR`. |
| `--from-dump DIR` | Work offline: read pages from a previously saved dump `DIR`. |
| `--debug` | Verbose per-unit diagnostics to stderr. |

If no `--faction` is given, an **interactive menu** lists the available factions
(numbers or slugs, or `all`).

---

## Output

One JSON file per faction (and per Space-Marines chapter / sub-faction), written
to the source's default directory unless `--out` overrides it:

- `fetched_armies_wahapedia/` for `--source wahapedia`
- `fetched_armies_40kapp/` for `--source 40kapp`

Each file is a native `w40k-sim/6` army file, ready to open in the Profile
Editor, Attack Analyzer or Game Assistant, or to merge with
[`join_armies.py`](../README.md#program-4--join-armies-cli).

---

## How it works

`fetch_armies.py` owns only the **generic** bits — the page source (live HTTP,
with an optional raw-HTML dump) and writing the yielded JSON files. All
source-specific discovery and parsing lives in the two parser libraries, which
expose the same interface:

```python
BASE, DEFAULT_OUT, collect(src, faction=None, debug=False)
    # -> yields (filename_stem, data_dict)
```

- **`army_parse_40kapp.py`** — pure parsing/JSON-building from already-linearised
  page text (no network in this module), so its fragile assumptions are
  unit-tested offline.
- **`army_parse_wahapedia.py`** — turns Wahapedia HTML into the *same*
  intermediate structure `army_parse_40kapp` produces, then hands it to that
  module's shared build layer. This is what makes the two sources produce
  identical units (and enables cross-checking).

**Live fetching is polite:** a configurable delay between requests and a
descriptive `User-Agent`. The `--dump` / `--from-dump` pair lets you fetch once
and then re-parse offline as many times as you like without hammering the site.

---

## Cross-check / QA

`QA_CROSSCHECK.md` documents an offline cross-check of the two sources used for
testing (T'au and Space Marines): a per-unit comparison of model stats, weapons,
keywords and core/faction abilities. The T'au set aligns perfectly; the residual
Space-Marines differences are traced to genuine **data discrepancies between the
two sites**, not parsing bugs (details in that file).
These problems may or may not be solved in the future. Please just note that
sometimes the sources are wrong on some unit's stats.

## Tests

`test_army_parse.py` is an offline self-test that runs the pure
parser/builder against linearised line fixtures derived from real pages (no
network required):

```bash
python3 test_army_parse.py
```

---

## Legal / etiquette

This scraper is for **personal, non-commercial** use. Respect the target sites'
terms of service and `robots.txt`, keep the request delay reasonable, and prefer
`--from-dump` when iterating. Datasheet content is the property of **Games
Workshop Ltd.** and of the respective sites; W40kDiviner and ArmyFetcher are
unofficial fan tools not affiliated with or endorsed by Games Workshop. I'm not
responsible fot your use or abuse of this program. Please resepect all copyrightt
laws applicable in your county and get the proper authorizations before
using this program.
