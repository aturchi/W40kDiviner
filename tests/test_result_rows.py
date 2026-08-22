"""The result table (src/result_rows.py).

The point of the totals row is that it does NOT simply add up the
column above it: means are additive, medians are not, and the inflicted
wounds and models killed depend on the weapons being chained into the
same target unit. This checks exactly that, on a real roster pairing,
and then the CSV form of the same table.
"""
import json

import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import result_rows as rr
import unit_model as um


def col(vals, key):
    return vals[rr.KEYS.index(key)]


data = json.load(open(testpaths.roster("space-marines.json")))
by = {u.name: u for u in um.units_from_native(data)}
att, dfn = by["Redemptor Dreadnought"], by["Intercessor Squad"]
aview, dview = ac.build_views(att, dfn, {}, {})
label, ref = ac.reference_options(dview)[0]
res = ac.run_analysis(aview, dview, ref, {}, "ranged")
rows = res["weapons"]
assert len(rows) > 1, "fixture changed: need several weapons"

tbl = rr.table(res)
assert len(tbl) == len(rows) + len(res.get("skipped", [])) + 1
name, tot = tbl[-1]
assert name.startswith("TOTAL"), name
assert f"{res['totals']['points']} pts" in name

# ---- what MAY be summed ------------------------------------------------
for key, field in (("att_m", "attacks"), ("eff_m", "wounds")):
    want = sum(r[field]["mean"] for r in rows)
    assert col(tot, key) == f"{want:.2f}", (key, col(tot, key), want)
assert col(tot, "count") == sum(r["count"] for r in rows)

# ---- what may NOT ------------------------------------------------------
# The median of the total is not the sum of the medians, and the table
# must show the former.
summed_medians = sum(r["damage"]["median"] for r in rows)
assert col(tot, "d_med") == str(res["totals"]["damage"]["median"])
assert int(col(tot, "d_med")) != summed_medians, (
    "fixture too tame to tell the two apart")

# Inflicted wounds cannot exceed the wounds the unit owns, however much
# damage is rolled, so they cannot be a sum of the weapon rows either.
unit_w = ref["W"] * ref["models"]
infl = float(col(tot, "infl"))
assert infl <= unit_w + 1e-9, (infl, unit_w)
assert infl < sum(float(col(rr.weapon_row(r), "infl")) for r in rows), \
    "chained weapons must inflict less than the same weapons fired apart"
assert float(col(tot, "d_mean")) > infl, "gross damage must exceed what lands"

# ---- efficiency: totals row only ---------------------------------------
pts = res["totals"]["points"]
assert col(tot, "per100") == f"{infl / pts * 100:.2f}"
for r in rows:
    assert col(rr.weapon_row(r), "per100") == "", (
        "the points are the unit's, not any one weapon's")

# ---- a weapon row is that weapon alone ---------------------------------
r0 = rows[0]
assert col(rr.weapon_row(r0), "d_mean") == f"{r0['damage']['mean']:.2f}"
assert col(rr.weapon_row(r0), "d_med") == str(r0["damage"]["median"])

# ---- an excluded weapon keeps its place, with the reason ---------------
sk = rr.skipped_row({"count": 2, "reason": "indirect fire only"})
assert len(sk) == len(rr.KEYS) and sk[0] == 2
assert sk[1] == "indirect fire only" and set(sk[2:]) == {""}

# ---- CSV ---------------------------------------------------------------
csv = rr.to_csv(res)
lines = csv.strip().split("\n")
assert lines[0].startswith("Weapon,")
assert len(lines) == len(tbl) + 1
assert lines[-1].startswith("TOTAL") or lines[-1].startswith('"TOTAL')
assert lines[0].count(",") == len(rr.COLUMNS)
for line in lines[1:]:
    # every row has the same number of fields once quoted names are
    # accounted for
    depth, fields = 0, 1
    for ch in line:
        if ch == '"':
            depth ^= 1
        elif ch == "," and not depth:
            fields += 1
    assert fields == len(rr.COLUMNS) + 1, (fields, line)

# A comma in a weapon name must not add a column.
odd = {"name": 'Gun, big "one"', "count": 1,
       "attacks": {"mean": 1.0, "median": 1},
       "wounds": {"mean": 1.0, "median": 1},
       "damage": {"mean": 1.0, "median": 1},
       "damage_net": {"mean": 1.0, "median": 1},
       "self_damage_mean": None}
fake = {"weapons": [odd], "skipped": [],
        "totals": {"damage": {"mean": 1.0, "median": 1},
                   "damage_net": {"mean": 1.0, "median": 1}, "points": 0}}
line = rr.to_csv(fake).strip().split("\n")[1]
assert line.startswith('"Gun, big ""one"""'), line

# ---- no chain: the columns it feeds are simply blank -------------------
plain = ac.run_analysis(aview, dview, ref, {}, "ranged", kills=False)
_n, tot2 = rr.table(plain)[-1]
assert col(tot2, "kills") == ""
assert col(tot2, "infl") == f"{plain['totals']['damage_net']['mean']:.2f}"

print("result table: OK (%d rows)" % len(tbl))
