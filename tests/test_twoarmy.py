"""Test the two-army join produces correct rosters via ArmyJoinState
(the pure model the dialog drives). Simulates the OK result."""
import os, json
import testpaths                      # sets up sys.path to the engine src/
import leader_core as lc
data = json.load(open(testpaths.roster("space-marines.json")))
u = {x["name"]: x for x in data["armies"][0]["units"]}

data_a = [u["Assault Intercessor Squad"], u["Captain"], u["Intercessor Squad"]]
data_b = [u["Bladeguard Veteran Squad"], u["Bladeguard Ancient"]]

sa = lc.ArmyJoinState(data_a)
sb = lc.ArmyJoinState(data_b)
# Army A: join Captain -> Assault Intercessor
sa.join_leader(u["Captain"], u["Assault Intercessor Squad"])
# Army B: join Ancient (support) -> Bladeguard Vet
sb.join_support(u["Bladeguard Ancient"], u["Bladeguard Veteran Squad"])

result = (sa.entries(), sb.entries())
print("Army A roster:")
for e in result[0]: print("  ", lc.entry_label(e))
print("Army B roster:")
for e in result[1]: print("  ", lc.entry_label(e))
# Build combined units to confirm they resolve
for side, ents in zip("AB", result):
    for e in ents:
        built = lc.build_entry_unit(e, {}, set(), {})
        assert built is not None
print("both armies build OK")
print("ALL TWO-ARMY TESTS PASS")
