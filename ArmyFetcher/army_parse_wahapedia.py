"""Wahapedia datasheet parser (army_parse_wahapedia).

Wahapedia serves ALL of a faction's datasheets in a single
factions/<slug>/datasheets.html page. Legends units and Space-Marines
chapter units are all present in the raw HTML, hidden only by CSS, so
they can be separated offline:
  * a datasheet is a  div.dsOuterFrame.datasheet
  * Legends carry the CSS class  sLegendary . (Forge World carries a
    separate sForgeWorld class which we ignore: a Forge World unit that is
    not also sLegendary is a current, main-file datasheet.)
  * Space Marines datasheets carry CH<code> class tokens (one per chapter
    that can field them); CHC0 = the base 'no supplements' roster.

This module ONLY does Wahapedia HTML -> the same intermediate `parsed`
dict that army_parse_40kapp.parse_unit produces, then hands it to the
shared build layer in army_parse_40kapp (build_units / faction_json). That
guarantees a unit shared between the two sources comes out with identical
syntax and characteristics - a built-in cross-check.

Interface shared with army_parse_40kapp (called by fetch_armies.py):
  BASE, DEFAULT_OUT
  collect(src, faction=None) -> yields (out_filename_stem, data_dict)
"""
import re

from bs4 import BeautifulSoup

import army_parse_40kapp as ap40

BASE = "https://wahapedia.ru"
DEFAULT_OUT = "fetched_armies_wahapedia"
_PREFIX = "/wh40k11ed/factions/"

# Space Marines chapter <select> code -> label; filled lazily per page too.
_SM_SLUG = "space-marines"

_BASE_PAREN = re.compile(r"\s*\(.*?\)\s*$")          # "Asurmen (⌀40mm)"
_SKILL = re.compile(r"^(?:\d\+|N/?A|[-\u2010-\u2014])$", re.I)


# --------------------------------------------------------------- helpers
def _text(el, sep=" "):
    """Whitespace-collapsed text of a BeautifulSoup element, joining with
    'sep'; empty string if 'el' is None."""
    return el.get_text(sep, strip=True) if el else ""


def _kw_head(label):
    """Regex matching the keyword-column heading, in BOTH syntaxes:
    the plain 'KEYWORDS:' and the per-model 'KEYWORDS - <GROUP>:' used when
    a datasheet gives different keywords to different models ('KEYWORDS -
    ALL MODELS: ... | ANCIENT: ...'). Hyphen, en dash and em dash accepted."""
    return re.compile(rf"^\s*{label}\s*(?:[-\u2013\u2014][^:]*)?:", re.I)


def _kw_after(label, div):
    """Keywords of the block starting with 'LABEL:' -> flat list.

    The column holds one <span> group per keyword set, separated by
    span.dsVertLine markers; the plain syntax simply has a single group.
    Per-model groups are MERGED into one unit-level list (the engine has no
    per-model keywords) and de-duplicated case-insensitively, keeping
    document order."""
    for el in div.find_all(string=_kw_head(label)):
        col = el.parent
        groups = [s for s in col.find_all("span", recursive=False)
                  if "dsVertLine" not in (s.get("class") or [])]
        if groups:
            blocks = [g.get_text(" ", strip=True) for g in groups]
        else:                                  # no span wrapper: plain text
            block = col.get_text(" ", strip=True)
            blocks = [_kw_head(label).split(block, maxsplit=1)[-1]]
        out, seen = [], set()
        for block in blocks:
            for kw in re.split(r"[;,]", block):
                kw = kw.strip()
                if kw and kw.casefold() not in seen:
                    seen.add(kw.casefold())
                    out.append(kw)
        return out
    return []


def _inv(text):
    """Invuln value -> int (2..6) from '4+', '4+*' (conditional), etc."""
    m = re.search(r"\d", text or "")
    return int(m.group()) if m else None


def _model_names(div):
    """Per-profile model names from .dsModelName (positional: Nth name ->
    Nth .dsProfileWrap)."""
    return [s.get_text(" ", strip=True) for s in div.select(".dsModelName")]


def _split_name(raw):
    """A profile header can cover several model types sharing one stat line
    ('FARSTALKERS & KILL-BROKER'); split so each maps to its composition
    entry."""
    parts = re.split(r"\s*&\s*|\s+/\s+|\s+and\s+", raw) if raw else []
    return [p.strip() for p in parts if p.strip()] or [raw]


