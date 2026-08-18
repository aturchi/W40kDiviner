"""The three ability-plumbing gaps the regression harness exposed.

1. generateExtras "extra hits" / "extra wounds" / "extra attacks":
   modifier_engine emitted EXTRA_HITS / EXTRA_WOUNDS / EXTRA_ATTACKS but
   no engine consumed them, so those abilities silently did nothing.
   Only the CRITICAL-hit form (SUSTAINED HITS) worked.
2. psychicAttack on the DEFENDER side: the condition reads the weapon in
   scope, and a defender view has no incoming weapon, so a "only against
   Psychic attacks" ability never fired. It is now deferred to the
   attack maths, where the attacking weapon is known.
3. invulnSave with a weapon-scope condition: invulnSave is applied at
   model scope, so the conditional form was exported as an effect string
   that nothing read. SETINVULN now grants an invulnerable save for the
   attack (best value wins, no stacking), mirroring Feel No Pain.

Expected values are written in closed form by hand; each mechanic is
also cross-checked against the dice resolver. No tkinter needed.
"""
import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
import mc_support as mcs
import modifier_engine as me
from unit_model import Weapon

TOL = 1e-9


def close(a, b, what):
    assert abs(a - b) < TOL, f"{what}: got={a!r} expected={b!r}"


def weapon(name="probe gun", A="4", skill=3, S=8, AP=0, D="1", count=1,
           kws=()):
    w = Weapon(name=name, wtype="Ranged", A=A, skill=skill, S=S, AP=AP,
               D=D, count=count)
    w.keywords = list(kws)
    return w


def mech_for(w, effects=(), warn_ok=False):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(w.keywords, m)
    am.parse_effect_strings(list(effects), "Ranged", m, w)
    if not warn_ok:
        assert not m.warnings, m.warnings
    return m


def dmg(w, ref, effects=(), ctx=None):
    """Mean total Damage of one weapon against a reference defender."""
    m = mech_for(w, effects)
    return am.analyze_weapon(w, ref, ctx or {}, m)["damage"]["mean"]


# A defenceless target: no save, no invuln, no FNP, 1 wound. Every
# unsaved wound is exactly 1 damage, so the mean damage IS the expected
# number of scored wounds -- which makes the closed forms readable.
NAKED = {"T": 4, "Sv": None, "W": 1, "invuln": None, "fnp": None,
         "models": 1, "keywords": set()}
P_HIT = 2 / 3                  # BS 3+
Q_W = 5 / 6                    # S8 vs T4 -> 2+
A = 4


# --- 1a. EXTRA HITS ----------------------------------------------------
# Every successful hit yields X more. Bonus hits are hits, not hit rolls:
# they are never critical and generate no extras of their own, exactly
# like the bonus hits of SUSTAINED HITS.
w = weapon()
base = dmg(w, NAKED)
close(base, A * P_HIT * Q_W, "baseline damage")

one = dmg(w, NAKED, ["EXTRA_HITS 1"])
close(one, A * P_HIT * 2 * Q_W, "EXTRA_HITS 1 doubles the hits")
two = dmg(w, NAKED, ["EXTRA_HITS 2"])
close(two, A * P_HIT * 3 * Q_W, "EXTRA_HITS 2 triples them")

# and it must NOT behave like SUSTAINED HITS, which only fires on a 6
sus = dmg(w, NAKED, ["IF CRIT_HIT: EXTRA_HITS 1"])
close(sus, A * (P_HIT + 1 / 6) * Q_W, "SUSTAINED HITS: bonus on a 6 only")
assert one > sus, "extra hits on every hit must beat extra hits on a 6"
print("EXTRA HITS: every hit yields the bonus, criticals aside")

# the two stack: a critical hit gets both bonuses
both = dmg(w, NAKED, ["EXTRA_HITS 1", "IF CRIT_HIT: EXTRA_HITS 1"])
close(both, A * (P_HIT * 2 + 1 / 6) * Q_W,
      "EXTRA HITS and SUSTAINED HITS stack")

# a dice-valued X is a mixture, not its average: the mean matches the
# equivalent flat value but the distribution does not.
d3 = am.analyze_weapon(weapon(), NAKED, {},
                       mech_for(weapon(), ["EXTRA_HITS D3"]))
flat2 = am.analyze_weapon(weapon(), NAKED, {},
                          mech_for(weapon(), ["EXTRA_HITS 2"]))
close(d3["damage"]["mean"], flat2["damage"]["mean"], "D3 extra hits, mean")
assert d3["damage_pmf"] != flat2["damage_pmf"], \
    "a dice-valued X must not collapse to its average distribution"
print("EXTRA HITS: dice-valued X is mixed over, not averaged")


