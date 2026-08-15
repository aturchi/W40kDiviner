"""Characteristics of the INCOMING attack: defender-side modifiers, an
absolute AP on the critical-wound branch, and ability-granted cover.

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
import effect_specs as _es
import mc_support as mcs
from characteristics import Characteristic
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

# --- 5. the other incoming characteristics -----------------------------
# Strength: S8 vs T4 wounds on 2+; S4 vs T4 wounds on 4+.
w = weapon(ap=0, S=8)
close(dmg(w, mech_for(["CHARMOD S -4"])),
      4 * (2 / 3) * (3 / 6) * (3 / 6),
      "S8 lowered by 4 must wound like S4")
# Attacks: the characteristic modifier lands before the extra attacks,
# so RAPID FIRE 2 at half range still adds its 2 shots on top.
close(am.analyze_weapon(weapon(ap=0, A="4"), REF, CTX,
                        mech_for(["CHARMOD A -1"]))["attacks"]["mean"],
      3.0, "A4 lowered by 1")
# BS: the characteristic modifier is NOT capped with the roll modifiers,
# and it is clamped at 6+ at worst. BS3+ worsened by 2 hits on 5+.
close(dmg(weapon(ap=0, skill=3), mech_for(["CHARMOD SKILL +2"])),
      4 * (2 / 6) * (5 / 6) * (3 / 6), "BS3+ worsened by 2")
# Damage rides the existing damage chain (a modifier of -1 is dmg_add).
close(dmg(weapon(ap=0, D="3"), mech_for(["CHARMOD D -1"])),
      4 * (2 / 3) * (5 / 6) * (3 / 6) * 2, "D3 lowered by 1")
print("Strength, Attacks, BS/WS and Damage modifiers of an incoming attack")

# --- 6. ability-granted cover (11th-ed. Stealth) -----------------------
# Cover is a -1 BS penalty: BS3+ becomes 4+.
base = 4 * (2 / 3) * (5 / 6) * (3 / 6)
covered = 4 * (3 / 6) * (5 / 6) * (3 / 6)
close(dmg(weapon(ap=0), mech_for(["BENEFITOFCOVER"])), covered,
      "an ability granting cover costs the attacker one point of BS")
# it must NOT stack with the terrain cover of the attack setup
m = mech_for(["BENEFITOFCOVER"])
close(am.analyze_weapon(weapon(ap=0), REF, {"cover": True}, m)["damage"]["mean"],
      covered, "granted cover does not stack with terrain cover")
# IGNORES COVER cancels it, exactly as it cancels terrain cover
m = mech_for(["BENEFITOFCOVER"])
m.ignores_cover = True
close(am.analyze_weapon(weapon(ap=0), REF, CTX, m)["damage"]["mean"], base,
      "IGNORES COVER cancels the granted cover too")
# and it is a RANGED-only penalty
mel = Weapon(name="blade", wtype="Melee", A="4", skill=3, S=8, AP=0, D="1",
             count=1)
close(am.analyze_weapon(mel, REF, CTX,
                        mech_for(["BENEFITOFCOVER"]))["damage"]["mean"],
      base, "cover does not apply to melee attacks")
# cover is a STATE, not a counter: no combination of sources stacks
w = weapon(ap=0)
for label, ctx, effects in [
        ("attack setup only", {"cover": True}, []),
        ("ability only", {}, ["BENEFITOFCOVER"]),
        ("setup + ability", {"cover": True}, ["BENEFITOFCOVER"]),
        ("two abilities", {}, ["BENEFITOFCOVER", "BENEFITOFCOVER"])]:
    close(am.analyze_weapon(w, REF, ctx, mech_for(effects))["damage"]["mean"],
          covered, f"cover must never stack: {label}")
# INDIRECT FIRE also grants cover; combined with the others, still -1 BS
ind = mech_for(["BENEFITOFCOVER"])
ind.indirect = True
res = am.analyze_weapon(w, REF, {"cover": True, "indirect": True,
                                 "spotter": True}, ind)["damage"]["mean"]
# BS3+ -> 4+ from the single cover penalty, and an unmodified 1-3 fails
close(res, 4 * (3 / 6) * (5 / 6) * (3 / 6),
      "indirect fire adds its own cover without stacking")
print("no combination of cover sources ever stacks")

# --- 7. ignoring the BS/WS modifiers clears cover ----------------------
close(dmg(weapon(ap=0), mech_for(["BENEFITOFCOVER", "IGNOREMALUS SKILL"])),
      base, "'Skill' ignore-malus clears the cover penalty")
close(dmg(weapon(ap=0), mech_for(["BENEFITOFCOVER", "IGNOREMALUS HIT"])),
      covered, "'Hit' ignore-malus must NOT clear the cover penalty")
close(dmg(weapon(ap=0), mech_for(["CHARMOD SKILL +2", "IGNOREMALUS SKILL"])),
      base, "'Skill' ignore-malus clears an ability BS penalty too")
# a BS BONUS survives being "ignored": only the maluses go (BS3+ -> 2+)
close(dmg(weapon(ap=0), mech_for(["CHARMOD SKILL -1", "IGNOREMALUS SKILL"])),
      4 * (5 / 6) * (5 / 6) * (3 / 6), "a BS bonus survives ignore-malus")
print("ignore-malus on the BS/WS group behaves as expected")

for label, effects in [("strength modifier", ["CHARMOD S -3"]),
                       ("attacks modifier", ["CHARMOD A -1"]),
                       ("skill modifier", ["CHARMOD SKILL +1"]),
                       ("granted cover", ["BENEFITOFCOVER"])]:
    w = weapon(ap=-1, A="6", D="2")
    ok, msg = mcs.check_weapon(label, w, REF, CTX, mech_for(effects))
    assert ok, f"{label}: {msg}"
print("exact maths and dice resolver agree on the new modifiers too")

# --- 8. "you can re-roll the Damage roll" (no range given) -------------
# The datasheet gives no range, so the policy is to re-roll what a player
# would: strictly below the die's mean, i.e. 1..sides//2.
for spec, expected in (("D6", (1, 3)), ("D3", (1, 1)), ("2D6", (1, 3)),
                       ("3", None), ("D6+2", (1, 3))):
    got = am.damage_reroll_range(Characteristic(spec))
    assert got == expected, f"{spec}: got={got} expected={expected}"

w = Weapon(name="rr", wtype="Ranged", A="1", skill=2, S=10, AP=-4, D="D6",
           count=1)
REF_SOFT = {"T": 4, "Sv": 7, "W": 20, "invuln": None, "fnp": None,
            "models": 1, "keywords": set()}
plain = am.analyze_weapon(w, REF_SOFT, CTX, mech_for())["damage"]["mean"]
free = am.analyze_weapon(w, REF_SOFT, CTX,
                         mech_for(["REROLL DAMAGE FAILS"]))["damage"]["mean"]
ranged = am.analyze_weapon(w, REF_SOFT, CTX,
                           mech_for(["REROLL DAMAGE RANGE [1, 3]"])
                           )["damage"]["mean"]
close(free, ranged, "a free damage re-roll equals the 1-3 range on a D6")
assert free > plain, (free, plain)
# an explicit range still wins over the free form
both = mech_for(["REROLL DAMAGE FAILS", "REROLL DAMAGE RANGE [1, 1]"])
only = mech_for(["REROLL DAMAGE RANGE [1, 1]"])
close(am.analyze_weapon(w, REF_SOFT, CTX, both)["damage"]["mean"],
      am.analyze_weapon(w, REF_SOFT, CTX, only)["damage"]["mean"],
      "an explicit range takes precedence over the free re-roll")
# and a flat Damage characteristic is untouched
flat = Weapon(name="flat", wtype="Ranged", A="1", skill=2, S=10, AP=-4,
              D="2", count=1)
close(am.analyze_weapon(flat, REF_SOFT, CTX,
                        mech_for(["REROLL DAMAGE FAILS"]))["damage"]["mean"],
      am.analyze_weapon(flat, REF_SOFT, CTX, mech_for())["damage"]["mean"],
      "a flat Damage has no roll to re-roll")
ok, msg = mcs.check_weapon("free damage re-roll", w, REF_SOFT, CTX,
                           mech_for(["REROLL DAMAGE FAILS"]))
assert ok, msg
print("a free damage re-roll picks the die's losing half, dice included")

# --- 9. model profile characteristics (T / Sv / W) --------------------
# Abilities that change the DEFENDER's own profile, not the attack: a
# storm shield raising Wounds, a buff to Toughness, a better armour save.
import modifier_engine as _me                              # noqa: E402
assert _me._MODEL_ATTRS["t"] == "T"
assert _me._MODEL_ATTRS["sv"] == "Sv"
assert _me._MODEL_ATTRS["w"] == "W"
# "Improve by 1" goes the right way for each: T and W up, Sv down.
assert _me._MODEL_IMPROVE_SIGN["T"] == +1
assert _me._MODEL_IMPROVE_SIGN["W"] == +1
assert _me._MODEL_IMPROVE_SIGN["Sv"] == -1
_apps = dict(_es.EFFECT_SPECS["modifyAbsolute"]["fields"][0][3])
for _label in ("Toughness (T)", "Save (Sv)", "Wounds (W)"):
    assert _label in _apps, f"{_label} missing from the editor vocabulary"
print("T, Sv and W can be modified by an ability")
