"""What the analyzer's unit tree shows, and what masking a row does.

The widget (`unit_tree`) only renders what `unit_mask.unit_plan` says
and calls the setters below, so this covers the whole of the new
behaviour that is not tkinter:

  * the row plan spans the models, their weapons and every ability
    scope, and reports how many rows are switched off (a collapsed unit
    row has to be able to say so);
  * masking a weapon means count 0 - which the analyzer already reads as
    "not fired" - and unmasking restores the count it HAD, not 1;
  * masking an ability writes the same 'enabled' flag the Inspect
    checkbox used to write, so the engine sees it;
  * a MODEL row and a UNIT row are bulk gestures over the weapons below
    them: they carry no state, they read as masked when every weapon
    under them is, and they never touch the abilities;
  * a joined unit shares its weapon and ability objects with the plain
    unit, so masking one row shows in both. That is why the analyzer
    refreshes both panels after any change, and it is checked here.

No external data.
"""
import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import unit_mask as um
from unit_model import units_from_native


def ability(name, kw=None, aid=None):
    eff = {"type": "special", "data": {}} if kw is None else {
        "type": "setKeyword", "data": {
            "target": {"title": "All weapons", "key": "allWeapons"},
            "operation": {"title": "Add", "key": "add"}, "keyword": kw}}
    return {"name": name, "description": "", "enabled": True, "id": aid,
            "share_with_unit": False, "conditions": [], "effect": eff}


def weapon(name, count=1, wtype="Ranged", A="2", D="1"):
    return {"name": name, "type": wtype, "RNG": 24, "A": A,
            "BS": 3, "WS": 3, "S": 4, "AP": 0, "D": D, "count": count,
            "keywords": [], "abilities": []}


def unit_dict(name, weapons, abilities=None, leadership=None, count=1):
    return {"name": name, "profile_name": name, "points": 10,
            "keywords": ["Infantry"], "abilities": abilities or [],
            "core_abilities": [], "faction_abilities": [],
            "leader_effects": [], "leadership": leadership or [],
            "support": [], "apply_leader_effects_to_self": False,
            "damageable": False, "unit_composition": "",
            "wargear_options": "", "notes": "",
            "models": [{"name": f"{name} model", "model_count": count,
                        "M": 6, "T": 4, "Sv": 3, "W": 2, "LD": 6, "OC": 1,
                        "invuln": None, "fnp": None, "keywords": [],
                        "abilities": [], "weapons": weapons}]}


DATA = {"format": "w40k-sim/6", "armies": [{"name": "Test", "units": [
    unit_dict("Squad", [weapon("bolter", count=10),
                        weapon("fist", count=1, wtype="Melee")],
              abilities=[ability("Grant", kw="LETHAL HITS", aid="a-grant"),
                         ability("Quiet", aid="a-quiet")], count=10),
    unit_dict("Chief", [weapon("pistol", count=1)],
              abilities=[ability("Chief own", aid="a-own")],
              leadership=["Infantry"])]}]}

units = units_from_native(DATA)
squad = next(u for u in units if u.name == "Squad")
chief = next(u for u in units if u.name == "Chief")
native_squad = DATA["armies"][0]["units"][0]

# --- 1. the row plan --------------------------------------------------

plan = um.unit_plan(squad)
assert [m["label"] for m in plan["models"]] == ["Squad model x10"], plan
assert [w["label"] for w in plan["models"][0]["weapons"]] == \
    ["[R] bolter", "[M] fist"]
assert [w["count"] for w in plan["models"][0]["weapons"]] == [10, 1]
assert [a["label"] for a in plan["abilities"]] == \
    ["[unit] Grant", "[unit] Quiet"]
assert [a["key"] for a in plan["abilities"]] == ["0", "1"]
assert plan["off"] == 0 and um.off_label(plan) == ""
assert um.weapon_at(squad, 0, 0).name == "bolter"
assert um.weapon_at(squad, 9, 0) is None and um.weapon_at(squad, 0, 9) is None
assert um.ability_at(squad, "1")["name"] == "Quiet"
assert um.ability_at(squad, "9") is None and um.ability_at(squad, "x") is None
print("row plan spans models, weapons and abilities")

# --- 2. masking a weapon is count 0, and it comes back as it was ------

bolter = um.weapon_at(squad, 0, 0)
assert um.set_weapon_masked(bolter, True) is True
assert bolter.count == 0 and um.is_weapon_masked(bolter)
# the native dict follows, so a saved session carries the same state
assert native_squad["models"][0]["weapons"][0]["count"] == 0
assert um.set_weapon_masked(bolter, True) is False, "already masked"
assert um.set_weapon_masked(bolter, False) is True
assert bolter.count == 10, "unmasking must restore TEN bolters, not one"

