"""Test leader_core native-level 3-slot split and build."""
import os, json
import testpaths                      # sets up sys.path to the engine src/
import leader_core as lc
data = json.load(open(testpaths.roster("space-marines.json")))
units = {u["name"]: u for u in data["armies"][0]["units"]}
unit = units["Bladeguard Veteran Squad"]
support = units["Bladeguard Ancient"]
n_unit = len(unit.get("models", []))
n_sup = len(support.get("models", []))

e = lc.make_entry(unit, None, support)
print("entry_models:", len(lc.entry_models(e)), "expected", n_unit + n_sup)
print("label:", lc.entry_label(e))
print("points:", lc.entry_points(e))

# No masking: full combined
built = lc.build_entry_unit(e, {}, set(), {})
print("built models:", sum(m.model_count for m in built.models()),
      "support:", built.attached_support.name if built.attached_support else None)
assert built.attached_support is not None

# Mask the support model group (global index n_unit) via masked_copies dict
# masked_copies masks COPIES; to drop the support model group set its count.
sup_count = support["models"][0].get("model_count", 1)
built2 = lc.build_entry_unit(e, {n_unit: sup_count}, set(), {})
print("mask support -> support:",
      built2.attached_support.name if built2.attached_support else None)
assert built2.attached_support is None, "support should be dropped"

# Mask all unit models -> support fights alone
mask_unit = {i: unit["models"][i].get("model_count", 1) for i in range(n_unit)}
built3 = lc.build_entry_unit(e, mask_unit, set(), {})
print("mask unit -> alone:", built3.name if built3 else None)
assert built3 is not None and built3.attached_support is None

# leader + support entry
leader = units["Captain"]
if lc.native_can_attach(leader, unit):
    e2 = lc.make_entry(unit, leader, support)
    print("leader+support entry_models:", len(lc.entry_models(e2)))
    built4 = lc.build_entry_unit(e2, {}, set(), {})
    print("  built:", sum(m.model_count for m in built4.models()),
          "L:", built4.attached_leader.name if built4.attached_leader else None,
          "S:", built4.attached_support.name if built4.attached_support else None)
    assert built4.attached_leader and built4.attached_support
print("ALL LEADER_CORE TESTS PASS")
