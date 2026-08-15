"""AP of the incoming attack: defender-side modifier, and an absolute AP
on the critical-wound branch.

  * A defender ability may worsen (or improve) the Armour Penetration
    characteristic of every attack that targets its unit. Since it acts
    on the attack, not on our weapons, it is exported as a unit-level
    effect string ("CHARMOD AP +1") and folded into the weapon
    mechanics at resolution time. The absolute limit still applies: AP
    can never be worsened past 0.
  * An attacker ability may SET the AP on a Critical Wound ("that attack
    has an Armour Penetration characteristic of -3"). That is an
    absolute value, not the improving delta that crit_ap_delta models,
    and it takes precedence over it.

Both are checked in closed form against the exact maths and cross-checked
with the dice resolver. No tkinter needed.
"""
import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
import mc_support as mcs
from unit_model import Weapon

TOL = 1e-9
CTX = {}
# Sv4+, T4, no invulnerable: every save probability below is exact.
REF = {"T": 4, "Sv": 4, "W": 3, "invuln": None, "fnp": None, "models": 1,
       "keywords": set()}


def close(a, b, what):
    assert abs(a - b) < TOL, f"{what}: got={a!r} expected={b!r}"


def weapon(ap=-1, skill=3, A="4", S=8, D="1"):
    return Weapon(name="test gun", wtype="Ranged", A=A, skill=skill, S=S,
                  AP=ap, D=D, count=1)


def mech_for(effects=()):
    m = am.WeaponMechanics()
    am.parse_effect_strings(list(effects), "Ranged", m, None)
    assert not m.warnings, m.warnings
    return m


def dmg(w, mech):
    return am.analyze_weapon(w, REF, CTX, mech)["damage"]["mean"]


# --- 1. the effect strings parse -------------------------------------
close(mech_for(["CHARMOD AP +1"]).ap_mod, 1, "defender AP modifier")
close(mech_for(["IF RANGED_ATTACK: CHARMOD AP +1"]).ap_mod, 1,
      "AP modifier restricted to ranged attacks")
close(mech_for(["IF MELEE_ATTACK: CHARMOD AP +1"]).ap_mod, 0,
      "a melee-only AP modifier must not touch a ranged attack")
assert mech_for(["IF CRIT_WOUND: CHARSET AP -3"]).crit_ap_set == -3
# the strongest absolute value wins when two abilities set it
assert mech_for(["IF CRIT_WOUND: CHARSET AP -2",
                 "IF CRIT_WOUND: CHARSET AP -3"]).crit_ap_set == -3
print("AP effect strings parse (defender modifier, critical-wound set)")

# --- 2. the defender modifier is exactly one point of AP -------------
# A4, BS3+ -> 4*2/3 hits; S8 vs T4 -> wound on 2+ (5/6); Sv4+ with AP-1
# saves on 5+ (2/6 -> 4/6 unsaved), with AP0 on 4+ (3/6 -> 3/6 unsaved).
w = weapon(ap=-1)
expected_ap1 = 4 * (2 / 3) * (5 / 6) * (4 / 6)
expected_ap0 = 4 * (2 / 3) * (5 / 6) * (3 / 6)
close(dmg(w, mech_for()), expected_ap1, "AP-1 baseline")
close(dmg(w, mech_for(["CHARMOD AP +1"])), expected_ap0,
      "AP-1 worsened by 1 must behave exactly like AP 0")
# and it cannot be worsened past 0 (absolute characteristic limit)
close(dmg(w, mech_for(["CHARMOD AP +3"])), expected_ap0,
      "AP is clamped at 0, never worse")
# it works the other way round too: an ability improving the incoming AP
close(dmg(weapon(ap=0), mech_for(["CHARMOD AP -1"])), expected_ap1,
      "AP 0 improved by 1 must behave exactly like AP-1")
print("the defender AP modifier is worth exactly one point of AP")

# --- 3. absolute AP on a critical wound ------------------------------
# S8 vs T4: wound on 2+, critical wound on an unmodified 6 -> 1/6 of the
# hits take the critical branch, the other 4/6 the normal one.
hits = 4 * (2 / 3)
p_crit, p_norm = 1 / 6, 4 / 6
# AP0 normally (save 4+ -> 3/6 unsaved), AP-3 on the crit branch (7+ ->
# impossible -> 6/6 unsaved)
expected = hits * (p_norm * (3 / 6) + p_crit * (6 / 6))
close(dmg(weapon(ap=0), mech_for(["IF CRIT_WOUND: CHARSET AP -3"])),
      expected, "AP set to -3 on a critical wound")
# an absolute set wins over the improving delta
both = mech_for(["IF CRIT_WOUND: CHARSET AP -3",
                 "IF CRIT_WOUND: CHARMOD AP -1"])
close(dmg(weapon(ap=0), both), expected,
      "CHARSET AP takes precedence over CHARMOD AP on the crit branch")
# the defender modifier applies on top of the set value: -3 +1 = -2,
# Sv4+ -> save on 6+ -> 5/6 unsaved
expected_def = hits * (p_norm * (3 / 6) + p_crit * (5 / 6))
close(dmg(weapon(ap=0), mech_for(["IF CRIT_WOUND: CHARSET AP -3",
                                  "CHARMOD AP +1"])),
      expected_def, "the defender AP modifier applies after the crit set")
print("an absolute AP on a critical wound behaves as expected")

# --- 4. the dice resolver agrees --------------------------------------
for label, ap, effects in [
        ("defender AP modifier", -2, ["CHARMOD AP +1"]),
        ("AP clamped at 0", -1, ["CHARMOD AP +2"]),
        ("critical-wound AP set", 0, ["IF CRIT_WOUND: CHARSET AP -3"]),
        ("crit set + defender modifier", 0,
         ["IF CRIT_WOUND: CHARSET AP -3", "CHARMOD AP +1"])]:
    w = weapon(ap=ap, A="6", D="2")
    ok, msg = mcs.check_weapon(label, w, REF, CTX, mech_for(effects))
    assert ok, f"{label}: {msg}"
print("exact maths and dice resolver agree on every AP configuration")
