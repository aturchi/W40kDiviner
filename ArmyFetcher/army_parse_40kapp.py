"""Pure parsing + JSON-building logic for the 40k.app army scraper.

No network here: functions take already-linearised page text (the list of
stripped, non-empty lines produced by BeautifulSoup's get_text) and return
structured data / w40k-sim JSON units. This module is unit-tested offline
(see self_test) so the fragile network layer stays thin.

Design notes / assumptions about the rendered page (verified against real
T'au pages, may need small tweaks for other factions):
  * The page linearises into sections introduced by a title line:
    "Models", "Ranged weapons", "Melee weapons", "Keywords", "Costs",
    "Unit composition", "Led by", "Leads", "Core abilities",
    "Faction abilities", "Unit abilities", "Wargear options", "Wargear".
  * Stat rows are a flat run of cell values. A model row's name cell
    always carries a base size ("25mm", "28.5mm", "90 x 52mm"), so name
    lines are detected by an "mm" token.
  * A weapon row always ends with 6 stats [RNG, A, skill, S, AP, D]; the
    skill cell is the only one shaped like "\\d+" (e.g. "4+"), which we use
    as the anchor. Everything between two weapons is [name, keyword...].
"""
import re
import sys

FORMAT_TAG = "w40k-sim/6"

SECTION_TITLES = [
    "Models", "Ranged weapons", "Melee weapons", "Keywords", "Costs",
    "Unit composition", "Led by", "Leads", "Core abilities",
    "Faction abilities", "Unit abilities", "Wargear options", "Wargear",
    "Invulnerable save", "Damaged",
]

_SKILL_RE = re.compile(r"^(?:\d\+|N/?A)$")    # 4+  or  N/A (auto-hit)
# 40k.app now writes the skill of an auto-hitting weapon (Torrent) as a
# bare dash instead of 'N/A'. A dash is ALSO a legal AP value and shows up
# in stat lines, so it only anchors a weapon row when the row shape agrees:
# a range two cells before and an integer Strength right after.
_NO_SKILL_RE = re.compile(r"^[-\u2010-\u2014]$")
_RANGE_RE = re.compile(r'^(?:\d+"|Melee|N/?A)$', re.I)


def _is_skill_anchor(body, j) -> bool:
    """True when body[j] is the skill cell of a weapon row."""
    if _SKILL_RE.match(body[j]):
        return True
    return bool(_NO_SKILL_RE.match(body[j]) and j >= 2
                and _RANGE_RE.match(body[j - 2])
                and re.fullmatch(r"-?\d+", body[j + 1]))
_BASE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:x\s*\d+(?:\.\d+)?\s*)?mm", re.I)
_STAT_HDRS = {"M", "T", "SV", "W", "LD", "OC", "RNG", "A", "BS", "WS",
              "S", "AP", "D"}
_INT_RE = re.compile(r"-?\d+")


def _num(v):
    """'4+', '6\"', '7', '-' -> int; keep dice ('D6+1') and None."""
    if v is None:
        return None
    s = str(v).strip().replace('"', "").replace("+", "")
    if s in ("", "-", "N/A"):
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return v                                  # dice / free text (A, D)


# ---------------------------------------------------------------- sections
def section_bounds(lines):
    """Map each present section title to (start, end) line indices, where
    lines[start:end] is that section's body (title excluded). A title that
    repeats (e.g. an <h3>Models</h3> heading plus a <th>Models</th> table
    header) is collapsed to its first occurrence, so the body is not cut
    to zero length between the two."""
    hits = [(i, ln) for i, ln in enumerate(lines) if ln in SECTION_TITLES]
    seen, uniq = set(), []
    for i, title in hits:
        if title not in seen:
            seen.add(title)
            uniq.append((i, title))
    bounds = {}
    for k, (i, title) in enumerate(uniq):
        end = uniq[k + 1][0] if k + 1 < len(uniq) else len(lines)
        bounds[title] = (i + 1, end)
    return bounds


def _body(lines, bounds, title):
    """The lines belonging to section 'title', using the (start, end) span
    from 'bounds'; empty list when the section is absent."""
    if title not in bounds:
        return []
    a, b = bounds[title]
    return lines[a:b]


# ---------------------------------------------------------------- models
def _is_stat(s):
    """A single stat cell: '-', a number (optional decimal), with an
    optional trailing '+' (skill/save '2+', or aircraft Move '20+') and an
    optional inch mark ('6"', '20+"')."""
    return bool(re.fullmatch(r'-|\d+(?:\.\d+)?\+?"?', s))