def _parse_stats(div):
    """Each div.dsProfileWrap is one stat profile. Read the six .dsCharValue
    cells positionally (Wahapedia labels only the first profile). A profile
    whose .dsModelName joins several model types is split into one entry per
    type (same stats) so composition counts match. Invuln inherited from the
    datasheet when a profile has none."""
    names = _model_names(div)
    inv_el = div.select_one(".dsCharInvulValue")
    ds_inv = _inv(_text(inv_el)) if inv_el else None
    models = []
    for i, prof in enumerate(div.select(".dsProfileWrap")):
        vals = [_text(v) for v in prof.select(".dsCharValue")][:6]
        if len(vals) < 6:
            continue
        M_, T_, Sv, W_, LD, OC = vals
        pinv_el = prof.select_one(".dsCharInvulValue")
        pinv = _inv(_text(pinv_el)) if pinv_el else None
        stats = {
            "M": ap40._num(M_), "T": ap40._num(T_), "Sv": ap40._num(Sv),
            "W": ap40._num(W_), "LD": ap40._num(LD), "OC": ap40._num(OC),
            "invuln": pinv if pinv is not None else ds_inv, "fnp": None,
        }
        raw = names[i] if i < len(names) else ""
        for part in _split_name(raw):
            models.append({"name": part.title(), **stats})
    return models


def _comp_lines(div):
    """The 'UNIT COMPOSITION' bullets ('1 Kroot Kill-broker',
    '9 Kroot Farstalkers', ...) up to the wargear ('equipped with') text.
    A datasheet offering two size options separates them with an 'OR' line
    (e.g. Wolf Scouts: 6-model OR 12-model); only the FIRST option is taken
    (the minimum size build_units models), so the model list is not
    duplicated across both options."""
    hdr = next((h for h in div.select(".dsHeader")
                if "COMPOSITION" in h.get_text(strip=True).upper()), None)
    blk = hdr.find_next_sibling() if hdr else None
    if not blk:
        return []
    out = []
    for ln in blk.get_text("\n").split("\n"):
        ln = ap40.normalise_dashes(ln).strip()
        if "equipped with" in ln.lower():
            break
        if ln.upper() == "OR" and out:        # second size option: stop
            break
        if ap40.is_size_cap_line(ln):         # '10 MODELS MAXIMUM': a cap,
            continue                          # not a model group
        if re.match(r"\d+(?:-\d+)?\s+\S", ln):
            out.append(ln)
    return out


_RNG_CELL = re.compile(r'^(?:\d+"|Melee|N/?A)$', re.I)
_ATTACKS_CELL = re.compile(r"^\d*D?\d+(?:[+-]\d+)?$", re.I)


def _weapon_rows(div, where=""):
    """All weapon data rows in the datasheet as (name, keywords, cells6),
    where cells6 = [RNG, A, skill, S, AP, D]. A weapon row ends in those 6
    cells with the skill cell shaped like '3+' or 'N/A'; the name cell is
    the one just before, its kwbw spans are the weapon keywords.

    A row whose skill cell is not recognised is skipped - silently, which
    is how a site change could remove weapons without any error - so a row
    that otherwise HAS the shape of a weapon (range + attacks) is reported
    via ap40.warn instead."""
    out, suspect = [], []
    for tr in div.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 7:
            continue
        six = cells[-6:]
        vals = [_text(c) for c in six]
        if not _SKILL.match(vals[2]):         # stats[2] must be the skill
            if _RNG_CELL.match(vals[0]) and _ATTACKS_CELL.match(vals[1]):
                suspect.append((_text(cells[-7]), vals))
            continue
        name_cell = cells[-7]
        # keywords are kwbw spans APPENDED after the name; remove those
        # elements (not a text-replace, which would also strike a keyword
        # word that is part of the name, e.g. 'Pulse pistol' + kw 'pistol').
        kws = [_text(s) for s in name_cell.select(".kwbw")]
        for s in name_cell.select(".kwbw"):
            s.extract()
        nm = re.sub(r"\s{2,}", " ",
                    name_cell.get_text(" ", strip=True)).strip(" ,")
        if nm:
            out.append((nm, kws, vals))
    for nm, vals in suspect:
        ap40.warn(f"{where or 'unit'}: weapon row '{nm or '?'}' skipped - "
                  f"unexpected skill cell {vals[2]!r} (row: {vals})")
    return out


def _parse_weapons(div, where=""):
    """Ranged and melee weapon profiles parsed from a datasheet div, as two
    lists of native weapon dicts. 'where' names the unit for warnings."""
    ranged, melee = [], []
    for nm, kws, v in _weapon_rows(div, where):
        rng, a, skill, s, ap, d = v
        melee_w = rng.strip().lower() == "melee"
        w = {"name": nm, "keywords": kws,
             "type": "Melee" if melee_w else "Ranged",
             "RNG": None if melee_w else ap40._num(rng), "A": a,
             "skill": ap40._num(skill), "S": ap40._num(s),
             "AP": ap40._num(ap), "D": d}
        (melee if melee_w else ranged).append(w)
    return ranged, melee


