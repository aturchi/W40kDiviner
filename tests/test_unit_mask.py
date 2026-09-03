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
  * a [JOINED] entry is built from independent copies of everything it
    combines - bodyguard, leader and support alike - so masking a row in
    one entry never shows up in another entry or in the same unit's own
    still-listed plain row; that independence is checked here too.

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


def unit_dict(name, weapons, abilities=None, leadership=None, support=None,
             count=1):
    return {"name": name, "profile_name": name, "points": 10,
            "keywords": ["Infantry"], "abilities": abilities or [],
            "core_abilities": [], "faction_abilities": [],
            "leader_effects": [], "leadership": leadership or [],
            "support": support or [], "apply_leader_effects_to_self": False,
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
              leadership=["Infantry"]),
    unit_dict("Chief2", [weapon("power sword", count=1, wtype="Melee")],
              abilities=[ability("Chief2 own", aid="a-own2")],
              leadership=["Infantry"]),
    unit_dict("Buddy", [weapon("plasma pistol", count=1)],
              abilities=[ability("Buddy own", aid="a-buddy")],
              support=["Infantry"]),
    unit_dict("Squad2", [weapon("bolter", count=5)], count=5)]}]}

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

# --- 5. a [JOINED] entry copies the squad too, not just the leader ----
# A unit is never removed from the analyzer's pool when it joins (see
# attack_analyzer.cmd_join: "units stay listed and reusable"), so the
# SAME Squad can sit in its own plain row AND inside a [JOINED] entry at
# once. The two must not affect each other (see Unit._attach /
# _clone_unit): the copy starts from whatever state the squad was in AT
# JOIN TIME (that part IS carried over - it is a snapshot, not a blank
# slate) but diverges from then on.

um.set_weapon_masked(um.weapon_at(squad, 0, 1), True)
um.set_ability_masked(um.ability_at(squad, "1"), True)
joined = squad.attach_leader(chief)
jplan = um.unit_plan(joined)
assert [m["label"] for m in jplan["models"]] == \
    ["Squad model x10", "Chief model x1"], jplan
assert jplan["off"] == 2, "the copy must start from the squad's state so far"
assert um.weapon_at(joined, 0, 0) is not um.weapon_at(squad, 0, 0)
um.set_weapon_masked(um.weapon_at(joined, 0, 0), True)
assert not um.is_weapon_masked(um.weapon_at(squad, 0, 0)), \
    "masking a weapon of the joined unit must NOT reach the plain unit"
# the leader's own ability is reachable from the joined rows
labels = [a["label"] for a in jplan["abilities"]]
assert "[unit] Chief own" in labels, labels
print("a [JOINED] entry copies the squad too, not just the leader")

# --- 6. two joins of the SAME leader stay independent ------------------
# Nothing is consumed in the analyzer (a leader/support stays reusable
# across several [JOINED] entries at once - see attack_analyzer.cmd_join
# and leader_core.ArmyJoinState), so the SAME Chief object may end up
# attached to two DIFFERENT combined units at once. Each join must own
# an INDEPENDENT copy of the Chief's profile: masking or editing him
# inside one joined unit must never leak into the other, nor into the
# reusable pool object he came from (see Unit._attach / _clone_unit).
squad2 = next(u for u in units if u.name == "Squad2")
joined_x = squad.attach_leader(chief)
joined_y = squad2.attach_leader(chief)
assert joined_x.attached_leader is not joined_y.attached_leader
assert joined_x.attached_leader is not chief

pistol_x = um.weapon_at(joined_x, 1, 0)     # model 1 = the attached Chief
pistol_y = um.weapon_at(joined_y, 1, 0)
pistol_pool = chief.models()[0].weapons[0]
assert pistol_x is not pistol_y and pistol_x is not pistol_pool
um.set_weapon_masked(pistol_x, True)
assert um.is_weapon_masked(pistol_x)
assert not um.is_weapon_masked(pistol_y), \
    "masking the Chief inside one joined unit leaked into the other"
assert not um.is_weapon_masked(pistol_pool), \
    "masking the Chief inside a joined unit leaked into the reusable pool"

label = "[unit] Chief own"
key_x = next(a["key"] for a in um.unit_plan(joined_x)["abilities"]
            if a["label"] == label)