def _is_invuln(s):
    """True if 's' is an invulnerable-save line (e.g. '4+ INVULNERABLE SAVE')."""
    return s.lower().startswith("invulnerable save")


def _is_fnp(s):
    """True if 's' is a Feel No Pain line (e.g. 'FEEL NO PAIN 5+')."""
    return s.lower().startswith("feel no pain")


# A base-size cell on its own line: "25mm", "28.5mm", "90 x 52mm".
_BASE_LINE_RE = re.compile(
    r"^\d+(?:\.\d+)?(?:\s*[x\u00d7]\s*\d+(?:\.\d+)?)?\s*mm$", re.I)


def _is_base(s):
    """True if 's' is a base-size line (e.g. '40mm'), not a characteristic."""
    return bool(_BASE_LINE_RE.match(s))


_MODEL_HDR_SKIP = _STAT_HDRS | {"Models", "Profiles", "Profile", "Unit"}


def parse_models(body):
    """Body of the Models section -> [{name, M,T,Sv,W,LD,OC, invuln}].

    Real pages put the base size / descriptor on its own line(s) after the
    model name ('25mm', 'Large Flying Base', 'Unique', 'X / Y: 60mm'), and
    an invuln as 'Invulnerable save:' + value on separate lines. So we
    anchor on the fixed 6-cell stat run (M,T,SV,W,LD,OC) at the end of each
    row: everything before it is [name, base descriptors] (name = first
    line); an 'Invulnerable save:' pair is pulled out as the invuln."""
    i = 0
    while i < len(body) and body[i] in _MODEL_HDR_SKIP:
        i += 1
    rows, meta, invuln, fnp, n = [], [], None, None, len(body)
    while i < n:
        ln = body[i]
        if _is_invuln(ln) or _is_fnp(ln):
            tgt = "invuln" if _is_invuln(ln) else "fnp"
            m = re.search(r"(\d)\+", ln)
            if m:
                val, adv = int(m.group(1)), 1
            elif i + 1 < n and re.search(r"(\d)\+", body[i + 1]):
                val, adv = int(re.search(r"(\d)\+", body[i + 1]).group(1)), 2
            else:
                val, adv = None, 1
            if tgt == "invuln":
                invuln = val
            else:
                fnp = val
            i += adv
            continue
        if _is_stat(ln):                       # start of the 6-stat run
            stats = []
            while i < n and len(stats) < 6 and _is_stat(body[i]):
                stats.append(body[i])
                i += 1
            name = _BASE_RE.sub("", meta[0]).strip() if meta else "?"
            stats = (stats + [None] * 6)[:6]
            M_, T_, Sv, W_, LD, OC = stats
            rows.append({"name": name, "M": _num(M_), "T": _num(T_),
                         "Sv": _num(Sv), "W": _num(W_), "LD": _num(LD),
                         "OC": _num(OC), "invuln": _num(invuln),
                         "fnp": _num(fnp)})
            meta, invuln, fnp = [], None, None
        else:                                   # name / base-descriptor line
            meta.append(ln)
            i += 1
    return rows


# ---------------------------------------------------------------- weapons
WARNINGS = []


def warn(message):
    """Print a parser warning on stdout, next to the driver's own progress
    lines, and keep it in WARNINGS so the driver can summarise at the end
    of a long run. Both parsers recognise a row by its SHAPE and skip
    whatever they do not understand; skipping silently is how a site change
    once removed every Torrent weapon without a single error, so anything
    dropped that looked like real data is reported here."""
    WARNINGS.append(message)
    print(f"    WARNING: {message}")


# a lone stat cell as it appears in the linearised text: a range ('12"'),
# an integer ('4', '-1'), a dice value ('D6', '2D6+3') or a bare dash
_STAT_CELL_RE = re.compile(r'^(?:\d+"|-?\d+|\d*D\d+(?:[+-]\d+)?'
                           r'|[-\u2010-\u2014])$', re.I)


def _stat_like(lines):
    """The lines that look like weapon stat cells - used to spot a weapon
    row the anchor did not recognise (its cells end up either as leftover
    tail or swallowed into the next weapon's name/keyword head)."""
    return [ln for ln in lines if _STAT_CELL_RE.match(ln)]


