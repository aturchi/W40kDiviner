"""Test ArmyJoinState pure join model."""
import os, json
import testpaths                      # sets up sys.path to the engine src/
import leader_core as lc
data = json.load(open(testpaths.roster("space-marines.json")))
units = {u["name"]: u for u in data["armies"][0]["units"]}

pick = [units["Assault Intercessor Squad"], units["Captain"],
        units["Bladeguard Veteran Squad"], units["Bladeguard Ancient"],
        units["Intercessor Squad"]]
st = lc.ArmyJoinState(pick)
print("initial: leaders=%d supports=%d others=%d" % (
    len(st.leaders), len(st.supports), len(st.others)))

# Join Captain -> Assault Intercessor Squad
cap = units["Captain"]; ais = units["Assault Intercessor Squad"]
assert st.can_lead(cap, ais)
st.join_leader(cap, ais)
print("after leader join: joined=%d leaders=%d others=%d" % (
    len(st.joined), len(st.leaders), len(st.others)))
assert cap not in st.leaders and ais not in st.others, "consumed units gone"

# Join Bladeguard Ancient (support) -> Bladeguard Veteran Squad
anc = units["Bladeguard Ancient"]; bvs = units["Bladeguard Veteran Squad"]
assert st.can_support(anc, bvs)
st.join_support(anc, bvs)
print("after support join: joined=%d supports=%d" % (
    len(st.joined), len(st.supports)))

# Add a leader to the support-joined entry (leader+support in two steps)
# find a leader that can lead bvs still in pool
extra_leader = next((u for u in st.leaders if st.can_lead(u, bvs)), None)
if extra_leader:
    st.add_to_joined(1, extra_leader, "leader")
    print("added leader to joined[1]:", lc.entry_label(st.joined[1]))

# entries() reflects everything
ents = st.entries()
print("final entries:", len(ents))
for e in ents:
    print("  ", lc.entry_label(e))

# unjoin restores parts
st.unjoin(0)
print("after unjoin[0]: joined=%d leaders=%d others=%d" % (
    len(st.joined), len(st.leaders), len(st.others)))
assert cap in st.leaders and ais in st.others, "parts restored"
print("ALL JOINSTATE TESTS PASS")

# --- join_combo: leader + support + unit in one entry ---
def test_combo():
    import leader_core as lc, json, os
    data = json.load(open(testpaths.roster("space-marines.json")))
    u = {x["name"]: x for x in data["armies"][0]["units"]}
    st = lc.ArmyJoinState([u["Captain"], u["Bladeguard Ancient"],
                           u["Bladeguard Veteran Squad"]])
    st.join_combo(u["Bladeguard Veteran Squad"], u["Captain"],
                  u["Bladeguard Ancient"])
    e = st.joined[0]
    assert e["leader"] and e["support"], "combo must fill both slots"
    built = lc.build_entry_unit(e, {}, set(), {})
    assert built.attached_leader and built.attached_support
    print("COMBO JOIN (leader+support+unit) PASS")

test_combo()