key_y = next(a["key"] for a in um.unit_plan(joined_y)["abilities"]
            if a["label"] == label)
ab_x, ab_y, ab_pool = (um.ability_at(joined_x, key_x),
                       um.ability_at(joined_y, key_y), chief.abilities[0])
assert ab_x is not ab_y and ab_x is not ab_pool
um.set_ability_masked(ab_x, True)
assert um.is_ability_masked(ab_x)
assert not um.is_ability_masked(ab_y), \
    "disabling the Chief's ability in one joined unit leaked into the other"
assert not um.is_ability_masked(ab_pool), \
    "disabling the Chief's ability leaked into the reusable pool"
print("two joins of the same leader stay independently editable")

# --- 7. the SAME bodyguard joined to two DIFFERENT leaders -------------
# Mirrors section 6 for the other side: e.g. a Crisis Fireknife team
# tried under one Commander and, separately, under another. The squad
# is never consumed by the first join, so both attempts must be able to
# coexist with independent, separately maskable copies of the squad.
chief2 = next(u for u in units if u.name == "Chief2")
joined_p = squad.attach_leader(chief)
joined_q = squad.attach_leader(chief2)
bolter_p = um.weapon_at(joined_p, 0, 0)     # model 0 = the squad itself
bolter_q = um.weapon_at(joined_q, 0, 0)
bolter_pool = squad.models()[0].weapons[0]
assert bolter_p is not bolter_q and bolter_p is not bolter_pool
um.set_weapon_masked(bolter_p, True)
assert um.is_weapon_masked(bolter_p)
assert not um.is_weapon_masked(bolter_q), \
    "masking the squad under one Commander leaked into the other join"
assert not um.is_weapon_masked(bolter_pool), \
    "masking the squad under one Commander leaked into its reusable pool"
print("the same bodyguard joined to two different leaders stays "
     "independently editable")

# --- 8. the same rule applies to SUPPORT, and to leader+support combos -
# _attach clones both sides regardless of slot ('leader' or 'support'),
# so a Support unit must be just as independent across joins as a
# Leader - and a unit carrying BOTH at once must keep every one of its
# three parts (bodyguard, leader, support) separately editable.
buddy = next(u for u in units if u.name == "Buddy")

# 8a. same Support attached to two different targets
joined_r = squad.attach_support(buddy)
joined_s = squad2.attach_support(buddy)
plasma_r = um.weapon_at(joined_r, 1, 0)     # model 1 = the attached Buddy
plasma_s = um.weapon_at(joined_s, 1, 0)
plasma_pool = buddy.models()[0].weapons[0]
assert plasma_r is not plasma_s and plasma_r is not plasma_pool
um.set_weapon_masked(plasma_r, True)
assert um.is_weapon_masked(plasma_r)
assert not um.is_weapon_masked(plasma_s), \
    "masking the Buddy support under one target leaked into the other"
assert not um.is_weapon_masked(plasma_pool), \
    "masking the Buddy support leaked into the reusable pool"

# 8b. leader AND support together: both slots independent per join, on
# top of the bodyguard independence already covered in section 5
combo_m = squad.attach_leader(chief).attach_support(buddy)
combo_n = squad2.attach_leader(chief).attach_support(buddy)
assert combo_m.attached_leader is not combo_n.attached_leader
assert combo_m.attached_support is not combo_n.attached_support
assert combo_m.bodyguard_models()[0] is not combo_n.bodyguard_models()[0]
lw_m = combo_m.attached_leader.models()[0].weapons[0]
sw_m = combo_m.attached_support.models()[0].weapons[0]
lw_m.count, sw_m.count = 0, 0
lw_n = combo_n.attached_leader.models()[0].weapons[0]
sw_n = combo_n.attached_support.models()[0].weapons[0]
assert lw_n.count != 0 and sw_n.count != 0, \
    "editing the leader/support of one leader+support combo leaked " \
    "into the other combo"
assert chief.models()[0].weapons[0].count != 0 \
    and buddy.models()[0].weapons[0].count != 0, \
    "editing a combo's leader/support leaked into the reusable pool"
print("support units, and leader+support combos, stay independent too")

print("OK: unit mask")
