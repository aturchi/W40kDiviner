"""Test the new support mechanism and leader+support composition."""
import os, json
import testpaths                      # sets up sys.path to the engine src/
import unit_model as um

data = json.load(open(testpaths.roster("space-marines.json")))
units = um.units_from_native(data)
by = {u.name: u for u in units}

# Find a support unit (non-empty support) and a unit it can support.
supports = [u for u in units if getattr(u, "support", None)]
print(f"support units found: {len(supports)}")
for s in supports[:3]:
    print(f"  {s.name}: supports {s.support[:3]}...")

# Attach a support and check models/points combine.
s = next((u for u in units if u.name == "Bladeguard Ancient"), None)
tgt = next((u for u in units if "Bladeguard Veteran" in u.name), None)
assert s is not None and tgt is not None, "test units missing"
assert tgt.can_support(s), "Bladeguard Ancient should support Bladeguard Veteran Squad"
combined = tgt.attach_support(s)
n_base = sum(m.model_count for m in tgt.models())
n_comb = sum(m.model_count for m in combined.models())
print(f"attach_support: {tgt.name}({n_base}) + {s.name} -> {n_comb} models, "
      f"{combined.points} pts")
assert n_comb == n_base + sum(m.model_count for m in s.models())
# attach_support clones the helper (see Unit._attach / _clone_helper): the
# combined unit carries its OWN copy, so it is equal in every value that
# matters but never the identical pool object - two different joins of
# the same support must be free to diverge (see test_joined_leader_copy
# in test_unit_mask.py for the isolation itself).
assert combined.attached_support is not s
assert combined.attached_support.name == s.name
assert combined.attached_leader is None

# Leader + support compose: attach a leader too.
leaders = [u for u in units if getattr(u, "leadership", None)
           and tgt.can_attach(u)]
if leaders:
    ld = leaders[0]
    both = combined.attach_leader(ld)
    n_both = sum(m.model_count for m in both.models())
    print(f"leader+support: +{ld.name} -> {n_both} models, {both.points} pts")
    assert both.attached_support.name == s.name, \
        "support slot must survive leader attach"
    assert both.attached_leader is not ld, "leader slot must hold a copy"
    assert both.attached_leader.name == ld.name, "leader slot must be set"
    assert n_both == n_comb + sum(m.model_count for m in ld.models())
    # Effects from both helpers present (by VALUE: the leader slot holds
    # a clone of ld, so the effect dicts are equal but not the same
    # objects - see Unit._attach).
    assert all(e in both.leader_effects for e in ld.leader_effects)
    print("PASS: leader+support compose, both slots retained, effects merged")
else:
    print("(no compatible leader found for compose test)")

print("ALL SUPPORT TESTS PASS")
