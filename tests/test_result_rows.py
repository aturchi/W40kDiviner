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


def col(vals, key, cols=None):
    """A cell by column KEY. The column list belongs to the analysis,
    so it has to be threaded through: indexing into the full catalogue
    would read the wrong cell as soon as one column is dropped."""
    return vals[list(cols if cols is not None else COLS).index(key)]


data = json.load(open(testpaths.roster("space-marines.json")))
by = {u.name: u for u in um.units_from_native(data)}
att, dfn = by["Redemptor Dreadnought"], by["Intercessor Squad"]
aview, dview = ac.build_views(att, dfn, {}, {})
label, ref = ac.reference_options(dview)[0]
res = ac.run_analysis(aview, dview, ref, {}, "ranged")
rows = res["weapons"]
assert len(rows) > 1, "fixture changed: need several weapons"
COLS = rr.keys(res)

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
    assert col(rr.weapon_row(r, COLS), "per100") == "", (
        "the points are the unit's, not any one weapon's")

# ---- a weapon row is that weapon alone ---------------------------------
r0 = rows[0]
assert col(rr.weapon_row(r0, COLS), "d_mean") == f"{r0['damage']['mean']:.2f}"
assert col(rr.weapon_row(r0, COLS), "d_med") == str(r0["damage"]["median"])

# ---- an excluded weapon keeps its place, with the reason ---------------
sk = rr.skipped_row({"count": 2, "reason": "indirect fire only"}, COLS)
assert len(sk) == len(COLS) and sk[0] == 2
assert sk[1] == "indirect fire only" and set(sk[2:]) == {""}

# ---- CSV ---------------------------------------------------------------
csv = rr.to_csv(res)
lines = csv.strip().split("\n")
assert lines[0].startswith("Weapon,")
assert len(lines) == len(tbl) + 1
assert lines[-1].startswith("TOTAL") or lines[-1].startswith('"TOTAL')
assert lines[0].count(",") == len(COLS)
for line in lines[1:]:
    # every row has the same number of fields once quoted names are
    # accounted for
    depth, fields = 0, 1
    for ch in line:
        if ch == '"':
            depth ^= 1
        elif ch == "," and not depth:
            fields += 1
    assert fields == len(COLS) + 1, (fields, line)

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
assert col(tot2, "kills", rr.keys(plain)) == ""
assert col(tot2, "infl", rr.keys(plain)) == \
    f"{plain['totals']['damage_net']['mean']:.2f}"

# ---- Self-dmg appears only when a HAZARDOUS weapon is in the list -----

# The engine leaves self_damage_mean at None for every non-hazardous
# weapon, and a column of blanks still has to be read before it can be
# ignored - so the column follows the analysis, not the catalogue.
def fake_results(self_damage):
    r = {"name": "gun", "count": 1,
         "attacks": {"mean": 1.0, "median": 1},
         "wounds": {"mean": 1.0, "median": 1},
         "damage": {"mean": 1.0, "median": 1},
         "damage_net": {"mean": 1.0, "median": 1},
         "self_damage_mean": self_damage}
    return {"weapons": [r], "skipped": [],
            "totals": {"damage": {"mean": 1.0, "median": 1},
                       "damage_net": {"mean": 1.0, "median": 1},
                       "points": 0}}


plain_res, haz_res = fake_results(None), fake_results(0.33)
assert "self" not in rr.keys(plain_res)
assert "self" in rr.keys(haz_res)
assert len(rr.columns(haz_res)) == len(rr.columns(plain_res)) + 1
assert rr.keys(haz_res) == rr.ALL_KEYS, "nothing else may be dropped"
# Zero is a NUMBER, not an absence: a hazardous weapon that happens to
# average no self-damage still owns its column.
assert "self" in rr.keys(fake_results(0.0))

# Every other column keeps its position, and the numbers keep landing in
# the cells the headings promise - the whole point of projecting a row
# onto the key list instead of building it positionally.
for res_ in (plain_res, haz_res):
    cols_ = rr.keys(res_)
    row = rr.weapon_row(res_["weapons"][0], cols_)
    assert len(row) == len(cols_)
    assert col(row, "d_mean", cols_) == "1.00"
    assert col(row, "att_m", cols_) == "1.00"
assert col(rr.weapon_row(haz_res["weapons"][0], rr.keys(haz_res)),
           "self", rr.keys(haz_res)) == "0.33"

# ---- heading help ------------------------------------------------------

# Every column carries help, and it is keyed by column, so a renamed
# key would silently lose its explanation instead of failing loudly.
assert set(rr.COLUMN_HELP) == set(rr.ALL_KEYS), (
    set(rr.ALL_KEYS) ^ set(rr.COLUMN_HELP))
assert rr.NAME_HELP, "the weapon column needs one too"
for _k, _text in rr.COLUMN_HELP.items():
    assert len(_text) > 40, _k
    # Every entry is split into a definition and the caveat under it,
    # which is the half that is actually worth reading.
    assert "\n\n" in _text, (_k, "no caveat paragraph")
# The two columns a weapon row and the totals row disagree about must
# say so in as many words.
for _k in ("infl", "kills"):
    assert "ALONE" in rr.COLUMN_HELP[_k], _k
# ...and the two that are safe to add up must say THAT.
for _k in ("att_m", "eff_m"):
    assert "dditive" in rr.COLUMN_HELP[_k], _k
assert "NOT additive" in rr.COLUMN_HELP["d_med"]

print("result table: OK (%d rows)" % len(tbl))