# --- 1b. EXTRA WOUNDS --------------------------------------------------
# A scored wound yields X more. They are not rolled, so they are always
# NORMAL wounds -- including the ones a critical wound generated.
one_w = dmg(w, NAKED, ["EXTRA_WOUNDS 1"])
close(one_w, A * P_HIT * Q_W * 2, "EXTRA_WOUNDS 1 doubles the wounds")

# they multiply with extra hits (both are per-event bonuses)
mixed = dmg(w, NAKED, ["EXTRA_HITS 1", "EXTRA_WOUNDS 1"])
close(mixed, A * P_HIT * 2 * Q_W * 2, "extra hits x extra wounds")
print("EXTRA WOUNDS: every scored wound yields the bonus")

# bonus wounds are NEVER critical: with DEVASTATING WOUNDS the extra
# wound must go through the save, not become a mortal wound. Against a
# 2+ save the difference is large and unmistakable.
ARMOURED = dict(NAKED, Sv=2)
dev = weapon(kws=["DEVASTATING WOUNDS"])
dev_base = dmg(dev, ARMOURED)
dev_extra = dmg(dev, ARMOURED, ["EXTRA_WOUNDS 1"])
p_crit = 1 / 6                              # critical wound on a 6
p_norm = Q_W - p_crit
p_unsaved = 1 / 6                           # Sv 2+, AP 0
close(dev_base, A * P_HIT * (p_norm * p_unsaved + p_crit),
      "DEVASTATING baseline")
close(dev_extra,
      A * P_HIT * (p_norm * p_unsaved * 2 + p_crit + p_crit * p_unsaved),
      "the extra wound of a critical wound is a NORMAL wound")
print("EXTRA WOUNDS: bonus wounds are normal, never critical")

# ...and the critical-only form, the wound-stage counterpart of
# SUSTAINED HITS. Against the naked target every wound is 1 damage, so
# the closed form is simply "one extra per critical wound".
crit_only = ["IF CRIT_WOUND: EXTRA_WOUNDS 1"]
close(dmg(w, NAKED, crit_only), A * P_HIT * (Q_W + 1 / 6),
      "EXTRA_WOUNDS on a critical wound only")
assert dmg(w, NAKED, crit_only) < one_w, \
    "the critical-only form must be weaker than the any-wound form"

# a critical wound collects BOTH bonuses
close(dmg(w, NAKED, ["EXTRA_WOUNDS 1"] + crit_only),
      A * P_HIT * (Q_W * 2 + 1 / 6),
      "a critical wound collects both kinds of bonus wound")

# ANTI-X lowers the critical-wound threshold, so it must feed this too
anti = weapon(kws=["ANTI-VEHICLE 4+"])
VEH = dict(NAKED, keywords={"VEHICLE"})
close(dmg(anti, VEH, crit_only), A * P_HIT * (Q_W + 3 / 6),
      "ANTI-X widens the critical-wound branch, bonus wounds included")
print("EXTRA WOUNDS: the critical-only form tracks the crit threshold")


# --- 1c. EXTRA ATTACKS -------------------------------------------------
# X further attacks with the weapon: a count, settled before any dice.
close(dmg(w, NAKED, ["EXTRA_ATTACKS 2"]), (A + 2) * P_HIT * Q_W,
      "EXTRA_ATTACKS 2 adds two attacks")
res = am.analyze_weapon(weapon(count=3), NAKED, {},
                        mech_for(weapon(count=3), ["EXTRA_ATTACKS 1"]))
close(res["attacks"]["mean"], 3 * (A + 1),
      "the bonus is per weapon copy, like Rapid Fire")
print("EXTRA ATTACKS: added to the attack count, per copy")


# --- 2. psychicAttack, defender side ----------------------------------
# The condition has no weapon in scope on a defender view, so
# modifier_engine must defer it instead of answering False.
env_no_weapon = type("Env", (), {"weapon": None})()
assert me._c_psychic_attack({}, env_no_weapon) is me.DYNAMIC, \
    "psychicAttack with no weapon in scope must be deferred, not denied"
cond = {"type": "psychicAttack", "data": {}}
assert me._dynamic_prefix(cond) == "PSYCHIC_ATTACK"

# ...and the attack maths must decide it from the attacking weapon.
psy = weapon(kws=["PSYCHIC"])
plain = weapon()
gated = ["IF PSYCHIC_ATTACK: SAVE_ROLL +1"]
assert mech_for(psy, gated).save_mod == 1, \
    "the ability must fire against a PSYCHIC weapon"
assert mech_for(plain, gated).save_mod == 0, \
    "and must not fire against a plain weapon"
print("psychicAttack reaches the maths and is decided per weapon")