def parse_weapons(body, melee, where=""):
    """Body of a weapons section -> [{name, keywords, RNG,A,skill,S,AP,D}].
    Anchored on the skill cell ('\\d+'). melee decides WS vs BS.
    'where' names the unit for warnings about rows that were not
    recognised (see warn)."""
    # drop leading column headers
    i = 0
    while i < len(body) and body[i] in _STAT_HDRS:
        i += 1
    body = body[i:]
    # A skill cell is '\d+', 'N/A' or a dash (see _is_skill_anchor). But
    # 'N/A' also occurs as the RNG of some missiles, so only accept an
    # anchor whose AP slot (2 cells later) is a signed integer or '-'
    # (AP 0) - the real skill position has AP there, whereas an
    # N/A-as-RNG would have the BS ('2+') two cells on.
    anchors = [j for j, ln in enumerate(body)
               if j + 3 < len(body) and _is_skill_anchor(body, j)
               and re.fullmatch(r"-|-?\d+", body[j + 2])]
    weapons, prev_end, suspect = [], 0, []
    for j in anchors:
        if j - 2 < prev_end:                  # malformed, skip
            continue
        rng, a = body[j - 2], body[j - 1]
        s, ap, d = (body[j + 1], body[j + 2], body[j + 3])
        head = [h for h in body[prev_end:j - 2]
                if any(ch.isalnum() for ch in h)]   # drop '\u27a4' markers
        # stat cells inside the head mean the PREVIOUS row was not
        # recognised and its cells were swallowed by this one
        suspect += _stat_like(head)
        name = head[0] if head else "Weapon"
        keywords = [h for h in head[1:] if h]
        weapons.append({
            "name": name, "keywords": keywords,
            "type": "Melee" if melee else "Ranged",
            "RNG": None if melee else _num(rng), "A": a,
            "skill": _num(body[j]), "S": _num(s), "AP": _num(ap), "D": d,
        })
        prev_end = j + 4
    suspect += _stat_like(body[prev_end:])    # ... or left as a tail
    # a dropped weapon row leaves its range and numbers behind; a lone dash
    # (an empty stat cell elsewhere in the section) is not evidence
    solid = [c for c in suspect if not _NO_SKILL_RE.match(c)]
    kind = "melee" if melee else "ranged"
    if len(solid) >= 2:
        warn(f"{where or 'unit'}: {len(suspect)} unrecognised {kind} weapon "
             f"cell(s) dropped ({', '.join(suspect[:8])}) - a weapon row "
             f"was probably not parsed")
    elif body and not weapons:
        warn(f"{where or 'unit'}: the {kind} weapons section has "
             f"{len(body)} line(s) but no weapon row was recognised")
    return weapons


# ---------------------------------------------------------------- lists
def parse_simple_list(body):
    """Keyword / core / faction lists: one entry per line."""
    return [ln for ln in body if ln and ln not in SECTION_TITLES]


def parse_costs(body):
    """Costs -> [(models:int, points:int)] pairs. Matches each 'N model(s)'
    line with the first integer on the following line(s), so per-unit size
    tiers are captured while wargear/quantity surcharges ('+10 pts 3rd+ in
    your army', 'Missile pod +5 pts') are ignored."""
    pairs = []
    for i, ln in enumerate(body):
        m = re.fullmatch(r"(\d+)\s+models?", ln.strip())
        if not m:
            continue
        for j in range(i + 1, min(i + 3, len(body))):
            pm = re.search(r"\d+", body[j])
            if pm:
                pairs.append((int(m.group(1)), int(pm.group())))
                break
    return pairs


def _clean(text):
    """Collapse whitespace and strip a linearised text fragment."""
    text = re.sub(r"\s+([,.;:])", r"\1", text)     # drop space before punct
    return re.sub(r"\s{2,}", " ", text).strip()


def _is_ability_name(ln):
    """An ability name is a short, Title-cased line that is NOT an
    all-caps keyword fragment (e.g. 'VESPID STINGWINGS') and does not end
    like a sentence clause."""
    return (0 < len(ln.split()) <= 6
            and ln[:1].isupper()
            and not ln.isupper()
            and not ln.endswith((".", ",", ":", ";")))


def parse_unit_abilities(body):
    """Split the Unit abilities block into [(name, description)].

    Robust to inline ALL-CAPS keyword references (which the page renders
    on their own lines): a new ability only begins when the previous
    description has ended a sentence AND the next line looks like an
    ability name. This fixes descriptions being split at keywords such as
    'VESPID STINGWINGS' or 'FORTIFICATION'.
    """
    out, i, n = [], 0, len(body)
    while i < n and not _is_ability_name(body[i]):
        i += 1
    while i < n:
        name = body[i]
        i += 1
        desc = []
        while i < n:
            ln = body[i]
            prev_ended = desc and desc[-1].rstrip().endswith((".", "!"))
            if prev_ended and _is_ability_name(ln):
                break
            desc.append(ln)
            i += 1
        if not name.lower().startswith("designer"):   # skip designer notes
            out.append((name, _clean(" ".join(desc))))
    return out


