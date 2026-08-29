"""HAZARDOUS: self-damage only, never a second profile.

A datasheet lists the two firing modes of a plasma weapon as two
separate weapons - "Plasma pistol - standard" and "Plasma pistol -
supercharge" - and it is the supercharged one that carries HAZARDOUS,
with its higher Strength, better AP and (usually) more Damage already
written in. The engine used to add a THIRD, boosted profile on top of
it, which exists on no datasheet.

So HAZARDOUS now means exactly one thing: roll the Hazardous test.
  * the analysis lists the weapon once, with its own stats, and reports
    the mean self-damage next to it;
  * the dice resolver rolls one test per weapon copy (1-2 fails) and
    deals 3 damage to a MONSTER/VEHICLE bearer, 1 otherwise;
  * which profile to fire stays the player's choice - both are listed.

Checked here against the real rosters, since the point of the change is
that the roster already holds both profiles.
"""
import json

import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import attack_math as am
import attack_resolve as ar
import random
import unit_model as um
from unit_model import Weapon

TOL = 1e-9
REF = {"T": 5, "Sv": 3, "W": 6, "invuln": None, "fnp": None, "models": 1,
       "keywords": set()}


def mech_for(keywords):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(keywords, m)
    return m


# --- 1. the keyword does not change the attack maths ------------------
w = Weapon(name="plasma", wtype="Ranged", A="2", skill=3, S=8, AP=-3,
           D="2", count=1)
plain = am.analyze_weapon(w, REF, {}, mech_for([]))
haz = am.analyze_weapon(w, REF, {}, mech_for(["HAZARDOUS"]))
assert abs(plain["damage"]["mean"] - haz["damage"]["mean"]) < TOL, \
    "HAZARDOUS must not touch the damage dealt"
assert mech_for(["HAZARDOUS"]).hazardous is True
print("HAZARDOUS leaves the attack maths alone")

# --- 2. the self-damage is the whole of it ----------------------------
# 06.03 costs the unit 3 mortal wounds per failed roll only "if EACH
# model in that unit is a MONSTER/VEHICLE model", so the cost is read
# from one keyword set PER MODEL. It is the ATTACHED unit that makes
# the difference bite: Unit._attach gives the merged unit the UNION of
# its parts' keywords, so a MONSTER Leader would otherwise look as if
# every trooper beside it were a MONSTER too.
assert am.hazardous_damage_per_fail([]) == 1          # no models: neutral
assert am.hazardous_damage_per_fail(None) == 1
assert am.hazardous_damage_per_fail([["INFANTRY"]]) == 1
assert am.hazardous_damage_per_fail([["VEHICLE"]]) == 3
assert am.hazardous_damage_per_fail([["MONSTER"]]) == 3
assert am.hazardous_damage_per_fail([["monster", " vehicle "]]) == 3
# Every model qualifies -> 3, even when they qualify differently.
assert am.hazardous_damage_per_fail([["MONSTER"], ["VEHICLE"]]) == 3
# One model short -> 1. This is the case the union reading got wrong.
assert am.hazardous_damage_per_fail([["VEHICLE"], ["INFANTRY"]]) == 1
assert am.hazardous_damage_per_fail(
    [["INFANTRY"]] * 9 + [["VEHICLE"]]) == 1
# CHARACTER was in the 10th-ed. wording and is NOT in the 11th-ed. one.
assert am.hazardous_damage_per_fail([["CHARACTER", "INFANTRY"]]) == 1
# The old flat call is a TypeError, not a wrong answer: a bare list of
# strings would otherwise be read as one model per LETTER and quietly
# return 1.
try:
    am.hazardous_damage_per_fail(["VEHICLE"])
except TypeError:
    pass
else:
    raise AssertionError("a flat keyword set was accepted silently")
# 2/6 per weapon copy, times the damage per failed test
assert abs(am.hazardous_self_damage_mean(1, 1) - 1 / 3) < TOL
assert abs(am.hazardous_self_damage_mean(3, 3) - 3.0) < TOL
rng = random.Random(20260817)
w3 = Weapon(name="plasma", wtype="Ranged", A="1", skill=3, S=8, AP=-3,
            D="1", count=3)
