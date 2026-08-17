"""Offline self-test: run the pure parser/builder against linearised
line fixtures derived from real 40k.app pages (markdown markers stripped,
links reduced to their text - i.e. what soup.get_text() yields)."""
import os
import sys

import army_parse_40kapp as ap

# ---- Strike Team (fixture) ----
STRIKE = """Strike Team
Models
M
T
SV
W
LD
OC
Fire Warrior 25mm
6"
3
4+
1
7+
2
Fire Warrior Shas'ui 25mm
6"
3
4+
1
7+
2
Ranged weapons
RNG
A
BS
S
AP
D
Pulse carbine
20"
2
4+
5
0
1
Pulse pistol
Pistol
12"
1
4+
5
0
1
Pulse rifle
Rapid Fire 1
30"
1
4+
5
0
1
Support turret
Indirect Fire
Twin-linked
30"
2
5+
5
0
1
Melee weapons
RNG
A
WS
S
AP
D
Close combat weapon
Melee
1
5+
3
0
1
Keywords
Battleline
Fire Warrior
Grenades
Infantry
Markerlight
Strike Team
Costs
10 models
70 pts
Unit composition
1 Fire Warrior Shas'ui
9 Fire Warriors
Led by
Cadre Fireblade
Ethereal
Faction abilities
For the Greater Good
Unit abilities
Suppression Volley
In your Shooting phase, after this unit has shot, select one enemy INFANTRY unit hit by one or more of those attacks.
DS8 Support Turret
In your Movement phase, if this unit Remains Stationary, until the start of your next turn, its Shas'ui model is equipped with the support turret weapon.
""".strip().splitlines()

# ---- Kroot Carnivores (variable size 10/20) ----
KROOT = """Kroot Carnivores
Models
M
T
SV
W
LD
OC
Kroot Carnivore 28.5mm
7"
3
6+
1
7+
2
Long-quill 28.5mm
7"
3
6+
1
7+
2
Ranged weapons
RNG
A
BS
S
AP
D
Kroot rifle
Rapid Fire 1
24"
1
4+
4
0
1
Tanglebomb launcher
Blast
24"
D3
4+
5
0
1
Melee weapons
RNG
A
WS
S
AP
D
Close combat weapon
Melee
2
3+
4
0
1
Keywords
Carnivores
Grenades
Infantry
Kroot
Costs
10 models
65 pts
20 models
130 pts
Unit composition
1 Long-quill
9-19 Kroot Carnivores
Core abilities
Scouts 7"
Stealth
Unit abilities
Fieldcraft
At the end of your Command phase, if this unit is within range of an objective marker you control, that objective marker remains under your control.
""".strip().splitlines()


def show(tag, p):
    print(f"=== {tag} ===")
    print(" name      :", p["name"])
    print(" models    :", [(m["name"], m["T"], m["Sv"], m["W"]) for m in p["models"]])
    print(" ranged    :", [(w["name"], w["skill"], w["S"], w["AP"], w["D"], w["keywords"]) for w in p["ranged"]])
    print(" melee     :", [(w["name"], w["skill"], w["S"]) for w in p["melee"]])
    print(" keywords  :", p["keywords"])
    print(" core      :", p["core_abilities"])
    print(" faction   :", p["faction_abilities"])
    print(" leads     :", p["leads"])
    print(" costs     :", p["costs"])
    print(" abilities :", [(n, d[:35]) for n, d in p["unit_abilities"]])


ps = ap.parse_unit(STRIKE)
show("Strike Team", ps)
assert ps["models"][0]["name"] == "Fire Warrior"
assert ps["models"][0]["T"] == 3 and ps["models"][0]["Sv"] == 4
r = {w["name"]: w for w in ps["ranged"]}
assert r["Pulse pistol"]["keywords"] == ["Pistol"] and r["Pulse pistol"]["skill"] == 4
assert r["Pulse rifle"]["keywords"] == ["Rapid Fire 1"]
assert r["Support turret"]["keywords"] == ["Indirect Fire", "Twin-linked"]
assert ps["melee"][0]["name"] == "Close combat weapon" and ps["melee"][0]["skill"] == 5
assert "Markerlight" in ps["keywords"]
assert ps["faction_abilities"] == ["For the Greater Good"]
assert ps["leads"] == []      # Strike Team has "Led by", not "Leads"
assert ps["costs"] == [(10, 70)]
assert [n for n, _ in ps["unit_abilities"]] == ["Suppression Volley", "DS8 Support Turret"]

