"""Three structural features that have no dice in them.

  * NEGATED CONDITIONS: every condition carries a 'negate' flag, so a
    rule of the form "only while X" is written as "disabled while NOT X".
    A roll-time condition cannot be negated (the effect grammar has no
    negation), and such an ability is switched off rather than applied
    with the wrong sense.
  * disableWeapon: the weapon is not selectable for the attack while the
    ability holds. The analyzer reports it as skipped, exactly like an
    indirect-fire or close-quarters exclusion, instead of resolving it.
  * attachmentSlots: how many Leader / Support units may be attached.
    Both default to 1; a datasheet ability can raise or set them.

No tkinter needed.
"""
import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import modifier_engine as me
import unit_model as um


def cond(ctype, data, negate=False):
    d = dict(data)
    d["negate"] = negate
    return {"text": ctype, "type": ctype, "data": d, "description": "",
            "preselected": False}


def ability(effect, conditions, name="a", enabled=True):
    return {"name": name, "description": "", "enabled": enabled,
            "share_with_unit": False, "conditions": conditions,
            "effect": effect}


def unit_dict(name, keywords, weapon_abilities=(), abilities=(),
              leadership=(), models=1, **extra):
    d = {"name": name, "profile_name": name, "points": 10,
         "keywords": list(keywords), "abilities": list(abilities),
         "core_abilities": [], "faction_abilities": [],
         "leadership": list(leadership), "support": [],
         "leader_effects": [], "apply_leader_effects_to_self": False,
         "damageable": False, "unit_composition": "",
         "wargear_options": "", "notes": "",
         "models": [{"name": name + " model", "model_count": models,
                     "M": 6, "T": 4, "Sv": 4, "W": 1, "LD": 6, "OC": 1,
                     "invuln": None, "fnp": None, "keywords": [],
                     "abilities": [], "weapons": [
                         {"name": "rifle", "type": "Ranged", "RNG": 24,
                          "A": 2, "BS": 3, "S": 4, "AP": 0, "D": 1,
                          "count": 1, "keywords": [], "abilities": []},
                         {"name": "turret", "type": "Ranged", "RNG": 18,
                          "A": 3, "BS": 4, "S": 5, "AP": 0, "D": 1,
                          "count": 1, "keywords": [],
                          "abilities": list(weapon_abilities)}]}]}
    d.update(extra)
    return d


def build(*unit_dicts):
    return um.units_from_native(
        {"format": "w40k-sim/6",
         "armies": [{"name": "T", "units": list(unit_dicts)}]})


STATIONARY = {"remainedStationary": {"title": "Attacker remained stationary",
                                     "key": "attackerStationary"}}
GATE = ability({"type": "disableWeapon", "data": {}},
               [cond("remainedStationary", STATIONARY, negate=True)],
               name="needs to stand still")


def selection(unit, flags):
    aview, _d = ac.build_views(unit, unit, flags)
    kept, skipped = ac.select_weapons_split(aview, "ranged")
    return [w.name for w in kept], {w.name: why for w, why in skipped}


# --- 1. a negated condition gates the weapon the right way round ------
gunner = build(unit_dict("gunner", ["Infantry"], weapon_abilities=[GATE]))[0]
kept, skipped = selection(gunner, {})
assert "turret" not in kept, "the gated weapon fired although the unit moved"
assert skipped.get("turret") == ac.DISABLED_SKIP, skipped
assert "rifle" in kept, "the gate must not touch the other weapons"
kept, skipped = selection(gunner, {"stationary": True})
assert "turret" in kept, "the gated weapon did not come back when stationary"
assert not skipped, skipped
print("a negated condition gates a weapon in and out of the attack")

# --- 2. without the negation the sense is reversed --------------------
plain = ability({"type": "disableWeapon", "data": {}},
                [cond("remainedStationary", STATIONARY)])
mover = build(unit_dict("mover", ["Infantry"], weapon_abilities=[plain]))[0]
assert "turret" in selection(mover, {})[0]
assert "turret" not in selection(mover, {"stationary": True})[0]
print("the un-negated condition has the opposite sense, as it should")

# --- 3. a roll-time condition cannot be negated -----------------------
crit = cond("crit", {"crit": {"title": "Critical hit", "key": "hitRoll"}},
            negate=True)
dyn = build(unit_dict("dyn", ["Infantry"], weapon_abilities=[
    ability({"type": "disableWeapon", "data": {}}, [crit])]))[0]
view = me.build_view(dyn, None, me.Context(), role="attacker")
assert not any("WEAPON_DISABLED" in w.effects
               for m in view.models() for w in m.weapons), \
    "a negated roll-time condition must switch the ability off"
print("a negated roll-time condition switches the ability off")

# --- 4. attachment slots ----------------------------------------------
SLOTS2 = ability({"type": "attachmentSlots", "data": {
    "slot": {"title": "Leader", "key": "leader"},
    "operator": {"title": "Set", "key": "set"}, "value": "2"}},
    [], name="bodyguard", enabled=False)
squad = unit_dict("squad", ["Infantry", "Squad"], abilities=[SLOTS2],
                  models=10)
boss1 = unit_dict("boss1", ["Character"], leadership=["Squad"])
boss2 = unit_dict("boss2", ["Character"], leadership=["Squad"])
squad_u, b1, b2 = build(squad, boss1, boss2)

assert squad_u.slot_capacity("leader") == 1, "default is one Leader slot"
assert squad_u.can_attach(b1)
assert not squad_u.attach_leader(b1).can_attach(b2), \
    "a second Leader must be refused while the ability is off"

squad["abilities"][0]["enabled"] = True
squad_u, b1, b2 = build(squad, boss1, boss2)
assert squad_u.slot_capacity("leader") == 2, "the ability must open a slot"
both = squad_u.attach_leader(b1)
assert both.can_attach(b2), "the second Leader must fit"
both = both.attach_leader(b2)
assert [u.name for u in both.attached_leaders] == ["boss1", "boss2"]
assert both.attached_leader is b1, "the single-slot accessor is the first one"
assert not both.can_attach(b2), "a third Leader must be refused"
assert sum(m.model_count for m in both.models()) == 12, "10 + 1 + 1"
assert sum(m.model_count for m in both.bodyguard_models()) == 10, \
    "the bodyguard models must exclude both Leaders"
# 'add' works too, and the support slot is independent
squad["abilities"][0]["effect"]["data"]["operator"] = {"title": "Add",
                                                       "key": "add"}
squad["abilities"][0]["effect"]["data"]["value"] = "1"
squad_u = build(squad, boss1, boss2)[0]
assert squad_u.slot_capacity("leader") == 2
assert squad_u.slot_capacity("support") == 1, "support must be untouched"
# a plain field on the datasheet does the same without an ability
squad["abilities"] = []
squad["leader_slots"] = 3
assert build(squad, boss1, boss2)[0].slot_capacity("leader") == 3
print("leader/support slots: default, ability-driven and datasheet-driven")

print("ALL STRUCTURAL TESTS PASS")
