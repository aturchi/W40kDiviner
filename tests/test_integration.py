"""End-to-end: build a leader+support combined unit as the game assistant
would, then run the damage analysis to confirm the pipeline works and the
support's extra models contribute."""
import os, json
import testpaths                      # sets up sys.path to the engine src/
import leader_core as lc, analyzer_core as ac, unit_model as um

data = json.load(open(testpaths.roster("space-marines.json")))
units = {u["name"]: u for u in data["armies"][0]["units"]}
defender = um.units_from_native({"format": "w40k-sim/6", "armies": [
    {"name": "d", "units": [units["Intercessor Squad"]]}]})[0]

def total_damage(attacker):
    aview, dview = ac.build_views(attacker, defender, {}, {})
    ref = ac.reference_options(dview)[0][1]
    res = ac.run_analysis(aview, dview, ref, {}, "ranged")
    return round(sum(r["damage"]["mean"] for r in res["weapons"]), 3)

# Base unit alone
base_e = lc.make_entry(units["Bladeguard Veteran Squad"])
base = lc.build_entry_unit(base_e, {}, set(), {})
d_base = total_damage(base)

# + support (Bladeguard Ancient adds a model with its own weapons)
sup_e = lc.attach_support_to_entry(base_e, units["Bladeguard Ancient"])
withsup = lc.build_entry_unit(sup_e, {}, set(), {})
d_sup = total_damage(withsup)

print(f"base models={sum(m.model_count for m in base.models())} ranged_dmg={d_base}")
print(f"+support models={sum(m.model_count for m in withsup.models())} ranged_dmg={d_sup}")
assert sum(m.model_count for m in withsup.models()) == \
       sum(m.model_count for m in base.models()) + \
       sum(m.model_count for m in um.units_from_native(
           {"format":"w40k-sim/6","armies":[{"name":"x","units":[units["Bladeguard Ancient"]]}]})[0].models())
print("support adds its models to the combined unit: OK")

# + leader too
cap = units["Captain"]
if lc.native_can_attach(cap, units["Bladeguard Veteran Squad"]):
    both_e = dict(sup_e); both_e["leader"] = cap
    both = lc.build_entry_unit(both_e, {}, set(), {})
    print(f"+leader+support models={sum(m.model_count for m in both.models())} "
          f"L={both.attached_leader.name} S={both.attached_support.name}")
print("INTEGRATION TEST PASS")