# A Damaged-bracket line: 'DAMAGED: N-M WOUNDS REMAINING' or, on some pages,
# the same without the colon ('Damaged 1-10 Wounds Remaining'). It is the
# unit-level 'damageable' flag, not an ability.
_DAMAGED_RE = re.compile(r"^\s*DAMAGED\b.*\bWOUNDS?\s+REMAINING", re.I)


def _extract_damaged(ua_body):
    """(damageable, damaged_text, cleaned_body): if a DAMAGED bracket line
    is present, drop it and its following effect line(s) (up to the next
    ability-name line) from the Unit abilities body, report
    damageable=True, and return the bracket text (header + effect, newline
    joined) so the caller can keep it in notes. When absent: (False, "",
    ua_body)."""
    for i, ln in enumerate(ua_body):
        if _DAMAGED_RE.match(ln):
            j = i + 1
            # consume the bracket's effect text until the next ability name
            while j < len(ua_body) and not _is_ability_name(ua_body[j]):
                j += 1
            damaged_text = "\n".join(ua_body[i:j]).strip()
            return True, damaged_text, ua_body[:i] + ua_body[j:]
    return False, "", ua_body


# ---------------------------------------------------------------- assemble
def _extract_supports(comp_body, core_ab):
    """(support_list, cleaned_core): on 40k.app a support unit lists the
    units it can support as the lines after a 'Supports' marker inside the
    Unit composition body, e.g. [..., 'Supports', 'Crusader Squad', 'Sword
    Brethren Squad']. The 'Support' keyword also appears in Core abilities;
    it is dropped (the non-empty support list represents it, as leadership
    does for leaders). Prose fragments such as 'Any unit with ...' (a
    keyword clause linearised without its tail) are not datasheet names and
    are skipped."""
    support = []
    for i, ln in enumerate(comp_body):
        if ln.strip().lower() == "supports":
            for s in comp_body[i + 1:]:
                s = s.strip()
                if s and not s.lower().startswith("any unit"):
                    support.append(s)
            break
    cleaned = [c for c in core_ab if c.strip().lower() != "support"]
    return support, cleaned


def parse_unit(lines):
    """Linearised unit-page lines -> structured dict."""
    b = section_bounds(lines)
    name = lines[0] if lines else "Unknown"
    ua_body = _body(lines, b, "Unit abilities")
    damageable, damaged_text, ua_body = _extract_damaged(ua_body)
    core_ab = parse_simple_list(_body(lines, b, "Core abilities"))
    # 'Feel No Pain N+' is already parsed into model.fnp from the stat block;
    # drop it from the core ability list so the characteristic is not also
    # duplicated as an ability string (matches the wahapedia treatment).
    core_ab = [c for c in core_ab if not c.lower().startswith("feel no pain")]
    comp_body = _body(lines, b, "Unit composition")
    support, core_ab = _extract_supports(comp_body, core_ab)
    # Drop the 'Supports' marker and the supported-unit lines from the
    # composition body: they are captured in 'support', and must not appear
    # in the display text or be mistaken for models.
    if support:
        cut = next((i for i, ln in enumerate(comp_body)
                    if ln.strip().lower() == "supports"), len(comp_body))
        comp_body = comp_body[:cut]
    return {
        "name": name,
        "models": parse_models(_body(lines, b, "Models")),
        "ranged": parse_weapons(_body(lines, b, "Ranged weapons"), False,
                                name),
        "melee": parse_weapons(_body(lines, b, "Melee weapons"), True,
                               name),
        "keywords": parse_simple_list(_body(lines, b, "Keywords")),
        "core_abilities": core_ab,
        "faction_abilities": parse_simple_list(
            _body(lines, b, "Faction abilities")),
        "unit_abilities": parse_unit_abilities(ua_body),
        "leads": parse_simple_list(_body(lines, b, "Leads")),
        "support": support,
        "costs": parse_costs(_body(lines, b, "Costs")),
        "composition": comp_body,
        # Display-only text: keep source line breaks (one source line per
        # output line) so bullet lists stay readable in the editor.
        "unit_composition": "\n".join(comp_body),
        "wargear_options": "\n".join(_body(lines, b, "Wargear options")),
        "damageable": damageable,
        "notes": (f"[DAMAGED]\n{damaged_text}" if damaged_text else ""),
    }