def _ability_blocks(div):
    """The .dsAbility blocks under the 'ABILITIES' and 'WARGEAR ABILITIES'
    section headers (WARGEAR ABILITIES holds optional wargear abilities,
    between ABILITIES and UNIT COMPOSITION). Wahapedia reuses .dsAbility for
    the composition/cost/led-by/keyword boxes too, so bound it by header."""
    out, in_ab = [], False
    for el in div.find_all("div"):
        cls = el.get("class") or []
        if "dsHeader" in cls:
            in_ab = el.get_text(strip=True).upper() in (
                "ABILITIES", "WARGEAR ABILITIES")
            continue
        if in_ab and "dsAbility" in cls:
            out.append(el)
    return out


def _split_by_bold(ab):
    """Split one ability box into (name, description) per bold HEADING - a
    heading is a bold ending in ':' ('Breach and Clear:', 'DS8 Support
    Turret:'). Bold words used for inline emphasis inside a description
    ('Stratagem', 'Aura') do NOT end in ':' and stay in the text. Returns
    [] when the box has no heading (a CORE/FACTION keyword box)."""
    names = [b.get_text(" ", strip=True) for b in ab.select("b, strong")
             if b.get_text(strip=True).endswith(":")]
    text = re.sub(r"\s+", " ", ab.get_text(" ", strip=True))
    if not names:
        return []
    pos, idx = [], 0
    for nm in names:
        p = text.find(nm, idx)
        if p < 0:
            p = text.find(nm)
        if p >= 0:
            pos.append((p, nm))
            idx = p + len(nm)
    out = []
    for i, (p, nm) in enumerate(pos):
        start = p + len(nm)
        end = pos[i + 1][0] if i + 1 < len(pos) else len(text)
        desc = text[start:end].strip().lstrip(":").strip()
        out.append((nm.rstrip(":").strip(), desc))
    return out


def _keyword_box(ab):
    """If this box is a 'CORE:' / 'FACTION:' keyword box, return
    ('core'|'faction', [keyword, ...]); otherwise (None, []). The keywords
    are the comma-separated entries of the bold list after the label
    ('CORE: Deep Strike, Leader' -> ['Deep Strike', 'Leader'])."""
    full = re.sub(r"\s+", " ", ab.get_text(" ", strip=True))
    m = re.match(r"\s*(CORE|FACTION)\s*:\s*(.*)$", full, re.I)
    if not m:
        return None, []
    kind = m.group(1).lower()
    kws = [k.strip() for k in re.split(r"[;,]", m.group(2)) if k.strip()]
    return kind, kws


def _parse_abilities(div):
    """Split the ABILITIES / WARGEAR ABILITIES boxes into
    (core_keywords, faction_keywords, unit_abilities).

    A box whose text starts with 'CORE:' or 'FACTION:' is a keyword box:
    its keywords go to the dedicated core/faction lists (NOT into the unit
    ability list, and without the 'CORE:'/'FACTION:' prefix). Every other
    box is a real unit ability - split into one (name, description) per bold
    ':' heading, or kept whole. The Designer's Note is kept on purpose, to
    delete by hand."""
    core, faction, unit = [], [], []
    for ab in _ability_blocks(div):
        kind, kws = _keyword_box(ab)
        if kind == "core":
            core.extend(kws)
            continue
        if kind == "faction":
            faction.extend(kws)
            continue
        parts = _split_by_bold(ab)
        if parts:
            unit.extend(parts)
            continue
        full = re.sub(r"\s+", " ", ab.get_text(" ", strip=True))
        bolds = [b.get_text(" ", strip=True) for b in ab.select("b, strong")]
        name = bolds[0] if bolds else full.split(":", 1)[0]
        at = full.find(name) if name else -1
        desc = full[at + len(name):].strip().lstrip(":").strip() if at >= 0 else ""
        if name:
            unit.append((name.strip(), desc))
    return core, faction, unit


def _collapse(text):
    """Collapse all whitespace (incl. newlines from span splits) to single
    spaces, so words split across inline spans rejoin ('gun'+'drone')."""
    return re.sub(r"\s+", " ", text).strip()


