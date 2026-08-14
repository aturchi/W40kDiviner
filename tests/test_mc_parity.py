"""Exact PMF vs dice resolver: the permanent parity sweep.

The two engines must never diverge. This file walks a broad set of
mechanics - the hit-stage branches, the critical branches, the mortal
streams, the damage chain, the defensive side and the context flags -
and for each one compares the analytic PMF with the dice engine on BOTH
the mean and the whole distribution, with a tolerance derived from the
exact variance (see mc_support: SIGMA and TRIALS are the knobs).

What this does NOT prove: the two engines share WeaponMechanics and its
parsing, so parity shows CONSISTENCY, not fidelity to the rules. The
rules-level checks live in test_critical_triggers, test_modifier_caps,
test_fnp_and_mortals, test_indirect_fire and test_close_quarters, which
compare against values worked out in closed form.
"""
import testpaths                      # sets up sys.path to the engine src/
import mc_support as mcs
import attack_math as am
from unit_model import Weapon


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def kw_mech(*keywords):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(list(keywords), m)
    assert not m.warnings, m.warnings
    return m


# --- scenario A: random attacks and damage, tough target with an invuln
WEAPON_A = Weapon(name="A", wtype="Ranged", A="D6+2", skill=3, S=6, AP=-2,
                  D="D3+1", count=3)
REF_A = {"T": 5, "Sv": 3, "W": 3, "invuln": 5, "fnp": None, "models": 11,
         "keywords": {"VEHICLE"}}

# --- scenario B: flat profile, hard target, wounds only on 6s ---------
WEAPON_B = Weapon(name="B", wtype="Melee", A="4", skill=4, S=4, AP=-1,
                  D="2", count=2)
REF_B = {"T": 9, "Sv": 2, "W": 6, "invuln": None, "fnp": None, "models": 3,
         "keywords": {"VEHICLE", "MONSTER"}}

CASES = [
    # (scenario, name, mechanics, context, defender overrides)
    ("A", "plain", mech(), {}, {}),
    ("A", "sustained 2", mech(sustained=2), {}, {}),
    ("A", "lethal", mech(lethal=True), {}, {}),
    ("A", "lethal_crit", mech(lethal_crit=True), {}, {}),
    ("A", "devastating", mech(devastating=True), {}, {}),
    ("A", "dev + anti", mech(devastating=True,
                             anti=[("VEHICLE", 4)]), {}, {}),
    ("A", "anti alone", mech(anti=[("VEHICLE", 4)]), {}, {}),
    ("A", "twin-linked", mech(twin_linked=True), {}, {}),
    ("A", "reroll hit 1s", mech(reroll_hit="1"), {}, {}),
    ("A", "reroll hit fails", mech(reroll_hit="fails"), {}, {}),
    ("A", "crit hit on 5", mech(crit_hit_on=5, sustained=1), {}, {}),
    ("A", "sust+leth+dev+anti", mech(sustained=1, lethal=True,
                                     devastating=True,
                                     anti=[("VEHICLE", 5)]), {}, {}),
    ("A", "hit only unmod 5+", mech(hit_unmod_only=5), {}, {}),
    ("A", "hit-roll mortals", mech(hitroll_mw={"thr": 6, "value": None,
                                               "match": True,
                                               "end": True}), {}, {}),
    ("A", "crit mortals, go on", mech(crit_mw={"value": 2, "match": False,
                                               "end": False}), {}, {}),
    ("A", "crit AP delta", mech(crit_ap_delta=2), {}, {}),
    ("A", "reroll saves", mech(reroll_save="fails"), {}, {}),
    ("A", "hit -1, wound +1", mech(hit_mod=-1, wound_mod=1), {}, {}),
    ("A", "cover", mech(), {"cover": True}, {}),
    ("A", "cover + hit -1", mech(hit_mod=-1), {"cover": True}, {}),
    ("A", "heavy, stationary", mech(heavy=True), {"stationary": True}, {}),
    ("A", "melta at half range", mech(melta=2, rapid_fire=1),
     {"half_range": True}, {}),
    ("A", "blast 2", mech(blast=2), {}, {}),
    ("A", "auto wound", mech(auto_wound=True), {}, {}),
    ("A", "torrent", mech(torrent=True), {}, {}),
    ("A", "damage reroll 1-2", mech(dmg_reroll=(1, 2)), {}, {}),
    ("A", "fnp 5+", mech(), {}, {"fnp": 5}),
    ("A", "fnp 5+ with +1", mech(fnp_mod=1), {}, {"fnp": 5}),
    ("A", "fnp overridden away", kw_mech(), {}, {"fnp": 5}),
    ("A", "indirect, no spotter", kw_mech("INDIRECT FIRE"),
     {"indirect": True}, {}),
    ("A", "indirect with spotter", kw_mech("INDIRECT FIRE"),
     {"indirect": True, "spotter": True}, {}),
    ("A", "close quarters -1", kw_mech(), {"close_quarters_penalty": True},
     {}),
    ("A", "close quarters exempt", kw_mech("CLOSE-QUARTERS"),
     {"close_quarters_penalty": True}, {}),
    ("B", "plain (S4 vs T9)", mech(), {}, {}),
    ("B", "anti-vehicle 4+", mech(anti=[("VEHICLE", 4)]), {}, {}),
    ("B", "anti + dev", mech(anti=[("VEHICLE", 4)], devastating=True),
     {}, {}),
    ("B", "crit AP delta 3", mech(crit_ap_delta=3), {}, {}),
    ("B", "lance on the charge", mech(lance=True), {"charged": True}, {}),
    ("B", "wound reroll 1s", mech(reroll_wound="1"), {}, {}),
    ("B", "save -1", mech(save_mod=-1), {}, {}),
    ("B", "save -2 (uncapped)", mech(save_mod=-2), {}, {}),
    ("B", "ignore wound malus", mech(wound_mod=-1,
                                     ignore_malus={"wound"}), {}, {}),
    ("B", "damage set to 1", mech(dmg_set=1), {}, {}),
    ("B", "damage halved, -1", mech(dmg_mult=0.5, dmg_add=-1), {}, {}),
    ("B", "attacker damaged", mech(), {"damaged": True}, {}),
    ("B", "cleave 1", mech(cleave=1), {}, {}),
    ("B", "invuln vs mortals", kw_mech("DEVASTATING WOUNDS"), {},
     {"invuln_mw": 4}),
    ("B", "mortal fnp + invuln", kw_mech("DEVASTATING WOUNDS"), {},
     {"invuln_mw": 4, "fnp_mw": 5}),
]