pk = ap.parse_unit(KROOT)
show("Kroot Carnivores", pk)
assert pk["costs"] == [(10, 65), (20, 130)]
assert pk["core_abilities"] == ['Scouts 7"', "Stealth"]

# ---- build: single unit, MIN models/points, MAX weapon count ----
kunits = ap.build_units(pk)
print("\n=== build Kroot (single unit) ===")
u = kunits[0]
print(" ", u["name"], "| pts", u["points"],
      "| models", [(m["name"], m["model_count"]) for m in u["models"]],
      "| rifle count", next(w["count"] for m in u["models"] for w in m["weapons"] if w["name"] == "Kroot rifle"))
assert len(kunits) == 1 and u["name"] == "Kroot Carnivores"
assert u["points"] == 65                                   # min size points
assert sum(m["model_count"] for m in u["models"]) == 10    # min models
assert sorted((m["name"], m["model_count"]) for m in u["models"]) == \
    [("Kroot Carnivore", 9), ("Long-quill", 1)]
rc = next(w["count"] for m in u["models"] for w in m["weapons"] if w["name"] == "Kroot rifle")
assert rc == 20                                            # weapons: maximum
# build_units wraps core/faction ability NAMES into structured ability
# dicts (see _ability_json); the intermediate parse_datasheet keeps them
# as plain strings (asserted on 'pk' above, line ~221). Compare by name.
assert [a["name"] for a in u["core_abilities"]] == ['Scouts 7"', "Stealth"]
assert u["faction_abilities"] == []
assert u["abilities"][0]["enabled"] is False

su = ap.build_units(ps)
assert len(su) == 1 and su[0]["name"] == "Strike Team" and su[0]["points"] == 70
# exact matching: Fire Warrior=9 (not grabbing 'Shas'ui'), Shas'ui=1
assert sorted((m["name"], m["model_count"]) for m in su[0]["models"]) == \
    [("Fire Warrior", 9), ("Fire Warrior Shas'ui", 1)]

# ==================================================================
# Tidewall Shieldline: ability parsing must NOT split on ALL-CAPS
# keyword fragments (soup.get_text puts inline bold on their own lines).
# ==================================================================
TIDEWALL = """Tidewall Shieldline
Models
M
T
SV
W
LD
OC
Tidewall Defence Platform Hull
Invulnerable save: 5+
-
-
-
-
-
-
Tidewall Shieldline Hull
Invulnerable save: 5+
4"
8
3+
10
7+
0
Keywords
Fly
Fortification
Frame
Tidewall Shieldline
Transport
Vehicle
Costs
1 model
85 pts
2 models
105 pts
Unit composition
1 Tidewall Shieldline
Core abilities
Deadly Demise D3
Firing Deck 20
Unit abilities
Fortification
While an enemy unit is only within Engagement Range of one or more
FORTIFICATIONS
from your army:
That unit can still be selected as the target of ranged attacks, but each time such an attack is made, unless it is made with a Pistol, subtract 1 from the Hit roll.
Models in that unit do not need to take Desperate Escape tests due to Falling Back while Battle-shocked, except for those that will move over enemy models when doing so.
Tidewall Cover
Each time a ranged attack is allocated to a model, if that model is not fully visible to every model in the attacking unit because of this
FORTIFICATION
, that model has the Benefit of Cover against that attack.
Tidewall Defence Platform
If equipped with a Tidewall defence platform, this
FORTIFICATION
has a Wounds characteristic of 15.
Transport
This model has a transport capacity of 11
T'AU EMPIRE INFANTRY
models. It cannot transport
BATTLESUIT
,
KROOT
or
VESPID STINGWINGS
models. If this model is equipped with a Tidewall defence platform, it has a transport capacity of 22
T'AU INFANTRY
models instead.""".strip().splitlines()

pt = ap.parse_unit(TIDEWALL)
print("\n=== Tidewall abilities ===")
for n, d in pt["unit_abilities"]:
    print(f"  [{n}] {d[:70]}...")