def _li_text(li):
    """Text directly inside an <li>, excluding any nested <ul> (walked
    separately)."""
    parts = []
    for child in li.children:
        if getattr(child, "name", None) == "ul":
            continue
        parts.append(child.get_text(" ") if getattr(child, "name", None)
                     else str(child))
    return _collapse(" ".join(parts))


def _walk_ul(ul, depth, out):
    """One line per <li>; nested <ul> items are indented and bulleted."""
    for li in ul.find_all("li", recursive=False):
        text = _li_text(li)
        if text:
            prefix = ("  " * depth + "\u25e6 ") if depth else ""
            out.append(prefix + text)
        for sub in li.find_all("ul", recursive=False):
            _walk_ul(sub, depth + 1, out)


def _walk_block(blk, out):
    """Walk a section block into newline-separated lines. A block that is a
    <ul>, or contains one, is treated as structured: each <li> is a line
    (nested items indented) and any loose text between lists is its own
    line. A block with NO list is prose (e.g. a rule paragraph with inline
    keyword spans like COMMANDER / FARSIGHT) and is collapsed to a single
    line, so inline spans do not each land on their own line."""
    if getattr(blk, "name", None) == "ul":
        _walk_ul(blk, 0, out)
        return
    if not blk.find("ul"):                    # prose: no list markup
        text = _collapse(blk.get_text(" "))
        if text:
            out.append(text)
        return
    for child in blk.children:
        name = getattr(child, "name", None)
        if name == "ul":
            _walk_ul(child, 0, out)
        else:
            text = _collapse(child.get_text(" ") if name else str(child))
            if text:
                out.append(text)


def _section_text(div, label):
    """Text of the box right after the section header 'label' (e.g.
    'UNIT COMPOSITION', 'WARGEAR OPTIONS'). List structure and any non-list
    text are preserved as newline-separated lines (nested options indented
    with a bullet). '' when absent or just 'None.'."""
    hdr = next((h for h in div.select(".dsHeader")
                if h.get_text(strip=True).upper() == label), None)
    blk = hdr.find_next_sibling() if hdr else None
    if not blk:
        return ""
    lines = []
    _walk_block(blk, lines)
    txt = "\n".join(lines).strip()
    return "" if txt.strip(" .").lower() == "none" else txt


_COST_PART_RE = re.compile(r"^\s*(\d+)\s+\S")


def _cost_row_models(label) -> int:
    """Total model count a cost-table row is priced for, or None when the
    row is not a size row. Two label styles exist: the usual '5 models',
    and a per-group list naming the models ('3 Wolf Guard Headtakers,
    3 Hunting Wolves' = 6, '1 Sword Brother, 4 Neophytes, 5 Initiates'
    = 10), whose parts are summed. Wargear surcharge rows ('per Storm
    Shield', '+ 1 Invader ATV') match neither and return None."""
    if re.search(r"\d+\s+models?", label, re.I):
        return int(re.search(r"\d+", label).group())
    total = 0
    for part in label.split(","):
        m = _COST_PART_RE.match(part)
        if not m:
            return None
        total += int(m.group(1))
    return total or None


def _comp_costs(div):
    """Cost table -> [(models, points)]. Wahapedia lists escalating tiers
    for the same unit ('1st-2nd units: 100', '3rd+ unit: 110'); the roster
    price is the BASE tier, so keep the FIRST price seen per model count
    (later, higher tiers are ignored). Distinct model counts (real size
    options) are all kept. Wargear surcharge rows ('per Missile pod') carry
    no 'N models' and are skipped."""
    head = div.select_one(".dsUnitCostHeader")
    if not head:
        return []
    seen = {}
    for tr in head.find_parent("table").find_all("tr"):
        cells = [_text(c) for c in tr.find_all("td")]
        sizes = [n for n in (_cost_row_models(c) for c in cells)
                 if n is not None]
        pp = next((c for c in cells if re.fullmatch(r"\d+", c.strip())), None)
        if sizes and pp:
            m = sizes[0]
            if m not in seen:
                seen[m] = int(pp)
    return list(seen.items())


# --------------------------------------------------------------- datasheet
def _attach_box_keywords(ab):
    """The attachable-unit names inside one 'can be attached to' dsAbility.
    Prefers the anchor id (#Dark-Reapers -> 'Dark Reapers'), falling back to
    the visible (possibly singular) link text, Title-cased."""
    seen, out = set(), []
    for a in ab.select("a.kwbOne"):
        href = a.get("href", "")
        nm = (href.split("#")[-1].replace("-", " ").strip()
              if "#" in href else a.get_text(" ", strip=True).title())
        if nm and nm not in seen:
            seen.add(nm)
            out.append(nm)
    return out


