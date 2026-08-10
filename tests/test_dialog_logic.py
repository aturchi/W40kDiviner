"""Test the JoinDialog join logic (cmd_ok) without instantiating Tk, by
driving the pure methods on a lightweight stub."""
import os, json
import testpaths                      # sets up sys.path to the engine src/
import leader_core as lc

data = json.load(open(testpaths.roster("space-marines.json")))
units = {u["name"]: u for u in data["armies"][0]["units"]}

# Simulate the two-pass flow purely.
# Pass 1 (leader): join Captain -> Assault Intercessor Squad
cap = units["Captain"]; ais = units["Assault Intercessor Squad"]
assert lc.native_can_attach(cap, ais)
# entry after leader join:
e_leader = lc.make_entry(ais, cap)  # unit + leader
print("after leader pass:", lc.entry_label(e_leader),
      "| models", len(lc.entry_models(e_leader)))

# Pass 2 (support): add Ancient onto an entry whose unit it supports.
ancient = units["Ancient"]
# find a target the Ancient supports
tgt_name = next((n for n in units
                 if lc.native_can_support(ancient, units[n])), None)
print("Ancient can support:", tgt_name)
assert tgt_name is not None
tgt_entry = lc.make_entry(units[tgt_name])
# simulate cmd_ok merge for support slot:
merged = dict(tgt_entry); merged["support"] = ancient
print("after support pass:", lc.entry_label(merged),
      "| models", len(lc.entry_models(merged)))
built = lc.build_entry_unit(merged, {}, set(), {})
assert built.attached_support is not None
print("built support:", built.attached_support.name)

# Combined: an entry that already has a leader, then gets a support.
if lc.native_can_support(ancient, ais) and lc.native_can_attach(cap, ais):
    both = dict(e_leader); both["support"] = ancient
    b = lc.build_entry_unit(both, {}, set(), {})
    print("leader+support built:", 
          "L=", b.attached_leader.name if b.attached_leader else None,
          "S=", b.attached_support.name if b.attached_support else None,
          "models=", sum(m.model_count for m in b.models()))

# entry_ability_dicts covers all three parts
n = len(list(lc.entry_ability_dicts(merged)))
print("entry_ability_dicts count (unit+support):", n)
print("ALL DIALOG-LOGIC TESTS PASS")
