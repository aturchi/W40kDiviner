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
import dist_stats as ds
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
# must show the former. Same for a percentile, on EVERY statistic
# column - which is the whole reason analyzer_core convolves the
# attack and effective-attack laws instead of adding their means.
med = rr.totals_row(res, COLS, {k: "median" for k in COLS})
assert col(med, "dmg") == str(res["totals"]["damage"]["median"])
assert int(col(med, "dmg")) != sum(r["damage"]["median"] for r in rows), (
    "fixture too tame to tell the two apart")
for key, pmf_key in (("att_m", "attacks_pmf"), ("eff_m", "wounds_pmf"),
                     ("infl", "removed_pmf"), ("kills", "kills_pmf")):
    want = ds.percentile(res["totals"][pmf_key], 0.5)
    assert col(med, key) == str(want), (key, col(med, key), want)
# ...while a MEAN is additive, so switching to it must give back
# exactly what summing the column gives.
for key, field in (("att_m", "attacks"), ("eff_m", "wounds")):
    want = sum(r[field]["mean"] for r in rows)
    assert col(tot, key) == f"{want:.2f}", (key, col(tot, key), want)
# lo <= median <= hi, read off the same distribution.
lo = rr.totals_row(res, COLS, {k: "lo" for k in COLS})
hi = rr.totals_row(res, COLS, {k: "hi" for k in COLS})
for key in ("att_m", "eff_m", "dmg", "infl", "kills"):
    assert int(col(lo, key)) <= int(col(med, key)) <= int(col(hi, key)), key

# Inflicted wounds cannot exceed the wounds the unit owns, however much
# damage is rolled, so they cannot be a sum of the weapon rows either.
unit_w = ref["W"] * ref["models"]
infl = float(col(tot, "infl"))
assert infl <= unit_w + 1e-9, (infl, unit_w)
assert infl < sum(float(col(rr.weapon_row(r, COLS), "infl"))
                  for r in rows), \
    "chained weapons must inflict less than the same weapons fired apart"
assert float(col(tot, "dmg")) > infl, "gross damage must exceed what lands"

# ---- efficiency: totals row only ---------------------------------------
pts = res["totals"]["points"]
assert col(tot, "per100") == f"{infl / pts * 100:.2f}"
for r in rows:
    assert col(rr.weapon_row(r, COLS), "per100") == "", (
        "the points are the unit's, not any one weapon's")

# ---- a weapon row is that weapon alone ---------------------------------
r0 = rows[0]
assert col(rr.weapon_row(r0, COLS), "dmg") == f"{r0['damage']['mean']:.2f}"
assert col(rr.weapon_row(r0, COLS, {"dmg": "median"}), "dmg") == \
    str(r0["damage"]["median"])
# The efficiency column ignores the statistic on show: a ratio of two
# percentiles is not a percentile of the ratio.
assert col(rr.totals_row(res, COLS, {k: "hi" for k in COLS}), "per100") == \
    col(tot, "per100")

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

# ---- a median is genuinely NOT a column sum ---------------------------

# The real fixture cannot show this on the attack count: its weapons
# have a flat Attacks characteristic, so every median equals its mean
# and the sum happens to be right. Two coin-flip weapons make the point
# the fixture cannot.
coin = [0.0, 0.5, 0.5]                # 1 or 2 attacks, median 1
both = [0.0, 0.0, 0.25, 0.5, 0.25]    # their convolution, median 3
assert ds.percentile(coin, 0.5) * 2 != ds.percentile(both, 0.5)
synth = {"weapons": [{"name": "a", "count": 1, "attacks_pmf": coin},
                     {"name": "b", "count": 1, "attacks_pmf": coin}],
         "skipped": [],
         "totals": {"attacks_pmf": both, "points": 0}}
assert col(rr.totals_row(synth, COLS, {"att_m": "median"}),
           "att_m") == "3", "the totals must read their own distribution"
assert col(rr.totals_row(synth, COLS), "att_m") == "3.00", \
    "and the mean must still be the additive one"


# ---- Self-dmg appears only when a HAZARDOUS weapon is in the list -----

# The engine leaves self_damage_mean at None for every non-hazardous
# weapon, and a column of blanks still has to be read before it can be
# ignored - so the column follows the analysis, not the catalogue.
ONE = [0.0, 1.0]                      # a certain 1, as a PMF


def fake_results(self_damage):
    r = {"name": "gun", "count": 1, "attacks_pmf": ONE,
         "wounds_pmf": ONE, "damage_pmf": ONE, "damage_net_pmf": ONE,
         "self_damage_mean": self_damage,
         "self_damage_pmf": (None if self_damage is None
                             else [1.0 - 0.3, 0.3])}
    return {"weapons": [r], "skipped": [],
            "totals": {"damage_pmf": ONE, "damage_net_pmf": ONE,
                       "self_damage_pmf": r["self_damage_pmf"],
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
    assert col(row, "dmg", cols_) == "1.00"
    assert col(row, "att_m", cols_) == "1.00"
assert col(rr.weapon_row(haz_res["weapons"][0], rr.keys(haz_res)),
           "self", rr.keys(haz_res)) == "0.30"

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
# ...and the column whose statistic is deliberately frozen must say so.
assert "Always a mean" in rr.COLUMN_HELP["per100"]
# Every statistic column can be re-read; the two that cannot must not
# pretend otherwise by carrying a marker in their heading.
assert set(rr.STAT_PMF) | set(rr.FIXED_KEYS) == set(rr.ALL_KEYS)
assert rr.FIXED_KEYS == ("count", "per100")
for _k in rr.FIXED_KEYS:
    assert rr.heading(_k, "hi") == rr.heading(_k), _k
# The two percentiles either side of the median are dist_stats' choice
# and are named in exactly one place, so the table cannot disagree with
# the chart about what "the usual roll" means.
assert (rr.STAT_LABEL["lo"], rr.STAT_LABEL["hi"]) == ds.SPREAD_LABELS
for _k in rr.STAT_PMF:
    assert rr.heading(_k, "hi").endswith(ds.SPREAD_LABELS[1]), _k
# The cycle returns to where it started and never leaves the set.
_seen, _cur = [], "mean"
for _ in range(len(rr.STATS)):
    _cur = rr.next_stat(_cur)
    _seen.append(_cur)
assert _seen[-1] == "mean" and set(_seen) == set(rr.STATS), _seen
assert rr.next_stat("nonsense") == "mean"

print("result table: OK (%d rows)" % len(tbl))
