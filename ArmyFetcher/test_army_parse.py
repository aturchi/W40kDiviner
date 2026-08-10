"""Offline self-test: run the pure parser/builder against linearised
line fixtures derived from real 40k.app pages (markdown markers stripped,
links reduced to their text - i.e. what soup.get_text() yields)."""
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