names = [n for n, _ in pt["unit_abilities"]]
assert names == ["Fortification", "Tidewall Cover",
                 "Tidewall Defence Platform", "Transport"], names
transport = dict(pt["unit_abilities"])["Transport"]
assert "VESPID STINGWINGS" in transport and transport.endswith("instead.")
assert "22" in transport and "T'AU INFANTRY" in transport
assert "VESPID STINGWINGS" not in names          # no phantom ability
# robust model parse: 2 hull profiles, invuln 5, dash stats -> None
print(" models:", [(m["name"], m["T"], m["W"], m["invuln"]) for m in pt["models"]])
assert len(pt["models"]) == 2
sh = next(m for m in pt["models"] if "Shieldline" in m["name"])
assert sh["T"] == 8 and sh["W"] == 10 and sh["invuln"] == 5
plat = next(m for m in pt["models"] if "Platform" in m["name"])
assert plat["invuln"] == 5 and plat["T"] is None
# build: optional Platform Hull (not in composition) is dropped, only the
# Shieldline Hull is fielded, model_count 1, invuln carried through
tu = ap.build_units(pt)[0]
assert [(m["name"], m["model_count"]) for m in tu["models"]] == \
    [("Tidewall Shieldline Hull", 1)]
assert tu["models"][0]["invuln"] == 5 and tu["points"] == 85
print("\nALL PARSE/BUILD TESTS PASS")


# ==================================================================
# HTML round-trip: exercise the soup -> linearise -> parse path on real
# HTML structure (tables, inline <b> keyword fragments, split invuln,
# duplicated 'Models' label). Catches bugs pre-linearised fixtures miss.
# ==================================================================
def _html_roundtrip_test():
    import army_parse_40kapp as fa
    from bs4 import BeautifulSoup
    html = """<h1>Demo</h1>
    <h3>Models</h3>
    <table><tr><th>Models</th><th>M</th><th>T</th><th>SV</th><th>W</th><th>LD</th><th>OC</th></tr>
    <tr><td>Hull<span><b>Invulnerable save:</b> 5+</span></td><td>4"</td><td>8</td><td>3+</td><td>10</td><td>7+</td><td>0</td></tr></table>
    <h3>Ranged weapons</h3>
    <table><tr><th>RNG</th><th>A</th><th>BS</th><th>S</th><th>AP</th><th>D</th></tr>
    <tr><td>Gun<span>Rapid Fire 1</span></td><td>24"</td><td>2</td><td>4+</td><td>5</td><td>0</td><td>1</td></tr></table>
    <h3>Keywords</h3><ul><li>Vehicle</li><li>Transport</li></ul>
    <h3>Costs</h3><p>1 model</p><p>90 pts</p>
    <h3>Unit composition</h3><ul><li>1 Hull</li></ul>
    <h3>Unit abilities</h3>
    <h4>Transport</h4><p>Carries 11 <b>T\u2019AU INFANTRY</b> models. Not <b>VESPID STINGWINGS</b> models. Ends here.</p>
    <footer>Become a supporter</footer>"""
    soup = BeautifulSoup(html, "html.parser")
    _name, lines = fa.unit_content(soup)
    p = ap.parse_unit(lines)
    assert p["models"] and p["models"][0]["T"] == 8 and p["models"][0]["invuln"] == 5, p["models"]
    assert p["ranged"][0]["skill"] == 4 and p["ranged"][0]["keywords"] == ["Rapid Fire 1"]
    names = [n for n, _ in p["unit_abilities"]]
    assert names == ["Transport"], names               # no phantom from CAPS
    assert "VESPID STINGWINGS" in dict(p["unit_abilities"])["Transport"]
    print("HTML round-trip test PASS")


_html_roundtrip_test()


# ability name and description are now separate fields
_ku = ap.build_units(pk)[0]
assert _ku["abilities"][0]["name"] == "Fieldcraft"
assert _ku["abilities"][0]["description"].startswith("At the end")
assert "name" in _ku["abilities"][0] and "description" in _ku["abilities"][0]
print("ability name/description separation PASS")


