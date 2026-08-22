"""run_analysis now keeps the per-weapon PMFs, not just their stats.

Checks, on a real roster unit, that:
  - every weapon row carries a normalised damage_pmf / damage_net_pmf;
  - the stats reported in the row are exactly the ones read off those
    PMFs (no drift between the summary and the curve now shown);
  - the totals PMF is the convolution of the per-weapon PMFs, i.e. the
    histogram of the whole unit and the per-weapon histograms tell the
    same story.
No tkinter needed.
"""
import json

import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import attack_math as am
import dist_stats as ds
import unit_model as um

TOL = 1e-9

data = json.load(open(testpaths.roster("space-marines.json")))
units = um.units_from_native(data)
by = {u.name: u for u in units}

att = by["Intercessor Squad"]
dfn = by["Intercessor Squad"]
aview, dview = ac.build_views(att, dfn, {}, {})
label, ref = ac.reference_options(dview)[0]
res = ac.run_analysis(aview, dview, ref, {}, "ranged")
assert res["weapons"], "no weapon selected: fixture changed"

gross_conv, net_conv = am.delta(0), am.delta(0)
for r in res["weapons"]:
    for key in ("damage", "damage_net"):
        pmf = r[key + "_pmf"]
        assert abs(ds.total_mass(pmf) - 1.0) < 1e-9, (r["name"], key)
    # The row's mean/median must be what the kept PMF says.
    got = ds.stats(r["damage_pmf"])
    assert abs(got["mean"] - r["damage"]["mean"]) < TOL, r["name"]
    assert got["median"] == r["damage"]["median"], r["name"]
    got = ds.stats(r["damage_net_pmf"])
    assert abs(got["mean"] - r["damage_net"]["mean"]) < TOL, r["name"]
    gross_conv = am.convolve(gross_conv, r["damage_pmf"])
    net_conv = am.convolve(net_conv, r["damage_net_pmf"])

for name, conv in (("damage", gross_conv), ("damage_net", net_conv)):
    tot = res["totals"][name + "_pmf"]
    assert len(conv) == len(tot), (name, len(conv), len(tot))
    for v, (a, b) in enumerate(zip(conv, tot)):
        assert abs(a - b) < TOL, (name, v, a, b)

# Tail probabilities are monotone and bracket the median, which is the
# property the "P(damage >= N)" readout relies on.
net = res["totals"]["damage_net_pmf"]
med = ds.percentile(net, 0.5)
assert ds.tail_prob(net, med) >= 0.5 - 1e-12
assert ds.tail_prob(net, 0) >= ds.tail_prob(net, med) >= ds.tail_prob(
    net, len(net))

print("result PMFs: OK (%d weapons)" % len(res["weapons"]))
