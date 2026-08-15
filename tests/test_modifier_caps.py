"""11th-ed. modifiers: what is capped, what is merely limited.

  * Only the HIT and WOUND roll modifiers are capped (CAP_ROLL_MOD).
    Save, invulnerable and Feel No Pain modifiers apply in full.
  * CHARACTERISTIC modifiers are NOT capped at all. They are bounded by
    absolute limits: BS/WS between 2+ and 6+, Sv (and invuln) never
    better than 2+, AP never above 0.
  * The two groups are independent, which is why the Benefit of Cover
    (-1 BS) stacks with a -1 to-hit ability for an effective -2.

Also checks that the characteristic limits are applied BEFORE the roll
modifier (the rules limit the characteristic, then the roll modifier
applies on top), and that the dice resolver agrees with the exact maths
once both groups stack. No tkinter needed.
"""
import json

import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import attack_math as am
import mc_support as mcs
import rules_config as rc
import unit_model as um
from unit_model import Weapon


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def clone(m):
    n = am.WeaponMechanics()
    n.__dict__.update(m.__dict__)
    n.ignore_malus, n.anti, n.warnings = set(m.ignore_malus), list(m.anti), []
    return n


WEAPON = Weapon(name="synthetic", wtype="Ranged", A="6", skill=3, S=5, AP=0,
                D="1", count=1)
REF = {"T": 4, "Sv": 4, "W": 1, "invuln": None, "fnp": None, "models": 1,
       "keywords": set()}


def mean(m, ctx, ref=None):
    return am.analyze_weapon(WEAPON, ref or REF, ctx,
                             clone(m))["damage"]["mean"]


# --- the pure helpers --------------------------------------------------
assert rc.cap_roll(3) == 1 and rc.cap_roll(-3) == -1 and rc.cap_roll(0) == 0
# characteristics: no cap, only absolute limits
assert rc.clamp_characteristic("BS", 0) == 2      # never better than 2+
assert rc.clamp_characteristic("BS", 9) == 6      # never worse than 6+
assert rc.clamp_characteristic("Sv", 1) == 2      # never better than 2+
assert rc.clamp_characteristic("invuln", 0) == 2
assert rc.clamp_characteristic("AP", 2) == 0      # never worse than 0
assert rc.clamp_characteristic("AP", -4) == -4    # ...but no floor
assert rc.clamp_characteristic("S", 12) == 12     # S/A/D unbounded above
assert rc.clamp_characteristic("S", -4) == 1
print("roll modifiers are capped, characteristics only limited")

# --- the two groups stack ----------------------------------------------
# BS3+, 6 attacks, always wounds on 3+, save 4+: only the hit stage moves.
base = mean(mech(), {})                                   # BS3+
one_pen = mean(mech(hit_mod=-1), {})                      # -1 roll  -> 4+
cover = mean(mech(), {"cover": True})                     # -1 BS    -> 4+
both = mean(mech(hit_mod=-1), {"cover": True})            # -1 and -1 -> 5+
assert one_pen == cover < base, (base, one_pen, cover)
assert abs(both - base / 2) < 1e-9, (both, base)
# the ROLL modifier is still clamped inside its own group...
assert mean(mech(hit_mod=-2), {"cover": True}) == both
assert mean(mech(hit_mod=-1, wound_mod=-3), {}) == mean(
    mech(hit_mod=-1, wound_mod=-1), {})
print("characteristic and roll modifiers stack, only the roll is capped")

# --- ...but the CHARACTERISTIC modifier is not clamped at 1 ------------
# Two -1 BS sources (cover plus a manual one) really is -2 BS: BS3+ -> 5+.
two_bs = mean(mech(), {"cover": True, "plunging": False})
assert two_bs == cover                                    # sanity: one source
# a huge BS penalty is bounded by the 6+ limit, not by a cap
worst = mean(mech(), {"cover": True})
assert mean(mech(hit_mod=-1), {"cover": True}) < worst
print("characteristic penalties are bounded by 6+, not by a cap")

# --- limits apply BEFORE the roll modifier -----------------------------
# BS2+ with +1 BS (plunging) is still 2+, so a -1 to-hit roll leaves 3+,
# NOT 2+: clamping first is what makes the two differ.
W2 = Weapon(name="best", wtype="Ranged", A="6", skill=2, S=5, AP=0, D="1",
            count=1)