# Regression: Feel No Pain extraction, torrent BS=N/A, missile RNG=N/A,
# AP shown as '-' (all found on the 5-faction real dumps).
def _real_dump_edge_cases():
    b = ap.section_bounds(["Models","M","T","SV","W","LD","OC",
        "Boy","32mm","Feel No Pain:","6+","6\"","5","5+","1","7+","2"])
    m = ap.parse_models(["Boy","32mm","Feel No Pain:","6+",
                         "6\"","5","5+","1","7+","2"])
    assert m[0]["name"]=="Boy" and m[0]["fnp"]==6 and m[0]["T"]==5 and m[0]["OC"]==2, m
    # torrent flamer: BS = N/A, AP negative
    w = ap.parse_weapons(["RNG","A","BS","S","AP","D",
        "Heavy flamer","Ignores Cover","Torrent","12\"","D6","N/A","5","-1","1"], False)
    assert w[0]["name"]=="Heavy flamer" and w[0]["skill"] is None \
        and w[0]["S"]==5 and w[0]["keywords"]==["Ignores Cover","Torrent"], w
    # missile with RNG=N/A must NOT anchor on that N/A (real BS follows)
    w2 = ap.parse_weapons(["RNG","A","BS","S","AP","D",
        "Big missile","Blast","N/A","2D6","2+","16","-4","1"], False)
    assert w2[0]["name"]=="Big missile" and w2[0]["skill"]==2 \
        and w2[0]["S"]==16 and w2[0]["AP"]==-4, w2
    # AP shown as '-' (== 0) still anchors correctly, two melee weapons split
    w3 = ap.parse_weapons(["RNG","A","WS","S","AP","D",
        "Maw","Precision","Melee","1","2+","5","-","D3+2",
        "Talons","Melee","12","2+","7","-2","2"], True)
    assert [x["name"] for x in w3]==["Maw","Talons"], [x["name"] for x in w3]
    assert w3[0]["keywords"]==["Precision"] and w3[1]["S"]==7
    print("real-dump edge-case regression PASS")


_real_dump_edge_cases()


def _subfaction_classification_test():
    import army_parse_40kapp as fa
    # SM-style: chapters in index, link back to parent; Aeldari-style:
    # sub not in index, links back. Both must resolve parent correctly.
    children = {"big-army": ["little-sub"], "little-sub": ["big-army"],
                "sm-like": ["chapter-a", "chapter-b"],
                "chapter-a": ["sm-like"], "chapter-b": ["sm-like"]}
    order = list(children)
    index = {"big-army", "sm-like", "chapter-a", "chapter-b"}  # little-sub not in index
    mains, parent = fa.classify(order, children, index)
    assert set(mains) == {"big-army", "sm-like"}, mains
    assert parent == {"little-sub": "big-army", "chapter-a": "sm-like",
                      "chapter-b": "sm-like"}, parent
    print("sub-faction classification test PASS")


_subfaction_classification_test()


def _selection_parser_test():
    import fetch_armies as fa
    facs = [("aeldari", "Aeldari"), ("orks", "Orks"), ("t-au-empire", "Tau")]
    assert fa._parse_selection("all", facs) == ["aeldari", "orks", "t-au-empire"]
    assert fa._parse_selection("", facs) == ["aeldari", "orks", "t-au-empire"]
    assert fa._parse_selection("1,3", facs) == ["aeldari", "t-au-empire"]
    assert fa._parse_selection("orks", facs) == ["orks"]
    assert fa._parse_selection("2 aeldari", facs) == ["orks", "aeldari"]
    assert fa._parse_selection("99 nope", facs) == []
    print("selection parser test PASS")


_selection_parser_test()