def _attach_box_for(div, header_name):
    """The 'can be attached to' dsAbility whose preceding .dsHeader matches
    header_name ('LEADER' or 'SUPPORT'). Wahapedia uses the SAME box wording
    for both, so the header is what distinguishes a leader box from a
    support box. Returns [] when absent."""
    for ab in div.select(".dsAbility"):
        if "attached to the following" not in \
                ab.get_text(" ", strip=True).lower():
            continue
        prev = ab.find_previous("div", class_="dsHeader")
        if prev is not None and prev.get_text(strip=True).upper() \
                == header_name:
            kws = _attach_box_keywords(ab)
            if kws:
                return kws
    return []


def _parse_leads(div):
    """Units this model can LEAD: the 'can be attached to' box that sits
    under the LEADER header. A support unit's identical box (under SUPPORT)
    is deliberately excluded here so support units do NOT get a leadership
    list (which would make them be treated as leaders)."""
    return _attach_box_for(div, "LEADER")


def _parse_support(div):
    """Units this model can SUPPORT: the 'can be attached to' box under the
    SUPPORT header (a support fills a separate slot from a leader). Returns
    [] for a pure leader (no SUPPORT header)."""
    return _attach_box_for(div, "SUPPORT")


def _match_profile(profiles, cname):
    """The stat profile whose name best matches a composition entry; when
    none matches (Wahapedia groups same-stat models under one profile),
    fall back to the first profile - they share its stats."""
    key = ap40._norm(cname)
    for p in profiles:
        pn = ap40._norm(p["name"])
        if pn and (pn == key or pn in key or key in pn):
            return p
    return profiles[0]


def _align_models(profiles, comp_lines):
    """One model entry per UNIT COMPOSITION line, each carrying the stats of
    its matching profile. Wahapedia lists model types (e.g. '1 Long-quill',
    '9-19 Kroot Carnivores') even when they share one stat profile, so
    driving the model list from the composition keeps every type and the
    correct total (build_units then reads the per-type counts by name)."""
    comp = ap40._parse_composition(comp_lines)
    if not comp or not profiles:
        return profiles
    stat_keys = ("M", "T", "Sv", "W", "LD", "OC", "invuln", "fnp")
    out = []
    for _lo, _hi, cname in comp:
        prof = _match_profile(profiles, cname)
        m = {k: prof.get(k) for k in stat_keys}
        m["name"] = cname
        out.append(m)
    return out


# Header sections consumed by dedicated parsers above -> never treated as
# residual "notes" text. Weapon-table column headers are excluded too.
_HANDLED_HEADERS = {
    "", "RANGED WEAPONS", "MELEE WEAPONS", "RANGE", "A", "BS", "WS", "S",
    "AP", "D", "ABILITIES", "WARGEAR ABILITIES", "UNIT COMPOSITION",
    "WARGEAR OPTIONS", "KEYWORDS", "FACTION KEYWORDS",
}
# Detachment-level sections shared by every datasheet (huge, repeated) and
# the redundant leader-side lists: ignored, never folded into notes.
_IGNORED_HEADERS = {
    "STRATAGEMS", "DETACHMENT ABILITY", "ENHANCEMENTS",
    "LEADER", "LED BY",
}


def _is_damageable(div):
    """True if the datasheet has a 'DAMAGED: N-M WOUNDS REMAINING' bracket
    (a .dsHeader). Sets the unit-level damageable flag; the bracket text is
    NOT emitted as an ability."""
    for hd in div.select(".dsHeader"):
        if hd.get_text(strip=True).upper().startswith("DAMAGED"):
            return True
    return False


def _header_sections(div):
    """Yield (header_upper, header_label, body_text) for every .dsHeader on
    the datasheet whose header is not a stat/weapon column and whose body
    is non-empty. body_text keeps newlines via _walk_block. The DAMAGED
    bracket is included here (so its text is preserved in notes); the
    damageable flag is set independently by _is_damageable."""
    for hd in div.select(".dsHeader"):
        label = hd.get_text(" ", strip=True)
        up = label.upper()
        if up in _HANDLED_HEADERS:
            continue
        blk = hd.find_next_sibling()
        if blk is None:
            continue
        lines = []
        _walk_block(blk, lines)
        body = "\n".join(lines).strip()
        if body:
            yield up, label, body