tot = 0
for _ in range(4000):
    tot += ar.resolve_weapon(w3, REF, {}, mech_for(["HAZARDOUS"]), rng,
                             3)["self_damage"]
mean = tot / 4000.0
expected = am.hazardous_self_damage_mean(3, 3)
assert abs(mean - expected) < 0.15, (mean, expected)
# ...and no self-damage without the keyword
assert ar.resolve_weapon(w3, REF, {}, mech_for([]), rng,
                         3)["self_damage"] == 0
print("the Hazardous test is rolled per weapon copy, and only then")

# --- 3. the analysis lists ONE row per weapon -------------------------
data = json.load(open(testpaths.roster("space-marines.json")))
units = {u.name: u for u in um.units_from_native(data)}
# Give a weapon the keyword, whatever roster is active. It must be a
# weapon the RANGED attack setup actually keeps: PISTOL / CLOSE-QUARTERS
# weapons fire only in close quarters and INDIRECT FIRE / HUNTER ones can
# be greyed out too, so "the first Ranged weapon in the file" is not
# necessarily one the analysis will report a row for.
_SKIPPABLE = set(ac.CLOSE_QUARTERS_KW) | {"INDIRECT FIRE"}


def _analysable(weapon) -> bool:
    kws = {str(k).strip().upper() for k in (weapon.get("keywords") or [])}
    return not (kws & _SKIPPABLE) and not any(k.startswith("HUNTER")
                                              for k in kws)


raw = json.loads(json.dumps(data))
target = next(w for a in raw["armies"] for u in a["units"]
              for m in u["models"] for w in m["weapons"]
              if w["type"] == "Ranged" and _analysable(w))
target["keywords"] = list(target.get("keywords") or []) + ["HAZARDOUS"]
owner = next(u["name"] for a in raw["armies"] for u in a["units"]
             for m in u["models"] for w in m["weapons"] if w is target)
u2 = {x.name: x for x in um.units_from_native(raw)}
att, dfn = u2[owner], next(v for k, v in u2.items() if k != owner)
aview, dview = ac.build_views(att, dfn, {})
ref = ac.reference_options(dview)[0][1]
res = ac.run_analysis(aview, dview, ref, {}, "ranged")
names = [r["name"] for r in res["weapons"]]
assert not any("[HAZARDOUS]" in n for n in names), \
    f"no boosted duplicate row may be produced: {names}"
assert len(names) == len(set(names)), f"one row per weapon: {names}"
row = next(r for r in res["weapons"] if r["name"] == target["name"])
assert row["self_damage_mean"], "the self-damage must be reported"
others = [r for r in res["weapons"] if r["name"] != target["name"]]
assert all(r["self_damage_mean"] is None for r in others), \
    "only the HAZARDOUS weapon carries self-damage"
# the same weapon without the keyword gives the same damage
plain_raw = json.loads(json.dumps(data))
u3 = {x.name: x for x in um.units_from_native(plain_raw)}
av3, dv3 = ac.build_views(u3[owner], u3[dfn.name], {})
res3 = ac.run_analysis(av3, dv3, ac.reference_options(dv3)[0][1], {},
                       "ranged")
row3 = next(r for r in res3["weapons"] if r["name"] == target["name"])
assert abs(row["damage"]["mean"] - row3["damage"]["mean"]) < TOL, \
    "HAZARDOUS must not change what the weapon does to the target"
assert abs(res["totals"]["damage"]["mean"]
           - res3["totals"]["damage"]["mean"]) < TOL, \
    "and the totals must match too"
print("the analysis lists one row per weapon, self-damage attached")