# Regression: per-model keyword syntax on Wahapedia datasheets
# ("KEYWORDS - ALL MODELS: ... | <MODEL>: ..."), seen on Company Heroes,
# Aun'va and Wolf Guard Headtakers. All groups are merged into one
# unit-level list, de-duplicated, document order kept.
def _per_model_keywords_test():
    from bs4 import BeautifulSoup
    import army_parse_wahapedia as apw

    def kws(inner):
        soup = BeautifulSoup(f'<div class="dsOuterFrame datasheet">{inner}</div>',
                             "html.parser")
        return (apw._kw_after("KEYWORDS", soup),
                apw._kw_after("FACTION KEYWORDS", soup))

    plain = ('<div class="ds2colKW"><div class="dsLeftColKW">KEYWORDS: '
             '<span><span class="kwb">INFANTRY</span>; '
             '<span class="kwb">GRENADES</span></span></div>'
             '<div class="dsRightColKW">FACTION KEYWORDS:<br>'
             '<span><span class="kwb">ADEPTUS</span> '
             '<span class="kwb">ASTARTES</span></span></div></div>')
    unit, faction = kws(plain)
    assert unit == ["INFANTRY", "GRENADES"], unit
    assert faction == ["ADEPTUS ASTARTES"], faction

    # two groups, an en dash in the heading, one keyword shared by both
    per_model = ('<div class="ds2colKW"><div class="dsLeftColKW">'
                 'KEYWORDS \u2013 ALL MODELS: '
                 '<span><span class="kwb">INFANTRY</span>; '
                 '<span class="kwb">IMPERIUM</span></span>'
                 '<span class="dsVertLine"></span>HUNTING WOLVES: '
                 '<span><span class="kwb">BEASTS</span>; '
                 '<span class="kwb">IMPERIUM</span></span></div>'
                 '<div class="dsRightColKW">FACTION KEYWORDS:<br>'
                 '<span><span class="kwb">SPACE</span> '
                 '<span class="kwb">WOLVES</span></span></div></div>')
    unit, faction = kws(per_model)
    assert unit == ["INFANTRY", "IMPERIUM", "BEASTS"], unit
    assert faction == ["SPACE WOLVES"], faction

    # single named group (no 'ALL MODELS'), hyphen instead of en dash
    single = ('<div class="ds2colKW"><div class="dsLeftColKW">'
              'KEYWORDS - AUN\u2019VA: <span><span class="kwb">CHARACTER</span>; '
              '<span class="kwb">EPIC</span> <span class="kwb">HERO</span>'
              '</span></div></div>')
    assert kws(single)[0] == ["CHARACTER", "EPIC HERO"], kws(single)[0]
    print("per-model keyword syntax PASS")


_per_model_keywords_test()


# Regression: chapter fallback + composition/cost edge cases
# (Kill Team Cassius: CH mask with the no-filter bit only; cost rows
# labelled with model names; '10 MODELS MAXIMUM' cap bullet; non-breaking
# hyphen in a size range; optional 0-model groups kept in the notes.)
def _chapter_and_composition_test():
    from bs4 import BeautifulSoup
    import army_parse_wahapedia as apw
    import army_parse_40kapp as ap40

    bitmap = apw._chapter_bit_map(["C0", "BA", "DW", "SW"])   # C0=1,BA=2,DW=3,SW=4

    def ds(dataf, colour):
        html = (f'<div class="dsOuterFrame datasheet" data-f="{dataf}">'
                f'<div class="ds2colKW {colour}">x</div></div>')
        return BeautifulSoup(html, "html.parser").select_one("div.dsOuterFrame")

    # normal sheet: the mask decides, the colour is ignored
    assert apw._ds_chapters(ds("CH:9,AA:1", "dsColorFrSM"), bitmap) == {"DW"}
    # no-filter bit only -> fall back to the colour class (Kill Team Cassius)
    assert apw._ds_chapters(ds("CH:1,AA:141", "dsColorFrCHDW"), bitmap) == {"DW"}
    # no chapter anywhere -> empty, and the caller warns instead of dropping
    assert apw._ds_chapters(ds("CH:1,AA:141", "dsColorFrSM"), bitmap) == set()

    # cost rows: 'N models', named groups (summed), surcharge rows ignored
    assert apw._cost_row_models("5 models") == 5
    assert apw._cost_row_models("3 Wolf Guard Headtakers, "
                                "3 Hunting Wolves") == 6
    assert apw._cost_row_models("1 Sword Brother, 4 Neophytes, "
                                "5 Initiates") == 10
    assert apw._cost_row_models("per Storm Shield") is None
    assert apw._cost_row_models("+ 1 Invader ATV") is None

    # composition: cap bullet dropped, non-breaking hyphen range parsed
    comp = ap40._parse_composition(["10 MODELS MAXIMUM",
                                    "1 Kill Team Sergeant",
                                    "3\u201110 Kill Team Intercessors",
                                    "0-4 Kill Team Intercessors with "
                                    "plasma incinerators"])
    assert comp == [(1, 1, "Kill Team Sergeant"),
                    (3, 10, "Kill Team Intercessors"),
                    (0, 4, "Kill Team Intercessors with "
                           "plasma incinerators")], comp

    # top-up: per-group minimums (1+3=4) below the priced size (10) are
    # topped up on the group with the most headroom, optional groups stay 0
    assert ap40._top_up([1, 3, 0], [1, 10, 4], 10) == [1, 9, 0]
    assert ap40._top_up([1, 5], [1, 10], 3) == [1, 5]      # already enough

    # a 0-model optional group is not emitted but survives in the notes
    note = ap40._dropped_note([{"name": "Hunting Wolves", "M": 10, "T": 4,
                                "Sv": 6, "W": 1, "LD": 8, "OC": 0}])
    assert "Hunting Wolves" in note and "T 4" in note
    print("chapter/composition edge-case test PASS")


