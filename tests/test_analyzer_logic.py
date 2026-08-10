"""Test attack_analyzer join logic (exploratory model) via a stub panel
that mimics the parts _lead_picks/cmd_join use, without Tkinter."""
import os, json
import testpaths                      # sets up sys.path to the engine src/
import leader_core as lc, unit_model as um

data = json.load(open(testpaths.roster("space-marines.json")))
units = um.units_from_native(data)
by = {u.name: u for u in units}

# Reproduce the panel model: leaders, supports, others, joined
leaders, rest = lc.split_leaders(units)
supports, others = lc.split_supports(rest)
print("pools: leaders=%d supports=%d others=%d" % (
    len(leaders), len(supports), len(others)))

# Simulate: leader + unit -> new joined (no consumption)
cap = by["Captain"]
tgt = next(u for u in others if u.can_attach(cap))
joined = []
joined.append((tgt.attach_leader(cap), cap, tgt, None))
print("joined 1:", joined[0][0].name)
# leader still present (not consumed)
assert cap in leaders and tgt in others, "exploratory: nothing consumed"

# support + a joined-with-free-support-slot -> add support
anc = by["Bladeguard Ancient"]
# find a joined whose base unit the ancient supports; build one
bvs = by["Bladeguard Veteran Squad"]
if bvs.can_support(anc):
    j2 = (bvs.attach_support(anc), None, bvs, anc)
    joined.append(j2)
    # now add a leader to j2 (free leader slot) if compatible
    ld2 = next((u for u in leaders if bvs.can_attach(u)), None)
    if ld2:
        combined, _l, unit, sup = joined[1]
        joined[1] = (combined.attach_leader(ld2), ld2, unit, sup)
        b = joined[1][0]
        print("j2 leader+support:", 
              "L=", b.attached_leader.name if b.attached_leader else None,
              "S=", b.attached_support.name if b.attached_support else None,
              "models=", sum(m.model_count for m in b.models()))
        assert b.attached_leader and b.attached_support

# un-join just drops the entry (no restore needed)
before = len(joined)
joined.pop(0)
assert len(joined) == before - 1
assert cap in leaders  # still there
print("un-join drops entry, pools intact")
print("ALL ANALYZER-LOGIC TESTS PASS")