# --- 3b. the cost is read per MODEL, on a REAL attached unit ----------
# Everything below is built with Unit.attach_leader, the same call the
# leader dialog makes: no model-level keyword is injected by hand, so
# the fixture exercises the mechanism the shipped rosters actually use
# (Model.inherited_keywords, frozen at load time and surviving the
# merge) rather than a JSON shape nothing ever writes.
def _unit_dict(name, kws, mname, n, leadership=(), model_kw=()):
    return {"name": name, "profile_name": name, "points": 10,
            "keywords": list(kws), "abilities": [],
            "core_abilities": [], "faction_abilities": [],
            "leadership": list(leadership), "support": [],
            "leader_effects": [], "apply_leader_effects_to_self": False,
            "damageable": False, "unit_composition": "",
            "wargear_options": "", "notes": "",
            "models": [{"name": mname, "model_count": n, "M": 6, "T": 5,
                        "Sv": 3, "W": 3, "LD": 6, "OC": 1,
                        "invuln": None, "fnp": None,
                        "keywords": list(model_kw),
                        "abilities": [], "weapons": []}]}


def _pair(bodyguard_kw, leader_kw, leader_model_kw=()):
    """(attacker view of Squad+Boss, defender view), attached for real."""
    raw2 = {"format": "w40k-sim/6", "armies": [{"name": "A", "units": [
        _unit_dict("Squad", bodyguard_kw, "Trooper", 5),
        _unit_dict("Boss", leader_kw, "Boss", 1,
                   leadership=[bodyguard_kw[0]],
                   model_kw=leader_model_kw)]}]}
    made = {x.name: x for x in um.units_from_native(raw2)}
    joined = made["Squad"].attach_leader(made["Boss"])
    return ac.build_views(joined, made["Squad"], {})


# INFANTRY squad led by a MONSTER: the union says MONSTER, the models
# do not all agree, so the unit pays 1. This is the inverse check that
# keeps the claim honest - the union reading is computed and shown to
# give the WRONG answer, so the case cannot pass by both agreeing.
av, _dv = _pair(["Infantry"], ["Monster", "Character"])
assert {k.upper() for k in av.keywords} & {"MONSTER", "VEHICLE"}, \
    "the fixture must carry MONSTER at unit level"
assert am.hazardous_damage_per_fail([av.keywords]) == 3, \
    "reading the union gives 3 - that is what this case must not do"
assert ac.hazardous_damage(av) == 1, \
    "a MONSTER Leader does not make the troopers MONSTER models"
# The mirror: a MONSTER squad led by an INFANTRY CHARACTER, also 1.
av, _dv = _pair(["Monster"], ["Infantry", "Character"])
assert ac.hazardous_damage(av) == 1
# Both parts big -> 3, which is the only way to reach 3 on a merged unit.
av, _dv = _pair(["Vehicle"], ["Vehicle", "Character"])
assert ac.hazardous_damage(av) == 3
# Neither part big -> 1.
av, _dv = _pair(["Infantry"], ["Infantry", "Character"])
assert ac.hazardous_damage(av) == 1
# An unattached unit is unaffected: every model reads its own unit,
# which is the only unit there is.
av, _dv = _pair(["Vehicle"], ["Vehicle", "Character"])
lone = ac.build_views(
    next(u for u in um.units_from_native(json.loads(json.dumps(data)))
         if u.name == owner), dfn, {})[0]
assert ac.hazardous_damage(lone) == am.hazardous_damage_per_fail(
    [lone.keywords]), "an unattached unit must read the same either way"

# A keyword granted at COMBAT time must count too. modifier_engine
# applies a unit-scoped setKeyword by writing on the unit view's own
# keyword list (its kind == "kw" branch, target 'unit'), which leaves
# each model's load-time inherited_keywords untouched - so reading the
# models' original sets alone would miss it.
av, _dv = _pair(["Infantry"], ["Infantry", "Character"])
assert ac.hazardous_damage(av) == 1
av.keywords = list(av.keywords) + ["VEHICLE"]
assert ac.hazardous_damage(av) == 3, \
    "a keyword granted on the unit view during combat was not seen"
# ...and a keyword revoked during combat stops counting.
av, _dv = _pair(["Vehicle"], ["Vehicle", "Character"])
assert ac.hazardous_damage(av) == 3
av.keywords = [k for k in av.keywords if k.upper() != "VEHICLE"]
assert ac.hazardous_damage(av) == 1, \
    "a keyword revoked on the unit view during combat still counted"