def _residual_notes(div):
    """Every unrecognised header section, joined into the notes text with
    its title kept as a clear '[HEADER]' line so the source of each block is
    identifiable:

        [TRANSPORT]
        This model has a transport capacity of ...

        [SUPREME COMMANDER]
        Your army can include ...

    Handled sections (stats, abilities, composition, wargear), detachment-
    level sections and the redundant leader-side lists (_IGNORED_HEADERS),
    plus LEADER/SUPPORT (parsed into the leadership/support lists) are not
    included. Newlines inside a section are preserved."""
    blocks = []
    for _up, label, body in _header_sections(div):
        if _up in _IGNORED_HEADERS or _up == "SUPPORT":
            continue
        blocks.append(f"[{label}]\n{body}" if body else f"[{label}]")
    return "\n\n".join(blocks)


# CORE abilities that are really a MODEL CHARACTERISTIC the engine reads
# from the model stat block (not a rules ability). 'Feel No Pain N+' ->
# model.fnp = N. Mapped to the model key to populate. (Invulnerable save is
# always in the stat line on Wahapedia, so it is not listed here; add an
# entry if a datasheet ever carries it as a CORE ability instead.)
_CORE_STAT_KEYWORDS = {
    "feel no pain": "fnp",
}


def _extract_stat_abilities(core, models):
    """Move any CORE ability that is actually a model characteristic (e.g.
    'Feel No Pain 5+') out of the core list and onto every model's stat
    (model['fnp'] = 5). Returns the filtered core list; models are mutated
    in place. Other CORE keywords (Deadly Demise, Scouts, ...) are left as
    abilities."""
    kept = []
    for kw in core:
        low = kw.lower()
        stat = next((v for k, v in _CORE_STAT_KEYWORDS.items()
                     if low.startswith(k)), None)
        m = re.search(r"(\d)\+", kw) if stat else None
        if stat and m:
            val = int(m.group(1))
            for model in models:
                model[stat] = val
        else:
            kept.append(kw)
    return kept


def parse_datasheet(div):
    """One div.dsOuterFrame.datasheet -> the intermediate `parsed` dict
    consumed by army_parse_40kapp.build_units."""
    name = _BASE_PAREN.sub("", _text(div.select_one(".dsH2Header"))).strip()
    profiles = _parse_stats(div)
    for m in profiles:                        # single-model sheets often have
        if not m["name"]:                     # no .dsModelName -> use unit name
            m["name"] = name
    comp_lines = _comp_lines(div)
    models = _align_models(profiles, comp_lines)
    for m in models:
        if not m["name"]:
            m["name"] = name
    ranged, melee = _parse_weapons(div, name)
    core, faction, unit_ab = _parse_abilities(div)
    # 'Feel No Pain N+' is a model characteristic, not an ability: lift it
    # from core onto every model's fnp stat (the engine reads model.fnp).
    core = _extract_stat_abilities(core, models)
    # Every unrecognised header section becomes residual notes text (with its
    # title kept), including TRANSPORT / BODYGUARD; LEADER and SUPPORT are
    # parsed into the leads/support lists instead.
    notes = _residual_notes(div)
    keywords = _kw_after("KEYWORDS", div) + _kw_after("FACTION KEYWORDS", div)
    return {
        "name": name, "models": models, "ranged": ranged, "melee": melee,
        "keywords": keywords, "core_abilities": core,
        "faction_abilities": faction, "unit_abilities": unit_ab,
        "leads": _parse_leads(div), "support": _parse_support(div),
        "costs": _comp_costs(div),
        "notes": notes,
        "damageable": _is_damageable(div),
        "unit_composition": _section_text(div, "UNIT COMPOSITION"),
        "wargear_options": _section_text(div, "WARGEAR OPTIONS"),
        "composition": comp_lines,
    }


_DATAF_CH_RE = re.compile(r"CH:([0-9a-fA-F]+)")


def _chapter_codes(soup):
    """Every real chapter code offered by the datasheet-filter <select>,
    in document order, EXCLUDING the 'CH' (no-filter) pseudo-option but
    INCLUDING 'C0' (No supplements = the base roster). e.g.
    ['C0','BT','BA','BR','DA', ...]."""
    out = []
    for opt in soup.select("select.FilterSelectCH option, option.ctrlOption"):
        code = (opt.get("value") or "").strip()
        if code and code != "CH":
            out.append(code)
    return out


def _chapter_bit_map(codes):
    """Map chapter code -> bit index in Wahapedia's data-f CH bitmask.

    Wahapedia encodes chapter membership as a hex bitmask in each
    datasheet's ``data-f`` attribute (``CH:<hex>``). Bit 0 is the
    'no-filter' flag (set on every sheet, meaningless here); the real
    chapters occupy bits 1..N in ALPHABETICAL order of their code
    (verified against every current SM chapter roster). Deriving the map
    from the live <select> means a newly-added chapter is picked up
    automatically, as long as that alphabetical ordering holds."""
    return {code: i + 1 for i, code in enumerate(sorted(codes))}