_chapter_and_composition_test()


# Regression: the weapon-row anchor must accept every rendering of a
# "no ballistic skill" cell (torrent weapons - T'au flamers, Dvorgite
# skinner...). A rejected row is dropped SILENTLY, so the weapon simply
# vanishes from the unit.
def _torrent_skill_cell_test():
    from bs4 import BeautifulSoup
    import army_parse_wahapedia as apw

    row = ('<table><tr><td></td><td><span>T\u2019au flamer</span></td>'
           '<td>12"</td><td>D6</td><td>{skill}</td><td>4</td><td>0</td>'
           '<td>1</td></tr></table>')

    for skill in ("N/A", "NA", "n/a", "N/a", "-", "\u2013", "\u2014", "4+"):
        soup = BeautifulSoup(row.format(skill=skill), "html.parser")
        got = apw._weapon_rows(soup)
        assert got, f"weapon row dropped for skill cell {skill!r}"
        assert got[0][0] == "T\u2019au flamer", got[0][0]

    # a non-weapon row must still be rejected
    soup = BeautifulSoup(row.format(skill="Infantry"), "html.parser")
    assert apw._weapon_rows(soup) == []
    print("torrent skill-cell test PASS")


_torrent_skill_cell_test()


# Regression: 40k.app switched the skill cell of auto-hitting (Torrent)
# weapons from 'N/A' to a bare dash. A row that fails the skill anchor is
# dropped SILENTLY, so every T'au flamer / Dvorgite skinner vanished - and
# the dropped row's lines were absorbed into the next weapon's name/keyword
# head, taking a second weapon with them.
def _dash_skill_anchor_test():
    import army_parse_40kapp as ap40

    # RNG, A, skill, S, AP, D
    body = ["T\u2019au flamer", "Ignores Cover", "Torrent",
            '12"', "D6", "-", "4", "0", "1"]
    got = ap40.parse_weapons(list(body), melee=False)
    assert len(got) == 1, got
    w = got[0]
    assert w["name"] == "T\u2019au flamer", w["name"]
    assert w["skill"] is None                      # auto-hit
    assert (w["S"], w["AP"], w["D"]) == (4, 0, "1"), w
    assert w["keywords"] == ["Ignores Cover", "Torrent"], w["keywords"]

    # the old spelling still works
    body_na = list(body)
    body_na[5] = "N/A"
    assert len(ap40.parse_weapons(body_na, melee=False)) == 1

    # a dash in the AP slot must NOT anchor a phantom weapon: one weapon in,
    # one weapon out
    ap_dash = ["Pulse rifle", "Rapid Fire 1", '30"', "1", "4+", "5", "-", "1"]
    got = ap40.parse_weapons(ap_dash, melee=False)
    assert len(got) == 1 and got[0]["name"] == "Pulse rifle", got

    # dashes with no weapon-row shape around them must not anchor anything
    noise = ["Invulnerable save:", "-", "-", "-", "-", "-"]
    assert ap40.parse_weapons(noise, melee=False) == []
    print("dash skill-cell anchor test PASS")


_dash_skill_anchor_test()


