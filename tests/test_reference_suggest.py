"""analyzer_core.suggested_references: the reference profile the rules fix
for the wound roll (highest Toughness among the BODYGUARD models when a
leader/support is attached, among all models otherwise) plus the masking
invariant (a fully masked model group never becomes a reference).
No Tkinter involved: pure engine-side logic.
"""
import copy, json
import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import leader_core as lc
import unit_model as um

data = json.load(open(testpaths.roster("space-marines.json")))
uds = {d["name"]: d for a in data["armies"] for d in a["units"]}
units = um.units_from_native(data)
leaders, rest = lc.split_leaders(units)
_supports, others = lc.split_supports(rest)

# Pick a leader and a unit it can lead, straight from the native dicts.
lead_u = next(l for l in leaders if any(u.can_attach(l) for u in others))
unit_u = next(u for u in others if u.can_attach(lead_u))
unit_d = copy.deepcopy(uds[unit_u.name])
lead_d = copy.deepcopy(uds[lead_u.name])
# Normalise the shape: the checks below index the model groups by
# position (bodyguard 0, the added profile 1, the leader 2), so the base
# unit is reduced to its FIRST model group whatever the datasheet
# happens to carry -- real squads list a body AND a sergeant profile,
# which would shift every index. The weapons live on that first group.
unit_d["models"] = [unit_d["models"][0]]
lead_d["models"] = [lead_d["models"][0]]

# Two bodyguard profiles (T3 / T4) and a tougher leader (T6): the rules
# default is the T4 BODYGUARD, never the T6 leader.
unit_d["models"][0]["T"] = 3
tough = copy.deepcopy(unit_d["models"][0])
tough["name"] = "Tough model"
tough["T"] = 4
tough["model_count"] = 2
tough["weapons"] = []
unit_d["models"].append(tough)
lead_d["models"][0]["T"] = 6


def refs(entry, masked_copies=None):
    unit = lc.build_entry_unit(entry, masked_copies or {}, set(), {})
    dview = unit.against(None)
    opts = ac.reference_options(dview)
    return opts, ac.suggested_references(dview, opts)


# --- non-attached unit: highest T among all of its models -------------
opts, sugg = refs({"unit": unit_d})
assert len(opts) == 2, opts
assert {opts[i][1]["T"] for i in sugg} == {4}, (opts, sugg)

# --- attached unit: bodyguard only, the T6 leader is NOT suggested ----
opts, sugg = refs({"unit": unit_d, "leader": lead_d})
assert len(opts) == 3, opts
assert {opts[i][1]["T"] for i in sugg} == {4}, (opts, sugg)
print("suggestion follows the bodyguard rule")

# --- tie on Toughness: every tied profile is suggested ----------------
tie = copy.deepcopy(unit_d)
tie["models"][1]["T"] = 3
tie["models"][1]["Sv"] = 2                 # same T, different save
opts, sugg = refs({"unit": tie})
assert len(sugg) == 2, (opts, sugg)
print("tie on T suggests every tied profile")

# --- masking: a fully masked model group is not a reference at all ----
n_unit_models = len(unit_d["models"])
opts, _s = refs({"unit": unit_d, "leader": lead_d},
                masked_copies={n_unit_models:
                               lead_d["models"][0].get("model_count", 1)})
assert len(opts) == 2, opts
assert 6 not in {r["T"] for _l, r in opts}, opts
opts, sugg = refs({"unit": unit_d, "leader": lead_d},
                  masked_copies={1: tough["model_count"]})
assert {r["T"] for _l, r in opts} == {3, 6}, opts
assert {opts[i][1]["T"] for i in sugg} == {3}, (opts, sugg)
print("masked model groups are excluded from the references")

print("ALL REFERENCE-SUGGEST TESTS PASS")