# a count typed by hand becomes what an unmask restores
um.set_weapon_count(bolter, 4)
um.set_weapon_masked(bolter, True)
um.set_weapon_masked(bolter, False)
assert bolter.count == 4
# ...INCLUDING a hand-typed 0, which is the same gesture as masking the
# row: the count being overwritten must be remembered there too, or ten
# bolters switched off by typing 0 come back as one.
um.set_weapon_count(bolter, 10)
um.set_weapon_count(bolter, 0)                 # double-click, type "0"
assert um.is_weapon_masked(bolter)
assert um.set_weapon_masked(bolter, False) is True
assert bolter.count == 10, "typing 0 must remember the count it replaced"
# and a second 0 in a row must not overwrite the saved count with 0
um.set_weapon_count(bolter, 0)
um.set_weapon_count(bolter, 0)
um.set_weapon_masked(bolter, False)
assert bolter.count == 10
um.set_weapon_count(bolter, 10)
# a weapon already at 0 when first seen comes back at DEFAULT_COUNT
fist = um.weapon_at(squad, 0, 1)
fist.count = 0
assert um.is_weapon_masked(fist)
um.set_weapon_masked(fist, False)
assert fist.count == um.DEFAULT_COUNT
um.set_weapon_count(fist, 1)
print("weapon masking is count 0, and restores the count it had")

# --- 3. masking an ability is the flag the engine reads ---------------


def lethal_active(unit):
    view = ac.build_views(unit, unit, {}, {})[0]
    return any("LETHAL HITS" in {str(k).upper() for k in w.keywords}
               for m in view.models() for w in m.weapons)


grant = um.ability_at(squad, "0")
assert lethal_active(squad), "the granting ability is inert to begin with"
assert um.set_ability_masked(grant, True) is True
assert grant["enabled"] is False and um.is_ability_masked(grant)
assert not lethal_active(squad), "a masked ability still reached the engine"
assert um.set_ability_masked(grant, True) is False
um.set_ability_masked(grant, False)
assert lethal_active(squad)
print("ability masking writes the flag the engine reads")

# --- 4. the count of switched-off rows --------------------------------

um.set_weapon_masked(um.weapon_at(squad, 0, 1), True)
um.set_ability_masked(um.ability_at(squad, "1"), True)
plan = um.unit_plan(squad)
assert plan["off"] == 2 and um.off_label(plan) == "2 off"
assert plan["models"][0]["weapons"][1]["masked"] is True
assert plan["abilities"][1]["masked"] is True
print("a collapsed unit row can report what is switched off")

# --- 4b. model and unit rows in bulk ----------------------------------
# Restore the squad to a clean state first: sections 2-4 left rows off.
um.set_unit_masked(squad, False)
um.set_ability_masked(um.ability_at(squad, "1"), False)
assert um.unit_plan(squad)["off"] == 0

bolter, fist = um.weapon_at(squad, 0, 0), um.weapon_at(squad, 0, 1)
assert not um.is_model_masked(squad, 0) and not um.is_unit_masked(squad)

# one weapon off is NOT a masked model: the row shows the count instead
um.set_weapon_masked(bolter, True)
plan = um.unit_plan(squad)
assert plan["models"][0]["off"] == 1
assert plan["models"][0]["masked"] is False, "half off is not off"
assert plan["masked"] is False
assert um.off_count_label(1) == "1 off" and um.off_count_label(0) == ""

# the model row switches the rest off, and reads as masked
assert um.set_model_masked(squad, 0, True) == 1, "only the fist moved"
assert um.is_model_masked(squad, 0) and um.is_unit_masked(squad)
assert bolter.count == 0 and fist.count == 0
assert um.unit_plan(squad)["masked"] is True

# ...and unmasking brings every weapon back at the COUNT it had, the
# one the player had switched off by hand included (declared: the bulk
# gesture does not remember which those were)
assert um.set_model_masked(squad, 0, False) == 2
assert (bolter.count, fist.count) == (10, 1)
assert not um.is_model_masked(squad, 0)

# the unit row does the same over every model...
assert um.set_unit_masked(squad, True) == 2
assert um.is_unit_masked(squad) and um.unit_plan(squad)["masked"]
# ...but it never touches the abilities: they are listed one by one
assert all(not a["masked"] for a in um.unit_plan(squad)["abilities"]), \
    "a unit row must not switch the datasheet's abilities off"
assert um.set_unit_masked(squad, False) == 2
assert (bolter.count, fist.count) == (10, 1)

# a model with no weapons is never maskable: there would be nothing
# to undo, and a row that cannot come back is a trap
empty = um.model_weapons(squad, 9)
assert empty == [] and um.set_model_masked(squad, 9, True) == 0
assert not um.is_model_masked(squad, 9)
print("model and unit rows are bulk gestures over the weapons below")

# --- 5. a joined unit shares the objects ------------------------------
# This is why the analyzer refreshes BOTH panels after a change.

um.set_weapon_masked(um.weapon_at(squad, 0, 1), True)
um.set_ability_masked(um.ability_at(squad, "1"), True)
joined = squad.attach_leader(chief)
jplan = um.unit_plan(joined)
assert [m["label"] for m in jplan["models"]] == \
    ["Squad model x10", "Chief model x1"], jplan
assert jplan["off"] == 2, "the joined view must show the same rows as off"
assert um.weapon_at(joined, 0, 0) is um.weapon_at(squad, 0, 0)
um.set_weapon_masked(um.weapon_at(joined, 0, 0), True)
assert um.is_weapon_masked(um.weapon_at(squad, 0, 0)), \
    "masking a weapon of the joined unit must show in the plain unit too"
# the leader's own ability is reachable from the joined rows
labels = [a["label"] for a in jplan["abilities"]]
assert "[unit] Chief own" in labels, labels
print("joined and plain units share the rows, as the panels assume")

print("OK: unit mask")