# The parsers must SAY something when they skip data that looked real:
# a silently dropped row is how the Torrent-weapon regression went unnoticed.
def _dropped_row_warning_test():
    from bs4 import BeautifulSoup
    import army_parse_40kapp as ap40
    import army_parse_wahapedia as apw

    def captured(fn):
        """Run fn, return the warnings it emitted."""
        start = len(ap40.WARNINGS)
        buf, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            fn()
        finally:
            sys.stdout.close()
            sys.stdout = buf
        return ap40.WARNINGS[start:]

    # 40k.app: a weapon row whose skill cell is unknown ('X') is dropped;
    # its stat cells survive as a tail and must be reported
    body = ["Burst cannon", '18"', "4", "4+", "5", "0", "1",
            "T\u2019au flamer", "Torrent", '12"', "D6", "X", "4", "0", "1"]
    got = {}
    msgs = captured(lambda: got.setdefault(
        "w", ap40.parse_weapons(list(body), False, "Test unit")))
    assert len(got["w"]) == 1                       # only the burst cannon
    assert msgs and "Test unit" in msgs[0], msgs
    assert "ranged" in msgs[0]

    # ... and nothing is reported when every row parses
    ok_body = ["Burst cannon", '18"', "4", "4+", "5", "0", "1"]
    assert captured(lambda: ap40.parse_weapons(ok_body, False, "Test")) == []

    # Wahapedia: same, on a table row with the six trailing stat cells
    row = ('<div><table><tr><td></td><td><span>T\u2019au flamer</span></td>'
           '<td>12"</td><td>D6</td><td>X</td><td>4</td><td>0</td>'
           '<td>1</td></tr></table></div>')
    soup = BeautifulSoup(row, "html.parser")
    msgs = captured(lambda: apw._weapon_rows(soup, "Ghostkeel"))
    assert msgs and "Ghostkeel" in msgs[0] and "'X'" in msgs[0], msgs

    # a non-weapon table row with 7+ cells must NOT warn
    noise = ('<div><table><tr><td></td><td>QUARRY TALLY</td><td>Incursion</td>'
             '<td>2</td><td>Strike Force</td><td>3</td><td>Onslaught</td>'
             '<td>4</td></tr></table></div>')
    soup = BeautifulSoup(noise, "html.parser")
    assert captured(lambda: apw._weapon_rows(soup, "Bunker")) == []
    print("dropped-row warning test PASS")


_dropped_row_warning_test()


# Regression: the 'can be attached to' box drives leadership/support.
# Two ways it used to lose or invent entries:
#   - an entry rendered as a plain tooltip span, with no <a> at all
#     (VANGUARD VETERAN SQUAD, ERADICATOR SQUAD) was skipped;
#   - a numbered duplicate anchor (#Sternguard-Veteran-Squad-1) produced a
#     phantom unit name 'Sternguard Veteran Squad 1' matching nothing.
def _attach_box_test():
    from bs4 import BeautifulSoup
    import army_parse_wahapedia as apw

    box = ('<div class="dsAbility">This model can be attached to the '
           'following units:<ul>'
           '<li><a class="kwbOne" href="/x.html#Tactical-Squad">'
           '<span class="kwb">TACTICAL</span> <span class="kwb">SQUAD</span>'
           '</a></li>'
           '<li><span class="tooltip"><span class="kwb kwbu">VANGUARD</span> '
           '<span class="kwb kwbu">VETERAN</span> '
           '<span class="kwb kwbu">SQUAD</span></span></li>'
           '<li><a class="kwbOne" href="/x.html#Sternguard-Veteran-Squad">'
           '<span class="kwb">STERNGUARD VETERAN SQUAD</span></a></li>'
           '<li><a class="kwbOne" href="/x.html#Sternguard-Veteran-Squad-1">'
           '<span class="kwb">STERNGUARD VETERAN SQUAD</span></a></li>'
           '</ul></div>')
    ab = BeautifulSoup(box, "html.parser").select_one(".dsAbility")
    got = apw._attach_box_keywords(ab)
    assert got == ["Tactical Squad", "Vanguard Veteran Squad",
                   "Sternguard Veteran Squad"], got

    # a numeric suffix that is part of the real name must NOT be stripped:
    # it only goes when the visible text says otherwise
    one = ('<div class="dsAbility">attached to the following units:<ul>'
           '<li><a class="kwbOne" href="/x.html#Kill-Team-1">'
           '<span class="kwb">KILL TEAM 1</span></a></li></ul></div>')
    ab = BeautifulSoup(one, "html.parser").select_one(".dsAbility")
    assert apw._attach_box_keywords(ab) == ["Kill Team 1"]
    print("attach-box test PASS")


_attach_box_test()