# ==================================================================== build
def _weapon_json(w, count):
    """Build the native weapon dict from a parsed weapon 'w' and its count."""
    # AP is always applicable ('-' means 0). Unlike BS/WS 'N/A' (auto-hit,
    # correctly None), AP must be a real 0 so AP modifiers (e.g. Hazardous
    # -1) apply instead of being lost on a not-applicable characteristic.
    ap = w["AP"] if w["AP"] is not None else 0
    j = {"name": w["name"], "type": w["type"], "RNG": w["RNG"],
         "A": w["A"], "S": w["S"], "AP": ap, "D": w["D"],
         "count": count, "keywords": w["keywords"], "abilities": []}
    j["WS" if w["type"] == "Melee" else "BS"] = w["skill"]
    return j


def _ability_json(name, text):
    """Build the native ability dict from an ability name and its body text."""
    return {"name": name, "description": text,
            "enabled": False, "share_with_unit": False,
            "conditions": [], "effect": {"type": "special", "data": {}}}


_COMP_RE = re.compile(r"(\d+)(?:\s*[-\u2013]\s*(\d+))?\s+([A-Za-z].*)")


def _norm(s):
    """Normalise a model/composition name for matching: letters only, and
    each word singularised so plurals match their profile. Handles the
    regular '-s' plural ('Veterans' -> 'Veteran', 'Marines' -> 'Marine')
    and the '-ves' -> '-f' plural ('Wolves' -> 'Wolf', 'Knives' -> 'Knife')
    so 'Hunting Wolf' matches the profile 'Hunting Wolves'."""
    def singular(w):
        """Best-effort English singular of one lowercased word, for keyword/name matching between composition and profiles."""
        if w.endswith("ves"):
            return w[:-3] + "f"
        return re.sub(r"s$", "", w)
    return "".join(singular(w) for w in re.findall(r"[a-z]+", s.lower()))


_RANGE_DASH_RE = re.compile(r"(?<=\d)[\u2010-\u2014](?=\d)")


def normalise_dashes(text) -> str:
    """Unicode hyphens/dashes BETWEEN DIGITS -> plain '-'. Wahapedia writes
    size ranges with a non-breaking hyphen on some datasheets ('3\u201110 Kill
    Team Infiltrators'), which otherwise fails the '<min>-<max> <name>'
    match and silently drops the whole composition entry. Only digit-digit
    dashes are touched, so model names keep their original punctuation."""
    return _RANGE_DASH_RE.sub("-", str(text or ""))


_SIZE_CAP_RE = re.compile(r"^\s*\d+\s+MODELS?\s+MAXIMUM\b", re.I)


def is_size_cap_line(line) -> bool:
    """True for a composition bullet that states the TOTAL size cap
    ('10 MODELS MAXIMUM') instead of naming a model group. It looks exactly
    like a real entry ('<N> <name>'), so without this it becomes a phantom
    model profile of 10 models (seen on the Deathwatch Kill Teams)."""
    return bool(_SIZE_CAP_RE.match(str(line or "")))


def _parse_composition(lines):
    """Composition bullets -> [(min, max, name)]. '1 Long-quill' and
    '9-19 Kroot Carnivores' both parse; a size-cap bullet is skipped."""
    out = []
    for ln in lines:
        ln = normalise_dashes(ln)
        if is_size_cap_line(ln):
            continue
        m = _COMP_RE.search(ln.lstrip("-\u2022\u25e6* "))
        if m:
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else lo
            out.append((lo, hi, m.group(3).strip()))
    return out


def _compose_counts(model_profiles, comp, use_max):
    """Per-profile model_count from composition. Each composition entry is
    assigned to at most ONE profile: exact normalised matches are made
    first (and consumed), then the leftover profiles take a remaining entry
    by substring. This stops a short profile name ('Devastator') from
    grabbing a longer entry it is a substring of ('Devastator Sergeant')
    and leaving the real entry ('Devastator Marines') unmatched. Profiles
    with no entry (optional wargear profiles) get 0. Returns None only when
    there is no composition to work from."""
    if not comp:
        return None
    remaining = list(comp)
    counts = [None] * len(model_profiles)
    for i, mp in enumerate(model_profiles):                 # pass 1: exact
        pn = _norm(mp["name"])
        for c in remaining:
            if _norm(c[2]) == pn:
                counts[i] = c[1] if use_max else c[0]
                remaining.remove(c)
                break
    for i, mp in enumerate(model_profiles):                 # pass 2: substring
        if counts[i] is not None:
            continue
        pn = _norm(mp["name"])
        for c in remaining:
            cn = _norm(c[2])
            if pn and (pn in cn or cn in pn):
                counts[i] = c[1] if use_max else c[0]
                remaining.remove(c)
                break
    return [c if c is not None else 0 for c in counts]


