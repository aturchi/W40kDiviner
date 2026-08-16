"""One re-roll per ACTIVATION (Targeting Array, Aquilon Optics).

The datasheet gives the unit ONE re-roll for the whole activation, not
one per attack. Modelled exactly: with n attacks and a per-die failure
probability pf, at least one die failed with probability 1-(1-pf)^n, and
the player spends the re-roll on it - which adds one fresh outcome (a
whole attack for a hit re-roll, a wound roll onwards for a wound one).

The subtle part is the CORRELATION: the extra die lands only on the
sequences where something failed, and those are also the sequences with
the least damage. Treating the two as independent gets the mean right
and the distribution wrong, so the maths splits on that event - and this
test pins it down against the dice resolver, which is the only way to
tell the two apart.

The rule is per activation while the analyzer works weapon by weapon, so
the ability goes on ONE weapon (a switched-off copy sits on the others).
analyzer_core.single_reroll_notes counts what is on and says what is
wrong; the second half of this test covers that.
"""
import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import attack_math as am
import mc_support as mcs
import unit_model as um
from unit_model import Weapon

REF = {"T": 4, "Sv": 3, "W": 10, "invuln": None, "fnp": None,
       "models": 1, "keywords": set()}
TOL = 1e-9


def mech_for(effects=()):
    m = am.WeaponMechanics()
    am.parse_effect_strings(list(effects), "Ranged", m, None)
    assert not m.warnings, m.warnings
    return m


def weapon(a="4", skill=3, s=8, ap=-2, d="2"):
    return Weapon(name="gun", wtype="Ranged", A=a, skill=skill, S=s, AP=ap,
                  D=d, count=1)


def mean(w, effects):
    return am.analyze_weapon(w, REF, {}, mech_for(effects))["damage"]["mean"]


# --- 1. the effect strings parse --------------------------------------
assert mech_for(["REROLL ONE HIT_ROLL"]).single_reroll == "hit"
assert mech_for(["REROLL ONE WOUND_ROLL"]).single_reroll == "wound"
# and it is NOT the per-attack re-roll
assert mech_for(["REROLL ONE HIT_ROLL"]).reroll_hit is None
print("the single re-roll parses and is not a per-attack re-roll")

# --- 2. it sits between nothing and a full re-roll --------------------
w = weapon()
base = mean(w, [])
one_hit = mean(w, ["REROLL ONE HIT_ROLL"])
all_hit = mean(w, ["REROLL HIT_ROLL FAILS"])
assert base < one_hit < all_hit, (base, one_hit, all_hit)
one_wound = mean(w, ["REROLL ONE WOUND_ROLL"])
all_wound = mean(w, ["REROLL WOUND_ROLL FAILS"])
assert base < one_wound < all_wound, (base, one_wound, all_wound)
# With a single attack there is nothing else to gain from, so one
# re-roll and a full re-roll must agree exactly.
w1 = weapon(a="1")
assert abs(am.analyze_weapon(w1, REF, {}, mech_for(["REROLL ONE HIT_ROLL"])
                             )["damage"]["mean"]
           - am.analyze_weapon(w1, REF, {},
                               mech_for(["REROLL HIT_ROLL FAILS"])
                               )["damage"]["mean"]) < TOL, \
    "with one attack, one re-roll IS the full re-roll"
print("one re-roll sits between no re-roll and a full one")

# --- 3. the dice resolver agrees, shape included ----------------------
for label, a, effects in [("hit, 4 attacks", "4", ["REROLL ONE HIT_ROLL"]),
                          ("wound, 4 attacks", "4",
                           ["REROLL ONE WOUND_ROLL"]),
                          ("hit, 1 attack", "1", ["REROLL ONE HIT_ROLL"]),
                          ("hit, D6 attacks", "D6",
                           ["REROLL ONE HIT_ROLL"]),
                          ("wound, D6 attacks", "D6",
                           ["REROLL ONE WOUND_ROLL"])]:
    ok, msg = mcs.check_weapon(label, weapon(a=a), REF, {},
                               mech_for(effects))
    assert ok, msg
print("exact maths and dice resolver agree, distribution included")

# --- 4. the warnings that count what the player switched on -----------
ROLLS = {"hit": "Hit roll", "wound": "Wound roll"}


def ability(name, roll, allowance, enabled):
    return {"name": f"{name} [{roll} roll]", "description": "",
            "enabled": enabled, "share_with_unit": False,
            "conditions": [], "effect": {
                "type": "singleReRoll", "data": {
                    "roll": {"title": ROLLS[roll], "key": roll},
                    "allowance": {"title": allowance,
                                  "key": allowance}}}}


def roster(picks, allowance):
    """A two-weapon unit carrying a copy of the ability per weapon and
    per kind; 'picks' is the set of (weapon, kind) switched on."""
    weapons = []
    for wname in ("big gun", "small gun"):
        weapons.append(
            {"name": wname, "type": "Ranged", "RNG": 24, "A": 2, "BS": 3,
             "S": 5, "AP": -1, "D": 1, "count": 1, "keywords": [],
             "abilities": [ability("Targeting Array", kind, allowance,
                                   (wname, kind) in picks)
                           for kind in ("hit", "wound")]})
    return {"format": "w40k-sim/6", "armies": [{"name": "T", "units": [{
        "name": "U", "profile_name": "U", "points": 10,
        "keywords": ["Vehicle"], "abilities": [], "core_abilities": [],
        "faction_abilities": [], "leadership": [], "support": [],
        "leader_effects": [], "apply_leader_effects_to_self": False,
        "damageable": False, "unit_composition": "", "wargear_options": "",
        "notes": "", "models": [{
            "name": "M", "model_count": 1, "M": 6, "T": 5, "Sv": 3,
            "W": 6, "LD": 6, "OC": 1, "invuln": None, "fnp": None,
            "keywords": [], "abilities": [], "weapons": weapons}]}]}]}


def notes(picks, allowance):
    unit = um.units_from_native(roster(picks, allowance))[0]
    aview, _d = ac.build_views(unit, unit, {})
    return ac.single_reroll_notes(aview)


# 'exclusive' (hit OR wound): one is fine, two is not - of either kind.
assert notes(set(), "exclusive") == []
assert notes({("big gun", "hit")}, "exclusive") == []
assert notes({("big gun", "wound")}, "exclusive") == []
two = notes({("big gun", "hit"), ("small gun", "hit")}, "exclusive")
assert len(two) == 1 and "only ONE" in two[0], two
mixed = notes({("big gun", "hit"), ("big gun", "wound")}, "exclusive")
assert len(mixed) == 1 and "only ONE" in mixed[0], mixed
assert "1x hit" in mixed[0] and "1x wound" in mixed[0], mixed

# 'eachKind' (hit AND wound): one of each, and the reminder when the
# player used one kind and forgot the other.
assert notes(set(), "eachKind") == [], "silence when the ability is unused"
one = notes({("big gun", "hit")}, "eachKind")
assert len(one) == 1 and "wound-roll" in one[0] and "EACH kind" in one[0], one
assert notes({("big gun", "hit"), ("small gun", "wound")},
             "eachKind") == [], "one of each kind is correct"
dup = notes({("big gun", "hit"), ("small gun", "hit")}, "eachKind")
assert len(dup) == 2, dup            # too many hits + no wound at all
assert any("2 hit-roll re-rolls" in n for n in dup), dup
print("the warnings count each kind across the unit's weapons")

print("ALL SINGLE RE-ROLL TESTS PASS")
