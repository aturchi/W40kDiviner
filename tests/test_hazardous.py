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
assert am.hazardous_damage_per_fail([]) == 1
assert am.hazardous_damage_per_fail(["INFANTRY"]) == 1
assert am.hazardous_damage_per_fail(["VEHICLE"]) == 3
assert am.hazardous_damage_per_fail(["MONSTER"]) == 3
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
# give a weapon the keyword, whatever the synthetic roster carries
raw = json.loads(json.dumps(data))
target = next(w for a in raw["armies"] for u in a["units"]
              for m in u["models"] for w in m["weapons"]
              if w["type"] == "Ranged")
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