def _dropped_note(profiles):
    """Note text for model profiles the datasheet offers but that resolve
    to 0 models at minimum unit size ('0-6 Hunting Wolves'). model_count
    must be a positive integer, so such a profile cannot be emitted; keep
    its stat line here instead of losing it, so it can be re-created by
    hand in the profile editor when the group is actually fielded."""
    out = ["Optional model profiles not fielded at minimum unit size "
           "(add by hand if you field them):"]
    for mp in profiles:
        stats = ", ".join(f"{k} {mp.get(k)}" for k in
                          ("M", "T", "Sv", "W", "LD", "OC"))
        for k in ("invuln", "fnp"):
            if mp.get(k):
                stats += f", {k} {mp[k]}+"
        out.append(f"  {mp.get('name') or '?'}: {stats}")
    return "\n".join(out)


def _top_up(counts, maxima, min_size):
    """A unit must field at least as many models as the price row it is
    given. A few datasheets state per-group minimums that add up to less
    than that (Deathwatch Kill Teams: '3-10 Kill Team Intercessors' with a
    single '10 models' price), so spread the shortfall over the groups that
    still have headroom, largest headroom first - i.e. onto the bulk group
    rather than onto the optional ones."""
    short = min_size - sum(counts)
    if short <= 0 or not maxima:
        return counts
    out = list(counts)
    room = {i: max(0, (maxima[i] or 0) - out[i]) for i in range(len(out))}
    for i in sorted(room, key=lambda j: (-room[j], j)):
        if short <= 0:
            break
        take = min(room[i], short)
        out[i] += take
        short -= take
    return out


def _split_models(model_profiles, total):
    """Fallback split when composition can't be matched: 1 per champion
    profile, remainder on the last. Total is preserved."""
    k = len(model_profiles)
    if k <= 1:
        return [total]
    counts = [1] * (k - 1) + [total - (k - 1)]
    if counts[-1] < 1:
        counts = [total // k] * k
        counts[-1] += total - sum(counts)
    return counts


def build_units(parsed):
    """Structured unit -> a SINGLE w40k-sim unit dict.

    Per the roster convention: the unit is modelled at its MINIMUM size
    (fewest models, lowest points), but every weapon's count is the
    MAXIMUM the datasheet allows (== the maximum unit size). Per-profile
    model_count comes from Unit composition when parseable.
    """
    costs = parsed["costs"] or [(1, 0)]
    sizes = sorted({m for m, _ in costs})
    pts = dict(costs)
    min_size, max_size = sizes[0], sizes[-1]
    comp = _parse_composition(parsed["composition"])
    counts = _compose_counts(parsed["models"], comp, use_max=False)
    if not counts or sum(counts) == 0:
        counts = _split_models(parsed["models"], min_size)
    else:
        counts = _top_up(counts, _compose_counts(parsed["models"], comp,
                                                 use_max=True), min_size)
    weapon_count = max_size                       # weapons: always maximum
    weapons = ([_weapon_json(w, weapon_count) for w in parsed["ranged"]]
               + [_weapon_json(w, weapon_count) for w in parsed["melee"]])
    # keep only profiles actually fielded at min size (drop optional
    # wargear profiles that resolve to 0 models, e.g. an unequipped hull);
    # their stat line survives in the notes (see _dropped_note)
    present = [(mp, c) for mp, c in zip(parsed["models"], counts) if c > 0]
    dropped = [mp for mp, c in zip(parsed["models"], counts) if c <= 0]
    if not present:
        present = [(parsed["models"][0], min_size)] if parsed["models"] \
            else []
    models = []
    for i, (mp, c) in enumerate(present):
        models.append({
            "name": mp["name"], "model_count": c,
            "M": mp["M"], "T": mp["T"], "Sv": mp["Sv"], "W": mp["W"],
            "LD": mp["LD"], "OC": mp["OC"],
            "invuln": mp.get("invuln"), "fnp": mp.get("fnp"),
            "keywords": [], "abilities": [],
            "weapons": weapons if i == 0 else [],
        })
    return [{
        "name": parsed["name"], "profile_name": parsed["name"],
        "points": pts.get(min_size, 0),
        "keywords": list(parsed["keywords"]),
        # core/faction abilities carry only a name on the datasheet (their
        # rules live in the core/faction rules), so emit them as name-only
        # ability dicts - same shape as unit abilities, editable/enable-able
        # in the profile editor and applied by the engine once structured.
        "core_abilities": [_ability_json(n, "")
                           for n in parsed["core_abilities"]],
        "faction_abilities": [_ability_json(n, "")
                              for n in parsed["faction_abilities"]],
        "abilities": [_ability_json(n, t)
                      for n, t in parsed["unit_abilities"]],
        "leadership": list(parsed["leads"]),
        "support": list(parsed.get("support", [])),
        "leader_effects": [], "apply_leader_effects_to_self": False,
        "damageable": bool(parsed.get("damageable", False)),
        "unit_composition": parsed.get("unit_composition", ""),
        "wargear_options": parsed.get("wargear_options", ""),
        "notes": "\n\n".join(x for x in (parsed.get("notes", ""),
                                         _dropped_note(dropped) if dropped
                                         else "") if x),
        "models": models,
    }]


def faction_json(faction_name, parsed_units, faction_keyword=None):
    """Assemble the army JSON. faction_keyword, when given, is appended to
    every unit's keyword list (case-insensitively deduped) - 40k.app does
    not render the FACTION KEYWORD in the datasheet body, only the unit
    keywords, so the caller supplies the faction name to fold in. Wahapedia
    already carries FACTION KEYWORDS, so it does not pass this."""
    units = []
    for pu in parsed_units:
        for u in build_units(pu):
            if faction_keyword:
                have = {k.lower() for k in u["keywords"]}
                if faction_keyword.lower() not in have:
                    u["keywords"].append(faction_keyword)
            units.append(u)
    return {"format": FORMAT_TAG,
            "armies": [{"name": faction_name, "units": units}]}


# ====================================================================
# DISCOVERY + collect() -- the 40k.app HTTP-crawl layer, moved here from
# fetch_armies.py so this library exposes the same interface as
# army_parse_wahapedia (BASE, DEFAULT_OUT, collect(src, faction)). 'src'
# is a page source with a .get(url)->BeautifulSoup method (fetch_armies.
# PageSource); this module never touches the network itself.
# ====================================================================
BASE = "https://www.40k.app"
DEFAULT_OUT = "fetched_armies_40kapp"
FACTIONS_URL = BASE + "/factions"

_FACTION_HREF = re.compile(r"^/factions/([a-z0-9-]+)/?$")
_UNIT_HREF = re.compile(r"^/factions/[^/]+/units/([a-z0-9-]+)/?$")
_FOOTER = ("Become a supporter", "GW, Games Workshop")


def linearise(soup):
    """All visible text as stripped, non-empty lines in document order -
    the shape parse_unit expects (inline elements land on their own lines,
    which is what lets weapon keyword cells and section bodies be parsed)."""
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines()]
    return [ln for ln in lines if ln]


