"""Choices the player has to make, and the warnings that check them.

Two mechanisms, both about abilities the ENGINE cannot resolve on its
own: one re-roll per ACTIVATION (Targeting Array, Aquilon Optics), and
the generic "select one of the following" group (Nova Charge, the
Bladeguard stances).

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

# --- 5. the generic "select one of the following" groups --------------
# The same problem outside the re-roll case: a datasheet that says
# "select one weapon" or "select one of the following" is modelled as
# several switched-off copies, all labelled with the same
# 'exclusive_group'. Nothing stops the player ticking two, so the
# analysis counts them.
def grouped(picks, group="Nova Charge"):
    """A two-weapon unit whose weapons each carry a copy of one choice."""
    weapons = []
    for wname in ("big gun", "small gun"):
        weapons.append(
            {"name": wname, "type": "Ranged", "RNG": 24, "A": 2, "BS": 3,
             "S": 5, "AP": -1, "D": 1, "count": 1, "keywords": [],
             "abilities": [{
                 "name": group, "description": "", "enabled": wname in picks,
                 "share_with_unit": False, "exclusive_group": group,
                 "conditions": [], "effect": {
                     "type": "setKeyword", "data": {
                         "target": {"title": "This weapon", "key": "weapon"},
                         "operation": {"title": "Add", "key": "add"},
                         "keyword": "DEVASTATING WOUNDS"}}}]})
    data = {"format": "w40k-sim/6", "armies": [{"name": "T", "units": [{
        "name": "U", "profile_name": "U", "points": 10,
        "keywords": ["Vehicle"], "abilities": [], "core_abilities": [],
        "faction_abilities": [], "leadership": [], "support": [],
        "leader_effects": [], "apply_leader_effects_to_self": False,
        "damageable": False, "unit_composition": "", "wargear_options": "",
        "notes": "", "models": [{
            "name": "M", "model_count": 1, "M": 6, "T": 5, "Sv": 3,
            "W": 6, "LD": 6, "OC": 1, "invuln": None, "fnp": None,
            "keywords": [], "abilities": [], "weapons": weapons}]}]}]}
    unit = um.units_from_native(data)[0]
    aview, _d = ac.build_views(unit, unit, {})
    return ac.exclusive_group_notes(aview)


assert grouped(set()) == [], "nothing chosen is not an error"
assert grouped({"big gun"}) == [], "one choice is the normal case"
two = grouped({"big gun", "small gun"})
assert len(two) == 1 and "only ONE" in two[0], two
# the message must say WHICH copies are on - they share a name and
# differ only by the weapon
assert "big gun" in two[0] and "small gun" in two[0], two
print("the exclusive-group warning names the choices that are on")

# --- 6. "re-roll a Damage roll of N" ----------------------------------
# The ability editor offers "Single result" for the Damage application
# too, and it used to come out as an unsupported effect: only the range
# form was parsed. A single value is just the one-element range.
m = am.WeaponMechanics()
am.parse_effect_strings(["REROLL DAMAGE 1"], "Ranged", m, None)
assert not m.warnings, m.warnings
assert m.dmg_reroll == (1, 1), m.dmg_reroll
m2 = am.WeaponMechanics()
am.parse_effect_strings(["REROLL DAMAGE RANGE [1, 1]"], "Ranged", m2, None)
assert m2.dmg_reroll == m.dmg_reroll, "both forms must agree"
# and it does raise the damage of a dice-damage weapon
wd = Weapon(name="lance", wtype="Ranged", A="1", skill=2, S=12, AP=-4,
            D="D6", count=1)
soft = {"T": 4, "Sv": 7, "W": 20, "invuln": None, "fnp": None,
        "models": 1, "keywords": set()}
assert am.analyze_weapon(wd, soft, {}, m)["damage"]["mean"] > \
    am.analyze_weapon(wd, soft, {}, am.WeaponMechanics())["damage"]["mean"]
print("a single-value damage re-roll is the one-element range")

# --- 7. whose keywords a keyword condition reads ----------------------
# "While this model is leading a BLOOD CLAWS unit" asks about the
# ATTACKING unit, not the target. The keyword conditions take a 'who'
# field for that; it defaults to the target, which is what every
# condition written before the field meant.
import condition_specs as _cs                             # noqa: E402
import modifier_engine as _me2                            # noqa: E402

assert dict(_cs.CONDITION_SPECS["keywordsOnly"]["fields"][1][3])[
    "Target unit"] == "target"
assert _cs.new_condition("keywordsOnly")["data"]["who"]["key"] == "target", \
    "the default must stay 'target' for backward compatibility"


class _Side:
    def __init__(self, kws):
        self.keywords = kws


env = _me2.Env(_Side(["BLOOD CLAWS", "INFANTRY"]), _Side(["VEHICLE"]),
               _me2.Context(), "attacker")
only = _me2.CONDITION_EVALUATORS["keywordsOnly"]
excl = _me2.CONDITION_EVALUATORS["keywordsExcludes"]
# no 'who' at all: the target, as before
assert only({"keywords": ["VEHICLE"]}, env) is True
assert only({"keywords": ["BLOOD CLAWS"]}, env) is False
# who = self: the attacking unit
assert only({"keywords": ["BLOOD CLAWS"], "who": "self"}, env) is True
assert only({"keywords": ["VEHICLE"], "who": "self"}, env) is False
# and the same for the excluding form
assert excl({"keywords": ["VEHICLE"]}, env) is False
assert excl({"keywords": ["VEHICLE"], "who": "self"}, env) is True
print("keyword conditions can read the attacker's own keywords")

print("ALL PLAYER-CHOICE TESTS PASS")