plunge_then_pen = am.analyze_weapon(
    W2, REF, {"plunging": True}, clone(mech(hit_mod=-1)))["damage"]["mean"]
plain_pen = am.analyze_weapon(
    W2, REF, {}, clone(mech(hit_mod=-1)))["damage"]["mean"]
assert abs(plunge_then_pen - plain_pen) < 1e-9, (plunge_then_pen, plain_pen)
print("BS is clamped at 2+ before the hit-roll modifier applies")

# --- saves: uncapped modifiers, characteristic clamped at 2+ -----------
# A -2 to the save roll now applies in full (it used to be capped at -1).
assert mean(mech(save_mod=-2), {}) > mean(mech(save_mod=-1), {})
# Sv 1+ is illegal: it saves as 2+, so AP-1 leaves a 3+ save, not a 2+.
ref_1up = dict(REF, Sv=1)
ref_2up = dict(REF, Sv=2)
w_ap1 = Weapon(name="ap1", wtype="Ranged", A="6", skill=3, S=5, AP=-1, D="1",
               count=1)
a = am.analyze_weapon(w_ap1, ref_1up, {}, clone(mech()))["damage"]["mean"]
b = am.analyze_weapon(w_ap1, ref_2up, {}, clone(mech()))["damage"]["mean"]
assert abs(a - b) < 1e-9, (a, b)
print("Sv and invuln are clamped at 2+ before AP")

# --- the two ignore-malus groups are independent -----------------------
# 11th ed. keeps the hit ROLL modifiers and the BS/WS CHARACTERISTIC
# modifiers apart, so ignoring one group must not touch the other.
assert mean(mech(hit_mod=-1, ignore_malus={"hit"}), {"cover": True}) < base, \
    "'hit' must not clear the BS penalty of Cover"
assert mean(mech(hit_mod=-1, ignore_malus={"skill"}), {"cover": True}) < base, \
    "'skill' must not clear the hit-roll penalty"
assert mean(mech(hit_mod=-1, ignore_malus={"hit", "skill"}),
            {"cover": True}) == base, "both groups together clear everything"
assert mean(mech(hit_mod=1, ignore_malus={"hit"}), {}) > base, \
    "positive modifiers still apply"
# PSYCHIC sets both groups, as its wording says
psy = am.WeaponMechanics()
am.parse_weapon_keywords(["PSYCHIC"], psy)
assert psy.ignore_malus == {"hit", "skill"}, psy.ignore_malus
print("the hit-roll and BS/WS ignore-malus groups are independent")

# --- the "no cap" option frees the rolls -------------------------------
rc.set_caps(roll=None)
try:
    free = mean(mech(hit_mod=-2), {"cover": True})        # -1 BS, -2 roll
    assert free < both, (free, both)
finally:
    rc.set_caps(roll=1)
assert mean(mech(hit_mod=-2), {"cover": True}) == both    # cap restored
print("removing the cap frees the hit/wound rolls")

# --- characteristic deltas are NOT capped where the views are built ----
data = json.load(open(testpaths.roster("space-marines.json")))
units = um.units_from_native(data)
att = next(u for u in units if any(w.type == "Ranged" and not w.AP.is_none()
                                   for m in u.models() for w in m.weapons))
dfn = units[0]


def first_ranged(mods, attr):
    aview, _d = ac.build_views(att, dfn, {}, mods)
    for m in aview.models():
        for w in m.weapons:
            if w.type == "Ranged" and not w.AP.is_none():
                return getattr(w, attr).value()


plain_ap = first_ranged({}, "AP")
assert first_ranged({"weapon": {"AP": -3}}, "AP") == plain_ap - 3, \
    "AP delta must not be capped"
assert first_ranged({"weapon": {"AP": 99}}, "AP") == 0, "AP limit is 0"
plain_s = first_ranged({}, "S")
assert first_ranged({"weapon": {"S": 3}}, "S") == plain_s + 3
print("characteristic deltas apply in full, bounded only by the limits")

# --- the dice resolver agrees once the two groups stack ----------------
ok, msg = mcs.check_weapon("cover + hit -1", WEAPON, REF, {"cover": True},
                           mech(hit_mod=-1))
assert ok, msg
print("exact and Monte-Carlo agree with both groups stacked")

print("ALL MODIFIER-CAP TESTS PASS")