def unit_content(soup):
    """(unit_name, content_lines) trimmed to the datasheet body: from the
    'Models' section down to the page footer, with the H1 name prepended."""
    h1 = soup.find("h1")
    name = h1.get_text(strip=True) if h1 else "Unknown"
    lines = linearise(soup)
    try:
        start = lines.index("Models")
    except ValueError:
        start = 0
    end = len(lines)
    for i, ln in enumerate(lines[start:], start):
        if any(ln.startswith(f) for f in _FOOTER):
            end = i
            break
    return name, [name] + lines[start:end]


def _hrefs(soup, pattern):
    """All hrefs in 'soup' whose URL matches 'pattern' (deduped, in order)."""
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0]
        if pattern.match(href) and href not in seen:
            seen.add(href)
            out.append(href)
    return out


def _faction_sublinks(soup, self_slug):
    """Child-faction slugs linked from a faction page (excluding itself)."""
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = _FACTION_HREF.match(a["href"].split("?")[0])
        if m and m.group(1) != self_slug and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


def _unit_slug_hrefs(soup):
    """[(unit_slug, href)] for the datasheet links on a faction page."""
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0]
        m = _UNIT_HREF.match(href)
        if m and href not in seen:
            seen.add(href)
            out.append((m.group(1), href))
    return out


def _faction_name(soup):
    """The faction display name read from the faction page header."""
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else "Unknown faction"


def discover(src, seeds):
    """Pass 1 (quick): fetch every faction page reachable from 'seeds',
    following in-page sub-faction links. Only faction pages are fetched
    here (not unit pages). Faction pages missing from a dump are skipped."""
    order, name, children, units = [], {}, {}, {}
    queue, seen = list(dict.fromkeys(seeds)), set()
    while queue:
        slug = queue.pop(0)
        if slug in seen:
            continue
        seen.add(slug)
        try:
            soup = src.get(BASE + f"/factions/{slug}")
        except FileNotFoundError:
            print(f"  (faction page '{slug}' not in dump - skipped)",
                  file=sys.stderr)
            continue
        order.append(slug)
        name[slug] = _faction_name(soup)
        kids = _faction_sublinks(soup, slug)
        children[slug] = kids
        units[slug] = _unit_slug_hrefs(soup)
        for c in kids:
            if c not in seen:
                queue.append(c)
    return order, name, children, units


