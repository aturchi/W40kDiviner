"""Attack-setup ability selection (11th ed.: several weapon abilities are
optional, "you can").

  * abilities can be switched OFF one by one (the datasheet keyword is
    parsed, then the selection removes it);
  * extra abilities can be given to EVERY attack;
  * with 'optimise' on, the one genuine mid-sequence choice is taken on
    the better side and reported: LETHAL HITS is optional, and using it
    turns a critical hit into an ordinary automatic wound, which loses
    damage when the weapon also has Anti-X or Devastating Wounds;
  * with 'optimise' off the selection is followed literally, so Lethal
    Hits wins and Devastating Wounds never triggers;
  * FNP: no cap on its modifier (like a saving throw) and no stacking -
    the best value wins when several sources grant it.
No tkinter needed.
"""
import copy

import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import attack_math as am
import native_format as nf
import unit_model as um
from unit_model import Weapon

TOL = 1e-9
REF = {"T": 4, "Sv": 3, "W": 1, "invuln": None, "fnp": None, "models": 1,
       "keywords": {"VEHICLE"}}


def close(a, b, what):
    assert abs(a - b) < TOL, f"{what}: got={a!r} expected={b!r}"


def mech_from(kws, extra=None, disabled=None):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(list(kws), m)
    am.add_abilities(m, extra)
    am.disable_abilities(m, disabled, lambda msg: m.warnings.append(msg))
    return m


# --- switching abilities off ------------------------------------------
m = mech_from(["LETHAL HITS", "SUSTAINED HITS 2", "ANTI-VEHICLE 4+",
               "TWIN-LINKED"],
              disabled=["LETHAL HITS", "SUSTAINED HITS", "ANTI"])
assert not m.lethal and m.sustained == 0 and m.anti == []
assert m.twin_linked, "untouched abilities must survive"
assert not m.warnings, m.warnings
# an unknown name is reported, not swallowed
m2 = mech_from([], disabled=["NOT AN ABILITY"])
assert m2.warnings and "NOT AN ABILITY" in m2.warnings[0]
print("abilities can be switched off by datasheet name")

# --- extras are given to every attack ---------------------------------
m3 = mech_from([], extra=["LETHAL HITS", "SUSTAINED HITS 1", "MELTA 2"])
assert m3.lethal and m3.sustained == 1 and m3.melta == 2
# ...and can then be switched off like any other
m4 = mech_from([], extra=["LETHAL HITS"], disabled=["LETHAL HITS"])
assert not m4.lethal
print("extra abilities apply to every attack and remain switchable")

# --- the DISABLE effect string is now consumed, not warned about ------
m5 = am.WeaponMechanics()
am.parse_weapon_keywords(["LETHAL HITS"], m5)
am.parse_effect_strings(["DISABLE LETHAL HITS"], "Ranged", m5, None)
assert not m5.lethal and not m5.warnings, (m5.lethal, m5.warnings)
print("disableMechanic's DISABLE effect reaches the maths")

# --- optimise: Lethal Hits declined when it costs damage --------------
W = Weapon(name="w", wtype="Ranged", A="6", skill=3, S=8, AP=0, D="1",
           count=1)
both = mech_from(["LETHAL HITS", "DEVASTATING WOUNDS", "ANTI-VEHICLE 4+"])
literal = am.analyze_weapon(W, REF, {}, both.copy())["damage"]["mean"]
best, note = am.analyze_weapon_best(W, REF, {}, both.copy())
assert note and "LETHAL HITS declined" in note, note
assert best["damage"]["mean"] > literal, (best["damage"]["mean"], literal)
# closed form: 6 attacks, BS3+ (2/3 hit, 1/6 critical), S8 vs T4 wounds
# on 2+, Anti-VEHICLE 4+ makes 4,5,6 critical wounds, 3+ save.
A, P_HIT, P_CRIT, Q_W, Q_CRIT, UNSAVED = 6, 2 / 3, 1 / 6, 5 / 6, 3 / 6, 1 / 3
close(best["damage"]["mean"],
      A * P_HIT * ((Q_W - Q_CRIT) * UNSAVED + Q_CRIT), "lethal declined")
close(literal, A * ((P_HIT - P_CRIT) * ((Q_W - Q_CRIT) * UNSAVED + Q_CRIT)
                    + P_CRIT * UNSAVED), "lethal used literally")
# when Lethal is the better side, nothing is declined
plain = mech_from(["LETHAL HITS"])
res, note = am.analyze_weapon_best(W, REF, {}, plain.copy())
assert note is None
close(res["damage"]["mean"],
      am.analyze_weapon(W, REF, {}, plain.copy())["damage"]["mean"],
      "lethal kept")
print("optimise declines Lethal Hits only when it is worth more")

# --- the flags dict carries the selection -----------------------------
sel = ac.ability_selection({"extra_abilities": ["TWIN-LINKED"],
                            "disabled_abilities": ["LETHAL HITS"],
                            "optimise_abilities": False})
assert sel == {"extra": ["TWIN-LINKED"], "disabled": ["LETHAL HITS"],
               "optimise": False}, sel
assert ac.ability_selection({})["optimise"] is True, "optimise defaults on"
print("the attack setup selection travels in the flags dict")

# --- FNP: no cap on the modifier, and no stacking ---------------------
FNP_REF = dict(REF, Sv=6, fnp=4)
WF = Weapon(name="f", wtype="Ranged", A="6", skill=2, S=10, AP=-6, D="1",
            count=1)


def fnp_dmg(mod):
    m = am.WeaponMechanics()
    m.fnp_mod = mod
    return am.analyze_weapon(WF, FNP_REF, {}, m)["damage"]["mean"]


assert fnp_dmg(2) < fnp_dmg(1) < fnp_dmg(0), "the FNP modifier is not capped"
# ...bounded only by "an unmodified 1 always fails"
close(fnp_dmg(3), fnp_dmg(2), "FNP cannot go better than 2+")


def _unit(fnp_values, datasheet_fnp=None):
    abil = [{"name": f"A{i}", "enabled": True,
             "effect": {"type": "feelNoPain", "data": {"value": v}}}
            for i, v in enumerate(fnp_values)]
    u = {"name": "U", "profile_name": "U", "points": 10, "keywords": [],
         "abilities": abil, "core_abilities": [], "faction_abilities": [],
         "leadership": [], "support": [], "leader_effects": [],
         "apply_leader_effects_to_self": False, "damageable": False,
         "unit_composition": "", "wargear_options": "", "notes": "",
         "models": [{"name": "m", "model_count": 1, "M": 6, "T": 4, "Sv": 3,
                     "W": 2, "LD": 6, "OC": 1, "invuln": None,
                     "fnp": datasheet_fnp, "keywords": [], "abilities": [],
                     "weapons": []}]}
    data = nf.migrate({"format": "w40k-sim/6",
                       "armies": [{"name": "a", "units": [copy.deepcopy(u)]}]})
    view = um.units_from_native(data)[0].against(None, {}, role="defender")
    return [mv.fnp for mv in view.models()]


assert _unit([6, 5]) == [5], "two FNP sources: the best one wins"
assert _unit([6], datasheet_fnp=5) == [5], "datasheet FNP is not overwritten"
assert _unit([4], datasheet_fnp=5) == [4], "a better ability FNP wins"
print("FNP: uncapped modifier, best value wins, no stacking")

print("ALL ABILITY-SELECTION TESTS PASS")
