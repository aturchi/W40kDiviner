"""Pinned analyses and the comparison matrix (src/comparison.py).

Two analyses run under different flags look perfectly comparable once
they are numbers in adjacent columns, which is how a right calculation
becomes a wrong conclusion. So besides the arithmetic, this checks that
the context of every pin is carried along and that a difference in it
is flagged.
"""
import json

import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import comparison as cmp
import dist_stats as ds
import unit_model as um


def analyse(att, dfn, flags=None, mods=None, mode="ranged"):
    flags, mods = flags or {}, mods or {}
    aview, dview = ac.build_views(att, dfn, flags, mods)
    label, ref = ac.reference_options(dview)[0]
    res = ac.run_analysis(aview, dview, ref, flags, mode, manual=mods)
    return label, res, cmp.context_signature(flags, mods, mode)


data = json.load(open(testpaths.roster("space-marines.json")))
by = {u.name: u for u in um.units_from_native(data)}
att, dfn = by["Redemptor Dreadnought"], by["Intercessor Squad"]

lbl_a, res_a, ctx_a = analyse(att, dfn)
lbl_b, res_b, ctx_b = analyse(att, dfn, flags={"cover": True})
pin_a = cmp.make_pin("plain", res_a, ctx_a)
pin_b = cmp.make_pin("in cover", res_b, ctx_b)

# ---- a pin holds the numbers AND how they were obtained ---------------
assert pin_a["values"]["damage"] == res_a["totals"]["damage"]["mean"]
assert pin_a["values"]["inflicted"] == res_a["totals"]["removed"]["mean"]
assert pin_a["points"] == res_a["totals"]["points"]
assert pin_a["pmfs"]["kills"] == res_a["totals"]["kills_pmf"]
assert "ranged" in ctx_a and "cover" not in ctx_a
assert "cover" in ctx_b, ctx_b

# Cover can only help the defender, so the second pin must be no better.
assert pin_b["values"]["inflicted"] <= pin_a["values"]["inflicted"] + 1e-9
assert pin_b["values"]["inflicted"] < pin_a["values"]["inflicted"], \
    "fixture too tame: cover changed nothing"

# ---- the matrix -------------------------------------------------------
rows = cmp.matrix([pin_a, pin_b])
labels = [lab for lab, _cells in rows]
assert "Wounds inflicted \u03bc" in labels
by_label = dict(rows)
first, second = by_label["Wounds inflicted \u03bc"]
assert first == f"{pin_a['values']['inflicted']:.2f}"
assert "(" in second and second.startswith(
    f"{pin_b['values']['inflicted']:.2f}")
# the delta is signed and points the right way
delta = second.split("(")[1].rstrip(")")
assert delta.startswith("-"), delta

# The first column never carries a delta against itself.
assert "(" not in first

# A metric missing everywhere is dropped rather than shown blank.
bare = cmp.make_pin("no chain", ac.run_analysis(
    *ac.build_views(att, dfn, {}, {}),
    ac.reference_options(ac.build_views(att, dfn, {}, {})[1])[0][1],
    {}, "ranged", kills=False), "ranged")
assert bare["values"]["kills"] is None
assert "Models killed \u03bc" not in [lab for lab, _c in cmp.matrix([bare])]
# ...but it stays as soon as one pin has it.
assert "Models killed \u03bc" in [lab for lab, _c in
                                  cmp.matrix([pin_a, bare])]

# ---- the context is shown, and a difference is called out -------------
ctx_rows = dict(cmp.context_rows([pin_a, pin_b]))
assert ctx_rows["Analysis"] == ["plain", "in cover"]
assert ctx_rows["vs first"] == ["-", "DIFFERENT"]
same = dict(cmp.context_rows([pin_a, cmp.make_pin("again", res_a, ctx_a)]))
assert same["vs first"] == ["-", "same"]

# ---- identical pins: every delta reads as no change -------------------
twin = cmp.matrix([pin_a, cmp.make_pin("copy", res_a, ctx_a)])
for _label, cells in twin:
    if cells[1]:
        assert cells[1].endswith("(=)"), cells

# ---- CSV --------------------------------------------------------------
csv = cmp.to_csv([pin_a, pin_b])
lines = csv.strip().split("\n")
assert lines[0].split(",")[0] == "Metric"
assert lines[1].startswith("Context")
assert len(lines) == 2 + len(cmp.METRICS)
for line in lines:                      # one field per pin, plus the label
    depth, fields = 0, 1
    for ch in line:
        if ch == '"':
            depth ^= 1
        elif ch == "," and not depth:
            fields += 1
    assert fields == 3, (fields, line)
# the CSV keeps raw numbers, no delta annotations
assert "(" not in csv.replace("(unit", "")

# ---- overlay series ---------------------------------------------------
ser = cmp.overlay_series([pin_a, pin_b], "kills")
assert [s["name"] for s in ser] == ["plain", "in cover"]
# The series carry the PMF and nothing else - the canvas draws survival
# curves and needs no summary - so the statistic is computed here.
assert set(ser[0]) == {"name", "pmf"}, sorted(ser[0])
assert ds.stats(ser[0]["pmf"])["mean"] > ds.stats(ser[1]["pmf"])["mean"]

print("comparison: OK")