def classify(order, children, index_set):
    """Split discovered factions into main vs sub. A faction C is a SUB of
    P when P links to C and either C is NOT in the main index (Aeldari->
    Harlequins/Ynnari, Chaos->Plague Legions) or P has strictly more
    outgoing faction-links than C (Space Marines -> its 11 chapters, which
    ARE in the index). Order-independent, survives mutual links."""
    link_count = {s: len(children.get(s, [])) for s in order}
    parent = {}
    for p in order:
        for c in children.get(p, []):
            if c == p:
                continue
            is_sub = (c not in index_set
                      or link_count[p] > link_count.get(c, 0))
            if is_sub:
                cur = parent.get(c)
                if cur is None or link_count[p] > link_count[cur]:
                    parent[c] = p
    mains = [s for s in order if s not in parent]
    return mains, parent


def parse_units(unit_hrefs, src, debug=False, fetched=None):
    """Fetch+parse each (slug, href). 'fetched', when given, is a run-wide
    set of already-processed hrefs: a unit page is fetched at most once per
    collect() run even if several faction pages link to it (the 'all' path
    passes one shared set to avoid re-downloading the same unit)."""
    parsed = []
    for _uslug, href in unit_hrefs:
        if fetched is not None:
            if href in fetched:
                continue
            fetched.add(href)
        try:
            soup = src.get(BASE + href)
            nm, lines = unit_content(soup)
            if debug:
                print(f"---- {nm} ----\n" + "\n".join(lines), file=sys.stderr)
            parsed.append(parse_unit(lines))
            print(f"    ok  {nm}", file=sys.stderr)
        except FileNotFoundError:
            print(f"    skip {href}: not in dump", file=sys.stderr)
        except Exception as exc:                             # noqa: BLE001
            print(f"    FAIL {href}: {exc}", file=sys.stderr)
    return parsed


def _slug(href):
    """The trailing slug of a datasheet href (the unit id), lowercased."""
    m = _FACTION_HREF.match(href)
    return m.group(1) if m else href.strip("/").replace("/", "_")


def collect(src, faction=None, debug=False):
    """Yield (filename_stem, data_dict) for 40k.app. Handles the two-pass
    discovery + main/sub classification + per-sub dedup. Main factions are
    parsed fully; each sub-faction yields only the units whose slug is not
    already in its parent."""
    if faction:
        seeds = [faction]
    else:
        seeds = [_slug(h) for h in _hrefs(src.get(FACTIONS_URL), _FACTION_HREF)]
    index_set = set(seeds)
    order, name, children, units = discover(src, seeds)
    mains, parent = classify(order, children, index_set)
    subs = [s for s in order if s in parent]
    print(f"discovered {len(order)} faction page(s): {len(mains)} main, "
          f"{len(subs)} sub", file=sys.stderr)
    # Run-wide dedup of unit fetches. Mains are parsed first; a sub's units
    # already present in its parent are skipped both by the 'extra' slug
    # filter and by this href set. A unit is emitted in exactly one file:
    # its main, or the first sub that adds it as an extra.
    fetched = set()
    for slug in mains:
        print(f"=== {slug} (main, {len(units[slug])} units) ===",
              file=sys.stderr)
        parsed = parse_units(units[slug], src, debug, fetched)
        if parsed:
            yield slug, faction_json(name[slug], parsed, faction_keyword=name[slug])
    for slug in subs:
        p = parent[slug]
        parent_slugs = {u for u, _ in units.get(p, [])}
        extra = [(u, h) for u, h in units[slug] if u not in parent_slugs]
        print(f"=== {slug} (sub of {p}): {len(extra)} new / "
              f"{len(units[slug])} units ===", file=sys.stderr)
        parsed = parse_units(extra, src, debug, fetched)
        if parsed:
            yield slug, faction_json(name[slug], parsed, faction_keyword=name[slug])


def list_factions(src):
    """[(slug, display_name)] of the main factions, from the /factions
    index page. Sub-factions are discovered later, per faction."""
    out = []
    soup = src.get(FACTIONS_URL)
    for a in soup.find_all("a", href=True):
        m = _FACTION_HREF.match(a["href"].split("?")[0])
        if m:
            out.append((m.group(1), a.get_text(strip=True) or m.group(1)))
    seen, uniq = set(), []
    for slug, nm in out:
        if slug not in seen:
            seen.add(slug)
            uniq.append((slug, nm))
    return uniq
