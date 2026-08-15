"""setKeyword: scope of the target, and dynamic conditions.

Three behaviours the modifier engine must guarantee:
  * "This weapon" is resolved in the per-weapon pass, so a condition on
    the attack type is decided against the real weapon (a melee-only
    grant lands on melee weapons only). It used to be dropped entirely,
    because the whole effect type was skipped in that pass.
  * "All weapons" / "Unit" are resolved ONCE, in the weapon-free pass, so
    they are not re-applied per weapon.
  * A ROLL-TIME condition (a critical hit, a specific roll) cannot gate a
    keyword: the keyword is read once, when the mechanics are built. Such
    an ability must NOT be applied silently as if unconditional - it is
    exported as a string and reported as unsupported.

No tkinter needed.
"""
import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
import modifier_engine as me
import unit_model as um


def roster(conditions):
    """One two-weapon unit carrying a setKeyword ability with the given
    conditions and target."""
    return {"format": "w40k-sim/6", "armies": [{"name": "T", "units": [{
        "name": "U", "profile_name": "U", "points": 10,
        "keywords": ["Infantry"], "abilities": conditions,
        "core_abilities": [], "faction_abilities": [], "leadership": [],
        "support": [], "leader_effects": [],
        "apply_leader_effects_to_self": False, "damageable": False,
        "unit_composition": "", "wargear_options": "", "notes": "",
        "models": [{"name": "M", "model_count": 1, "M": 6, "T": 4, "Sv": 3,
                    "W": 2, "LD": 6, "OC": 1, "invuln": None, "fnp": None,
                    "keywords": [], "abilities": [], "weapons": [
                        {"name": "gun", "type": "Ranged", "RNG": 24, "A": 2,
                         "BS": 3, "S": 4, "AP": 0, "D": 1, "count": 1,
                         "keywords": [], "abilities": []},
                        {"name": "blade", "type": "Melee", "RNG": None,
                         "A": 3, "WS": 3, "S": 5, "AP": -1, "D": 1,
                         "count": 1, "keywords": [], "abilities": []}]}]}]}]}


def ability(target, conditions):
    return {"name": "grant", "description": "", "enabled": True,
            "share_with_unit": False, "conditions": conditions,
            "effect": {"type": "setKeyword", "data": {
                "target": {"title": target[0], "key": target[1]},
                "operation": {"title": "Add", "key": "add"},
                "keyword": "LETHAL HITS"}}}


MELEE_ONLY = [{"text": "Attack type", "type": "attackType",
               "data": {"attackType": "Melee"}, "description": "",
               "preselected": False}]
ON_CRIT = [{"text": "Critical hit/wound", "type": "crit",
            "data": {"crit": {"title": "Critical hit", "key": "hitRoll"}},
            "description": "", "preselected": False}]


def view(target, conditions):
    data = roster([ability(target, conditions)])
    unit = um.units_from_native(data)[0]
    return me.build_view(unit, None, me.Context(), role="attacker")


def keywords_of(v):
    return {w.name: {str(k).upper() for k in w.keywords}
            for m in v.models() for w in m.weapons}


# --- 1. "This weapon" + a static condition: per-weapon resolution -----
kws = keywords_of(view(("This weapon", "weapon"), MELEE_ONLY))
assert "LETHAL HITS" in kws["blade"], "melee-only grant lost on the melee weapon"
assert "LETHAL HITS" not in kws["gun"], "melee-only grant leaked onto a ranged weapon"

# --- 2. "All weapons", unconditional: every weapon, exactly once ------
kws = keywords_of(view(("All weapons", "allWeapons"), []))
assert all("LETHAL HITS" in k for k in kws.values()), "allWeapons did not reach every weapon"
assert all(sum(1 for x in k if x == "LETHAL HITS") == 1 for k in kws.values()), \
    "allWeapons applied more than once"

# --- 3. a roll-time condition must NOT be applied silently -----------
v = view(("All weapons", "allWeapons"), ON_CRIT)
kws = keywords_of(v)
assert not any("LETHAL HITS" in k for k in kws.values()), \
    "a keyword gated on a critical hit was applied unconditionally"
strings = list(v.effects) + [e for m in v.models() for w in m.weapons
                             for e in w.effects]
assert any("KEYWORD ADD LETHAL HITS" in s for s in strings), \
    "the conditional keyword was dropped without a trace"
mech = am.WeaponMechanics()
am.parse_effect_strings(strings, "Ranged", mech, None)
assert not mech.lethal, "the conditional keyword reached the mechanics"
assert mech.warnings, "the conditional keyword must be reported as unsupported"

print("ALL setKeyword SCOPE TESTS PASS")
