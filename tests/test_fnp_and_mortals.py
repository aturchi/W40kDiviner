"""Conditional Feel No Pain, and what can stop a mortal wound.

FNP can now be GRANTED (best value wins, no stacking), OVERRIDDEN
(forced, even if worse - 7 means none at all) or MODIFIED (+/-N on the
roll), and any of the three can be restricted to mortal wounds with the
"only vs mortal wounds" condition. Devastating Wounds allow no saving
throw, so the only things that stop them are Feel No Pain and an ability
granting an invulnerable save against mortal wounds.

Expected values are written in closed form, independently of the engine,
and every case is cross-checked against the dice resolver.
No tkinter needed.
"""
import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
import mc_support as mcs
from unit_model import Weapon

TOL = 1e-9


def close(a, b, what):
    assert abs(a - b) < TOL, f"{what}: got={a!r} expected={b!r}"


def mech(kws=(), effects=()):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(list(kws), m)
    am.parse_effect_strings(list(effects), "Ranged", m, None)
    assert not m.warnings, m.warnings
    return m


# Always hits, always wounds, no save: only the FNP stage moves.
W = Weapon(name="w", wtype="Ranged", A="6", skill=2, S=10, AP=-6, D="1",
           count=1)
REF = {"T": 2, "Sv": 6, "W": 9, "invuln": None, "fnp": None, "models": 1,
       "keywords": set()}
P_HIT, Q_W, A = 5 / 6, 5 / 6, 6


def dmg(ref, m):
    return am.analyze_weapon(W, ref, {}, m.copy())["damage"]["mean"]


def agree(ref, m, what, weapon=None):
    """Exact vs dice, with the statistical tolerance of mc_support (the
    standard error comes from the exact variance; mc_support.SIGMA is
    the knob) on both the mean and the whole distribution."""
    ok, msg = mcs.check_weapon(what, weapon or W, ref, {}, m)
    assert ok, msg


# --- effective_fnp: the three operators --------------------------------
ref5 = dict(REF, fnp=5)
close(am.effective_fnp(ref5, mech(), False)[0], 5, "datasheet FNP")
# grant: best wins, never stacks
close(am.effective_fnp(ref5, mech(effects=["SETFNP 4"]), False)[0], 4,
      "granted FNP, better")
close(am.effective_fnp(ref5, mech(effects=["SETFNP 6"]), False)[0], 5,
      "granted FNP, worse: the best still wins")
# override: forced, even when worse
close(am.effective_fnp(ref5, mech(effects=["FNPOVERRIDE 6"]), False)[0], 6,
      "overridden FNP")
close(am.effective_fnp(ref5, mech(effects=["FNPOVERRIDE 7"]), False)[0], 7,
      "override 7 = no FNP")
# modify: shifts the roll
close(am.effective_fnp(ref5, mech(effects=["FNP_ROLL +1"]), False)[1], 1,
      "FNP roll modifier")
print("FNP can be granted, overridden or modified")

# --- the same, restricted to mortal wounds -----------------------------
mw_only = mech(effects=["IF MW_ONLY: SETFNP 4",
                        "IF MW_ONLY: FNP_ROLL +1"])
close(am.effective_fnp(REF, mw_only, False)[0] or 0, 0,
      "MW-only FNP does not apply to normal damage")
close(am.effective_fnp(REF, mw_only, True)[0], 4, "MW-only FNP applies")
close(am.effective_fnp(REF, mw_only, True)[1], 1, "MW-only FNP modifier")
ovr = mech(effects=["IF MW_ONLY: FNPOVERRIDE 7"])
close(am.effective_fnp(ref5, ovr, True)[0], 7, "MW-only override")
close(am.effective_fnp(ref5, ovr, False)[0], 5, "...normal damage untouched")
print("every FNP operator can be conditioned on mortal wounds")

# --- the numbers, end to end -------------------------------------------
close(dmg(REF, mech()), A * P_HIT * Q_W, "no FNP")
# FNP 5+: two thirds of the damage points get through.
close(dmg(ref5, mech()), A * P_HIT * Q_W * (1 - 2 / 6), "FNP 5+")
# +1 to the roll makes it a 4+.
close(dmg(ref5, mech(effects=["FNP_ROLL +1"])), A * P_HIT * Q_W * (1 - 3 / 6),
      "FNP 5+ with +1")
# an override to 7+ removes it entirely
close(dmg(ref5, mech(effects=["FNPOVERRIDE 7"])), A * P_HIT * Q_W,
      "FNP overridden away")
for m, name in ((mech(), "plain"), (mech(effects=["FNP_ROLL +1"]), "mod"),
                (mech(effects=["FNPOVERRIDE 7"]), "override")):
    agree(ref5, m, name)
print("exact and Monte-Carlo agree on the FNP operators")

# --- Devastating Wounds: no save, only FNP (and a MW invuln) -----------
# 6 attacks, BS2+ (5/6, crit 1/6), S10 vs T2 wounds on 2+ (5/6, crit
# 1/6), armour 2+ with AP0 -> 5/6 saved, so the critical wounds carry
# almost everything.
WD = Weapon(name="d", wtype="Ranged", A="6", skill=2, S=10, AP=0, D="1",
            count=1)
DREF = {"T": 2, "Sv": 2, "W": 9, "invuln": 4, "fnp": None, "models": 1,
        "keywords": set()}
P_CRIT, Q_CRIT, UNSAVED = 1 / 6, 1 / 6, 1 - 5 / 6


def dmg_d(ref, m):
    return am.analyze_weapon(WD, ref, {}, m.copy())["damage"]["mean"]


dev = mech(["DEVASTATING WOUNDS"])
# critical wounds bypass BOTH the armour and the 4+ invulnerable save
close(dmg_d(DREF, dev),
      A * P_HIT * ((Q_W - Q_CRIT) * UNSAVED + Q_CRIT),
      "devastating ignores armour and invuln alike")
# ...unless an ability grants an invulnerable save against mortal wounds
dev_inv = mech(["DEVASTATING WOUNDS"], ["IF MW_ONLY: SETINVULN 4"])
assert dev_inv.invuln_mw == 4
close(dmg_d(DREF, dev_inv),
      A * P_HIT * ((Q_W - Q_CRIT) * UNSAVED + Q_CRIT * (1 - 3 / 6)),
      "invuln vs mortal wounds")
# FNP applies on top of that save
dev_both = mech(["DEVASTATING WOUNDS"],
                ["IF MW_ONLY: SETINVULN 4", "IF MW_ONLY: SETFNP 5"])
close(dmg_d(DREF, dev_both),
      A * P_HIT * ((Q_W - Q_CRIT) * UNSAVED
                   + Q_CRIT * (1 - 3 / 6) * (1 - 2 / 6)),
      "invuln then FNP, both vs mortal wounds only")
for m, name in ((dev, "dev"), (dev_inv, "dev+inv"), (dev_both, "dev+inv+fnp")):
    agree(DREF, m, name, weapon=WD)
print("mortal wounds: no save, only FNP or a mortal-wound invulnerable")

print("ALL FNP / MORTAL-WOUND TESTS PASS")