_COLOR_CH_RE = re.compile(r"^dsColorFrCH([A-Z0-9]{2})$")


def _colour_chapters(div, bitmap):
    """Chapter codes taken from the datasheet's colour classes
    (``dsColorFrCH<code>`` on its inner frames; a base / multi-chapter
    sheet uses ``dsColorFrSM`` instead, which names no chapter). Verified
    to agree with the data-f CH bitmask on every current SM datasheet, so
    it is a safe last resort when the mask names no chapter at all."""
    out = set()
    for el in div.find_all(class_=_COLOR_CH_RE):
        for cls in el.get("class", []):
            m = _COLOR_CH_RE.match(cls)
            if m and (not bitmap or m.group(1) in bitmap):
                out.add(m.group(1))
    return out


def _ds_chapters(div, bitmap):
    """Set of chapter codes a datasheet belongs to. Prefers the modern
    ``data-f`` CH bitmask (decoded via 'bitmap'); falls back to the legacy
    ``CH<code>`` CSS classes on the outer div when no mask is present, so
    the parser keeps working on both old and new Wahapedia markup.

    A few sheets carry a mask with the 'no filter' bit only (Wahapedia
    shows them under no chapter filter at all, e.g. Kill Team Cassius):
    they would belong to no file, so the colour class decides instead."""
    m = _DATAF_CH_RE.search(div.get("data-f", "") or "")
    if m and bitmap:
        mask = int(m.group(1), 16)
        codes = {code for code, bit in bitmap.items() if mask >> bit & 1}
        return codes or _colour_chapters(div, bitmap)
    # legacy markup: chapter codes were CSS classes on the datasheet div
    return {c[2:] for c in div.get("class", [])
            if re.fullmatch(r"CH[A-Z0-9]{2}", c)}


def _classify(div, bitmap=None):
    """Return ('legend'|'std', set_of_chapter_codes).

    Only sLegendary marks a Legends datasheet. sForgeWorld is an orthogonal
    flag we ignore: a Forge World unit that is not also sLegendary is a
    current, main-file datasheet (e.g. T'au Manta, Ta'unar). Chapter codes
    come from the data-f CH bitmask ('bitmap' required to decode it; only
    the Space-Marines split needs them)."""
    cls = div.get("class", [])
    kind = "legend" if "sLegendary" in cls else "std"
    return kind, _ds_chapters(div, bitmap)


# --------------------------------------------------------------- collect
def _fetch_soup(src, slug):
    """Parsed BeautifulSoup for datasheet 'slug' from source 'src' (either a
    local dump or a live fetch)."""
    # src.get returns a BeautifulSoup already (fetch_armies.PageSource does),
    # so just request the datasheets page.
    return src.get(BASE + f"{_PREFIX}{slug}/datasheets.html")


_DS_MARKER = '<div class="dsOuterFrame datasheet'


def _raw(src, slug):
    """Raw datasheet HTML for 'slug' from source 'src' (dump or live)."""
    return src.get_raw(BASE + f"{_PREFIX}{slug}/datasheets.html")


def _datasheet_divs(raw):
    """Yield each datasheet as a small parsed div by splitting the raw HTML
    on the datasheet marker and parsing one chunk at a time - avoids
    building a single BeautifulSoup tree for a 40MB page (Space Marines)."""
    for part in raw.split(_DS_MARKER)[1:]:
        div = BeautifulSoup(_DS_MARKER + part, "html.parser").select_one(
            "div.dsOuterFrame.datasheet")
        if div is not None:
            yield div


def _preamble(raw):
    """Everything before the first datasheet (holds the chapter <select>)."""
    return BeautifulSoup(raw.split(_DS_MARKER, 1)[0], "html.parser")


def collect(src, faction=None, debug=False):
    """Yield (filename_stem, data_dict) for a Wahapedia faction. For a
    normal faction: <slug> and <slug>_legends. For Space Marines: the base
    roster (CHC0) plus one file per chapter with only its extra units, each
    split into standard and _legends.

    faction=None means 'all': iterate every KNOWN_FACTIONS slug. Each
    Wahapedia datasheets page is self-contained (SM chapters live inside the
    space-marines page, not as separate slugs), so there is no cross-faction
    page overlap to deduplicate. A missing slug (404 / not in dump) is
    skipped."""
    if not faction:
        for slug, _label in KNOWN_FACTIONS:
            try:
                yield from collect(src, slug, debug)
            except (FileNotFoundError, RuntimeError):
                continue
        return
    raw = _raw(src, faction)

    if faction == _SM_SLUG:
        yield from _collect_space_marines(raw, debug)
        return

    std, leg = [], []
    for div in _datasheet_divs(raw):
        kind, _ = _classify(div)
        (leg if kind == "legend" else std).append(parse_datasheet(div))
    if std:
        yield faction, ap40.faction_json(faction, std)
    if leg:
        yield f"{faction}_legends", ap40.faction_json(
            f"{faction} (Legends)", leg)