SCENARIOS = {"A": (WEAPON_A, REF_A), "B": (WEAPON_B, REF_B)}
# Mechanics fields that the case table sets through the defender column,
# because they describe an ability of the DEFENDER, not of the weapon.
DEFENDER_MECH_FIELDS = ("invuln_mw", "fnp_mw", "fnp_set")

failures, lines = [], []
for scenario, name, base, ctx, over in CASES:
    weapon, ref = SCENARIOS[scenario]
    ref = dict(ref)
    m = base.copy()
    for key, value in over.items():
        if key in DEFENDER_MECH_FIELDS:
            setattr(m, key, value)
        else:
            ref[key] = value
    if name == "fnp overridden away":
        am.parse_effect_strings(["FNPOVERRIDE 7"], "Ranged", m, weapon)
    ok, msg = mcs.check_weapon(f"{scenario}: {name}", weapon, ref, ctx, m)
    lines.append(msg)
    if not ok:
        failures.append(msg)

print("\n".join(lines))
print(f"\n{len(CASES)} configurations, {mcs.TRIALS} rolls each, "
      f"tolerance {mcs.SIGMA} sigma on the mean and the same level on "
      f"the CDF, corrected for the number of points compared")
assert not failures, "parity broken:\n" + "\n".join(failures)

# --- the tolerance must actually bite ---------------------------------
# A deliberately wrong exact PMF (5% of the mass shifted) has to be
# caught, otherwise the sweep above would be decoration.
weapon, ref = SCENARIOS["A"]
good = am.analyze_weapon(weapon, ref, {}, am.WeaponMechanics())["damage_pmf"]
samples = mcs.sample_damage(weapon, ref, {}, am.WeaponMechanics())
bad = list(good)
bad[0] = bad[0] + 0.05
bad[-1] = max(0.0, bad[-1] - 0.05)
z_mean, _e, _g = mcs.mean_deviation(bad, samples)
z_cdf, _at, points = mcs.cdf_deviation(bad, samples)
assert (z_mean > mcs.SIGMA
        or z_cdf > mcs.family_limit(mcs.SIGMA, points)), (z_mean, z_cdf)
# ...and a distortion that leaves the mean alone must be caught by the
# CDF check, which is the whole point of looking past the mean.
mean_ok = list(good)
lo, hi = 1, len(good) - 2
if hi > lo:
    shift = 0.04
    mid = (lo + hi) / 2.0
    mean_ok[lo] += shift
    mean_ok[hi] += shift * (lo - mid) / (mid - hi) if mid != hi else shift
    total = sum(mean_ok)
    mean_ok = [p / total for p in mean_ok]
    z_cdf, _at, points = mcs.cdf_deviation(mean_ok, samples)
    assert z_cdf > mcs.family_limit(mcs.SIGMA, points), z_cdf
print("the tolerance catches both a shifted mean and a reshaped tail")

print("ALL MONTE-CARLO PARITY TESTS PASS")