# A model's OWN keywords still count. Unit.model_keywords delegates to
# Model.effective_keywords, which ADDS a plain token to the inherited
# set and SUPPRESSES one written '-TOKEN'. Nothing in the shipped
# rosters writes model-level keywords today, but the schema carries
# them and the profile editor can set them, so the delegation is pinned
# rather than assumed.
av, _dv = _pair(["Vehicle"], ["Infantry", "Character"],
                leader_model_kw=["Vehicle"])
assert ac.hazardous_damage(av) == 3, \
    "a model's own VEHICLE keyword must make it a VEHICLE model"
av, _dv = _pair(["Vehicle"], ["Vehicle", "Character"],
                leader_model_kw=["-Vehicle"])
assert ac.hazardous_damage(av) == 1, \
    "a model that suppresses VEHICLE is not a VEHICLE model"

# Finally, the analyzer itself must go through that helper and not
# answer the question a second way. Two units built from the SAME
# template with the SAME weapon differ only in their models' keywords,
# so the all-VEHICLE one must owe exactly THREE TIMES the mixed one. If
# either read the union, both would owe 3 and the ratio would be 1.
def _mixed_roster(leader_kw):
    """The real roster, with 'owner' turned into an attached unit whose
    Leader carries 'leader_kw', keeping the HAZARDOUS weapon in place."""
    raw2 = json.loads(json.dumps(raw))
    army = next(a for a in raw2["armies"]
                for u in a["units"] if u["name"] == owner)
    unit = next(u for u in army["units"] if u["name"] == owner)
    unit["keywords"] = ["Vehicle"]
    boss = json.loads(json.dumps(unit))
    boss["name"] = boss["profile_name"] = owner + " Boss"
    boss["keywords"] = list(leader_kw)
    boss["leadership"] = ["Vehicle"]
    for m in boss["models"]:
        m["model_count"] = 1
        m["weapons"] = []
    army["units"].append(boss)
    made = {x.name: x for x in um.units_from_native(raw2)}
    joined = made[owner].attach_leader(made[owner + " Boss"])
    other = next(v for k, v in made.items()
                 if k not in (owner, owner + " Boss"))
    return ac.build_views(joined, other, {})


def _self_damage(views):
    av2, dv2 = views
    out = ac.run_analysis(av2, dv2, ac.reference_options(dv2)[0][1], {},
                          "ranged")
    return next(r for r in out["weapons"]
                if r["name"] == target["name"])["self_damage_mean"]


mean_mixed = _self_damage(_mixed_roster(["Infantry", "Character"]))
mean_all = _self_damage(_mixed_roster(["Vehicle", "Character"]))
assert mean_mixed, "the mixed unit must still report self-damage"
assert abs(mean_all - 3 * mean_mixed) < TOL, \
    (f"the analyzer does not charge 06.03 per model: mixed={mean_mixed} "
     f"all-VEHICLE={mean_all}")
print("the hazard cost is read from every model, not from the union")

# --- 4. the rosters really do carry both profiles ---------------------
# (the assumption the change rests on: a HAZARDOUS weapon always has a
# non-HAZARDOUS twin of the same base name)
def base_name(name):
    low = name.lower()
    for sep in (" – ", " - ", " (", " —"):
        if sep in low:
            low = low.split(sep)[0]
    return low.strip()


checked = 0
for army in data["armies"]:
    for u in army["units"]:
        for m in u["models"]:
            for w in m["weapons"]:
                if not any("hazardous" in str(k).lower()
                           for k in w["keywords"]):
                    continue
                checked += 1
                twins = [x for x in m["weapons"]
                         if x is not w and x["type"] == w["type"]
                         and base_name(x["name"]) == base_name(w["name"])
                         and not any("hazardous" in str(k).lower()
                                     for k in x["keywords"])]
                assert twins, f"{u['name']}: {w['name']} has no twin"
# The synthetic roster carries no plasma, so this loop is empty there;
# it bites under --real_data, and the rule was verified by hand on the
# Space Marines, T'au and T'au Legends rosters (45 HAZARDOUS weapons,
# 45 twins, no exception).
print(f"every HAZARDOUS weapon has a plain twin ({checked} checked "
      f"in this roster)")

print("ALL HAZARDOUS TESTS PASS")