def _chapter_map(soup):
    """Chapter <select> code -> label (e.g. {'BT': 'Black Templars'})."""
    out = {}
    for opt in soup.select("select.FilterSelectCH option, option.ctrlOption"):
        code = (opt.get("value") or "").strip()
        label = opt.get_text(" ", strip=True)
        if code and code not in ("CH", "C0") and label:
            out[code] = label.title()
    return out


def _collect_space_marines(raw, debug=False):
    pre = _preamble(raw)
    chapters = _chapter_map(pre)
    # data-f CH bitmask decoder (built from ALL codes incl. C0, so the
    # alphabetical bit positions line up); see _chapter_bit_map.
    bitmap = _chapter_bit_map(_chapter_codes(pre))
    # base roster = 'No supplements' (C0); chapter extras = <code> - C0
    base_std, base_leg = [], []
    per_chapter = {c: {"std": [], "leg": []} for c in chapters}
    orphans = []
    for div in _datasheet_divs(raw):
        kind, chset = _classify(div, bitmap)
        parsed = parse_datasheet(div)
        if "C0" in chset:
            (base_leg if kind == "legend" else base_std).append(parsed)
        elif chset & set(chapters):
            for code in chset & set(chapters):
                bucket = per_chapter[code]
                bucket["leg" if kind == "legend" else "std"].append(parsed)
        else:
            # belongs to no roster file: never drop one silently
            orphans.append(parsed["name"])
    if orphans:
        print(f"  WARNING: {len(orphans)} Space Marines datasheet(s) match "
              f"no chapter and were skipped: {', '.join(orphans)}")
    if base_std:
        yield _SM_SLUG, ap40.faction_json(
            "Space Marines", base_std)
    if base_leg:
        yield f"{_SM_SLUG}_legends", ap40.faction_json(
            "Space Marines (Legends)", base_leg)
    for code, label in chapters.items():
        slug = f"{_SM_SLUG}_{label.lower().replace(' ', '_')}"
        if per_chapter[code]["std"]:
            yield slug, ap40.faction_json(
                label, per_chapter[code]["std"])
        if per_chapter[code]["leg"]:
            yield f"{slug}_legends", ap40.faction_json(
                f"{label} (Legends)",
                per_chapter[code]["leg"])


# The Wahapedia "factions" nav is rendered by JavaScript, so a plain HTML
# dump does not contain the faction list. This static list (11th ed. main
# factions, Wahapedia slugs) is used for the launch menu / "all"; live
# fetches simply skip a slug whose datasheets page 404s, so an out-of-date
# entry is harmless and the list is easy to edit.
KNOWN_FACTIONS = [
    ("adepta-sororitas", "Adepta Sororitas"),
    ("adeptus-custodes", "Adeptus Custodes"),
    ("adeptus-mechanicus", "Adeptus Mechanicus"),
    ("adeptus-titanicus", "Adeptus Titanicus"),
    ("astra-militarum", "Astra Militarum"),
    ("grey-knights", "Grey Knights"),
    ("imperial-agents", "Imperial Agents"),
    ("imperial-knights", "Imperial Knights"),
    ("space-marines", "Space Marines"),
    ("chaos-daemons", "Chaos Daemons"),
    ("chaos-knights", "Chaos Knights"),
    ("chaos-space-marines", "Chaos Space Marines"),
    ("death-guard", "Death Guard"),
    ("emperor-s-children", "Emperor's Children"),
    ("thousand-sons", "Thousand Sons"),
    ("world-eaters", "World Eaters"),
    ("aeldari", "Aeldari"),
    ("drukhari", "Drukhari"),
    ("genestealer-cults", "Genestealer Cults"),
    ("leagues-of-votann", "Leagues of Votann"),
    ("necrons", "Necrons"),
    ("orks", "Orks"),
    ("t-au-empire", "T'au Empire"),
    ("tyranids", "Tyranids"),
]


def list_factions(src=None):
    """[(slug, display_name)] for the launch menu. Static (see above)."""
    return list(KNOWN_FACTIONS)