# --- 3. invulnSave with a weapon-scope condition ----------------------
# SETINVULN grants an invulnerable save for the attack. Best value wins,
# no stacking -- the Feel No Pain rule.
BARE = dict(NAKED, Sv=6)                    # 6+ armour, no invuln
no_inv = dmg(w, BARE)
close(no_inv, A * P_HIT * Q_W * 5 / 6, "6+ armour baseline")
with_inv = dmg(w, BARE, ["SETINVULN 4"])
close(with_inv, A * P_HIT * Q_W * 3 / 6, "granted 4+ invulnerable")

HAS_INV = dict(NAKED, Sv=6, invuln=5)
close(am.effective_invuln(HAS_INV, mech_for(w, ["SETINVULN 4"])), 4,
      "the better invulnerable wins")
close(am.effective_invuln(HAS_INV, mech_for(w, ["SETINVULN 6"])), 5,
      "a worse granted invulnerable never replaces a better one")
close(am.effective_invuln(HAS_INV, mech_for(w)), 5, "no grant, no change")

# the conditional form is the one that used to be lost: a psychic-only
# invulnerable save, which is exactly gap 2 and gap 3 together.
psy_inv = ["IF PSYCHIC_ATTACK: SETINVULN 4"]
close(dmg(psy, BARE, psy_inv), A * P_HIT * Q_W * 3 / 6,
      "psychic-only invulnerable fires against a PSYCHIC weapon")
close(dmg(plain, BARE, psy_inv), A * P_HIT * Q_W * 5 / 6,
      "and stays silent against a plain one")
print("invulnSave works under a weapon-scope condition")


# --- Monte Carlo parity ------------------------------------------------
# The dice resolver must reproduce all of it, distribution included.
CASES = [
    ("extra hits", weapon(), NAKED, {}, ["EXTRA_HITS 1"]),
    ("extra hits D3", weapon(), NAKED, {}, ["EXTRA_HITS D3"]),
    ("extra hits + sustained", weapon(), NAKED, {},
     ["EXTRA_HITS 1", "IF CRIT_HIT: EXTRA_HITS 1"]),
    ("extra wounds", weapon(), ARMOURED, {}, ["EXTRA_WOUNDS 1"]),
    ("extra wounds D3", weapon(), ARMOURED, {}, ["EXTRA_WOUNDS D3"]),
    ("extra wounds on crit", weapon(), ARMOURED, {},
     ["IF CRIT_WOUND: EXTRA_WOUNDS 1"]),
    ("extra wounds on crit D3", weapon(), ARMOURED, {},
     ["IF CRIT_WOUND: EXTRA_WOUNDS D3"]),
    ("extra wounds, both kinds", weapon(), ARMOURED, {},
     ["EXTRA_WOUNDS 1", "IF CRIT_WOUND: EXTRA_WOUNDS 1"]),
    ("extra wounds on crit + anti", weapon(kws=["ANTI-VEHICLE 4+"]),
     dict(ARMOURED, keywords={"VEHICLE"}), {},
     ["IF CRIT_WOUND: EXTRA_WOUNDS 1"]),
    ("extra wounds on crit + devastating",
     weapon(kws=["DEVASTATING WOUNDS"]), ARMOURED, {},
     ["IF CRIT_WOUND: EXTRA_WOUNDS 1"]),
    ("extra wounds + devastating", weapon(kws=["DEVASTATING WOUNDS"]),
     ARMOURED, {}, ["EXTRA_WOUNDS 1"]),
    ("extra wounds + lethal", weapon(kws=["LETHAL HITS"]), ARMOURED, {},
     ["EXTRA_WOUNDS 1"]),
    ("extra attacks", weapon(count=2), NAKED, {}, ["EXTRA_ATTACKS 2"]),
    ("extra attacks D3", weapon(count=2), NAKED, {}, ["EXTRA_ATTACKS D3"]),
    ("granted invuln", weapon(AP=-2), dict(NAKED, Sv=3), {},
     ["SETINVULN 4"]),
    ("granted invuln, psychic gate", weapon(AP=-2, kws=["PSYCHIC"]),
     dict(NAKED, Sv=3), {}, ["IF PSYCHIC_ATTACK: SETINVULN 4"]),
    ("extras vs torrent", weapon(kws=["TORRENT"]), ARMOURED, {},
     ["EXTRA_HITS 1", "EXTRA_WOUNDS 1"]),
]
for name, wpn, ref, ctx, effects in CASES:
    ok, msg = mcs.check_weapon(name, wpn, ref, ctx, mech_for(wpn, effects))
    assert ok, msg
print(f"exact maths and dice resolver agree on all {len(CASES)} "
      f"new configurations")

print("ALL EXTRA-ABILITY TESTS PASS")
