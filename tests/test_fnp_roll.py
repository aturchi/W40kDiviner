"""The Feel No Pain ROLL itself: the natural 1, and what a re-roll of it
is worth.

Feel No Pain is a d6 per point of damage, needing the model's FNP
characteristic or better. Two 11th-ed. rules decide the faces:

  * an UNMODIFIED 1 always fails (05.04 states it for the saving throw
    and 01.05.03 for dice rolls in general). Feel No Pain modifiers are
    NOT capped - only hit and wound ROLLS are - so a +1 on a 2+ roll
    drives the target to 1+ and, without that floor, the roll would
    become automatic;
  * re-rolls happen BEFORE modifiers and a die may be re-rolled once
    (01.05.02), so a failed Feel No Pain that is re-rolled gets a fresh
    die: a 2+ with a re-roll of failures ignores 35/36, not 5/6.

Regression this file anchors (see the handoff):

  * the exact chain capped the probability AFTER accumulating the
    re-roll (min(P, 5/6)), which threw the re-roll away entirely on any
    roll of 3+ or better - 0.8333 where the rules say 0.8889;
  * the dice resolver had no natural-1 guard at all, so an effective
    target of 1+ ignored EVERYTHING - 1.0000 where the rules say
    0.8333.

Both engines were wrong, in OPPOSITE directions, which is why the
parity sweep was quiet: no case in it carried a Feel No Pain re-roll or
a positive Feel No Pain modifier large enough to reach the floor.

Every expected value below is written in closed form here. Each claim
carries an INVERSE check - a nearby configuration where the same number
must NOT appear - so the file cannot pass for the wrong reason.
"""
import random

import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
import attack_resolve as ar
import rules_config
from unit_model import Weapon

TOL = 1e-12


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


# --- 1. the faces, one by one ----------------------------------------
# An unmodified 1 fails whatever the target is.
assert am.fnp_roll_ok(1, 1) is False, "a natural 1 passed a 1+ FNP"
assert am.fnp_roll_ok(1, 4) is False
assert am.fnp_roll_ok(1, -3) is False, "a natural 1 passed a negative target"
# ...and every other face passes exactly when it reaches the target.
for eff in range(-2, 9):
    for r in range(2, 7):
        assert am.fnp_roll_ok(r, eff) is (r >= eff), (r, eff)
# INVERSE: without the natural-1 rule a target of 1+ would take all six
# faces. It takes five.
assert sum(1 for r in range(1, 7) if am.fnp_roll_ok(r, 1)) == 5
assert sum(1 for r in range(1, 7) if r >= 1) == 6

print("the natural 1 always fails a Feel No Pain roll")


# --- 2. the probability, with and without a re-roll -------------------
# No re-roll: (7 - eff) / 6, ceilinged at 5/6 by the natural 1.
CASES_PLAIN = {2: 5 / 6, 3: 4 / 6, 4: 3 / 6, 5: 2 / 6, 6: 1 / 6, 7: 0.0}
for eff, want in CASES_PLAIN.items():
    got = am.fnp_ignore_prob(eff, None)
    assert abs(got - want) < TOL, f"FNP {eff}+: {got} != {want}"
# The floor: 1+ and below are all worth 5/6, never more.
for eff in (1, 0, -1):
    assert abs(am.fnp_ignore_prob(eff, None) - 5 / 6) < TOL
# INVERSE: 5/6 is NOT the answer for a 3+, so the ceiling is a ceiling
# and not a constant.
assert abs(am.fnp_ignore_prob(3, None) - 5 / 6) > 0.1

# One re-roll of failures: p + (1-p)p. Worked out by hand.
#   2+  5/6 + (1/6)(5/6) = 35/36 = 0.972222
#   3+  4/6 + (2/6)(4/6) = 32/36 = 0.888889
#   4+  3/6 + (3/6)(3/6) = 27/36 = 0.750000
#   5+  2/6 + (4/6)(2/6) = 20/36 = 0.555556
#   6+  1/6 + (5/6)(1/6) = 11/36 = 0.305556
CASES_FAILS = {2: 35 / 36, 3: 32 / 36, 4: 27 / 36, 5: 20 / 36, 6: 11 / 36}
for eff, want in CASES_FAILS.items():
    got = am.fnp_ignore_prob(eff, "fails")
    assert abs(got - want) < TOL, f"FNP {eff}+ re-roll fails: {got} != {want}"
# INVERSE: the re-roll must be WORTH something on the good rolls too -
# the regression was exactly a 2+ and a 3+ coming back at 5/6.
assert am.fnp_ignore_prob(2, "fails") > 5 / 6 + 0.1
assert am.fnp_ignore_prob(3, "fails") > 5 / 6 + 0.05
# ...and the floor still holds after the re-roll: a 1+ is a 2+.
assert abs(am.fnp_ignore_prob(1, "fails") - 35 / 36) < TOL
assert abs(am.fnp_ignore_prob(-2, "fails") - 35 / 36) < TOL

# One re-roll of 1s only: p + (1/6)p, since only the natural 1 is taken
# back. On a 2+ that is the same as re-rolling failures (the 1 IS the
# only failure); on a 4+ it is strictly less.
for eff in range(2, 7):
    want = CASES_PLAIN[eff] * (1 + 1 / 6)
    got = am.fnp_ignore_prob(eff, "1")
    assert abs(got - want) < TOL, f"FNP {eff}+ re-roll 1s: {got} != {want}"
assert abs(am.fnp_ignore_prob(2, "1")
           - am.fnp_ignore_prob(2, "fails")) < TOL
assert am.fnp_ignore_prob(4, "1") < am.fnp_ignore_prob(4, "fails") - 0.1

# A target of 7+ is no Feel No Pain at all, re-roll or not: there is
# nothing to re-roll into.
for rr in (None, "fails", "1"):
    assert am.fnp_ignore_prob(7, rr) == 0.0
    assert am.fnp_ignore_prob(9, rr) == 0.0

# With re-rolls switched off globally the re-roll buys nothing.
_cap = rules_config.CAP_REROLLS
try:
    rules_config.CAP_REROLLS = 0
    for eff in (2, 4, 6):
        assert abs(am.fnp_ignore_prob(eff, "fails")
                   - CASES_PLAIN[eff]) < TOL
finally:
    rules_config.CAP_REROLLS = _cap
# INVERSE: with the cap back at 1 it buys something again.
assert am.fnp_ignore_prob(4, "fails") > CASES_PLAIN[4] + 0.2

print("Feel No Pain probabilities match the closed form, re-rolls included")


# --- 3. the dice resolver draws the same faces ------------------------
# _fnp_keep returns the points KEPT, so 1 - kept/n estimates the same
# probability. 200k rolls put the standard error near 0.001.
N = 200000
for fnp, fnp_mod, rr in ((2, 0, None), (2, 0, "fails"), (3, 0, "fails"),
                         (4, 0, "1"), (5, 0, None), (6, 0, "fails"),
                         (2, 1, None), (2, 1, "fails"), (3, 2, "fails"),
                         (4, -1, None), (6, -2, "fails")):
    m = mech(fnp_mod=fnp_mod, reroll_fnp=rr)
    kept = ar._fnp_keep(random.Random(4242), N, fnp, m, mw=False)
    got = 1.0 - kept / N
    want = am.fnp_ignore_prob(fnp - fnp_mod, rr)
    assert abs(got - want) < 0.006, \
        f"FNP {fnp}+ mod {fnp_mod:+d} re-roll {rr}: dice={got:.4f} " \
        f"exact={want:.4f}"
# INVERSE: an effective 1+ must NOT ignore everything - that was the
# dice-side regression, and 5/6 is a long way from 1.
m = mech(fnp_mod=1)
kept = ar._fnp_keep(random.Random(7), N, 2, m, mw=False)
assert kept > 0, "an effective FNP of 1+ ignored every point of damage"
assert abs(1.0 - kept / N - 5 / 6) < 0.006

print("the dice resolver agrees with the exact Feel No Pain probability")


# --- 4. end to end, through both engines ------------------------------
# A weapon that always hits, always wounds and is never saved, so the
# whole outcome IS the Feel No Pain roll: 8 attacks of 1 damage means
# the mean damage is exactly 8 * (1 - p_ignore).
FLAT = Weapon(name="flat", wtype="Ranged", A="8", skill=2, S=10, AP=-6,
              D="1", count=1)
REF = {"T": 1, "Sv": None, "W": 20, "invuln": None, "fnp": None,
       "models": 1, "keywords": ()}

for name, fnp, kw, want_p in (
        ("fnp 5+", 5, {}, 2 / 6),
        ("fnp 5+ re-roll fails", 5, {"reroll_fnp": "fails"}, 20 / 36),
        ("fnp 3+ re-roll fails", 3, {"reroll_fnp": "fails"}, 32 / 36),
        ("fnp 2+ re-roll fails", 2, {"reroll_fnp": "fails"}, 35 / 36),
        ("fnp 4+ re-roll 1s", 4, {"reroll_fnp": "1"}, (3 / 6) * (7 / 6)),
        ("fnp 2+ with +1", 2, {"fnp_mod": 1}, 5 / 6),
        ("fnp 3+ with +2", 3, {"fnp_mod": 2}, 5 / 6)):
    ref = dict(REF, fnp=fnp)
    m = mech(**kw)
    # BS2+ hits 5/6 of the time and S10 vs T1 wounds on 2+, another 5/6
    # (the natural 1 fails on both), so the expected damage is
    # 8 * (5/6) * (5/6) * (1 - p_ignore).
    want = 8 * (5 / 6) * (5 / 6) * (1 - want_p)
    exact = am.analyze_weapon(FLAT, ref, {}, m.copy())["damage"]["mean"]
    assert abs(exact - want) < 1e-9, \
        f"{name}: exact={exact:.6f} closed form={want:.6f}"
    rng = random.Random(2026)
    tot = 0
    for _ in range(30000):
        res = ar.resolve_weapon(FLAT, ref, {}, m.copy(), rng)
        tot += sum(e["amount"] for e in res["events"])
    assert abs(exact - tot / 30000) < 0.06, \
        f"{name}: exact={exact:.4f} dice={tot / 30000:.4f}"

# INVERSE: the two re-roll cases above must differ from their plain
# counterparts, or the assertions would hold with the re-roll ignored.
plain3 = am.analyze_weapon(FLAT, dict(REF, fnp=3), {},
                           mech())["damage"]["mean"]
rr3 = am.analyze_weapon(FLAT, dict(REF, fnp=3), {},
                        mech(reroll_fnp="fails"))["damage"]["mean"]
assert rr3 < plain3 - 0.5, \
    f"the Feel No Pain re-roll changed nothing: {plain3:.4f} -> {rr3:.4f}"

print("both engines agree end to end on Feel No Pain")


# --- 5. mortal wounds take the same roll ------------------------------
# A Feel No Pain that applies to mortal wounds only (fnp_mw) goes
# through the same helper, re-roll included.
DEV = Weapon(name="dev", wtype="Ranged", A="8", skill=2, S=10, AP=-6,
             D="1", count=1)
m = mech(devastating=True, crit_wound_on=2, fnp_mw=3, reroll_fnp="fails")
exact = am.analyze_weapon(DEV, REF, {}, m.copy())["damage"]["mean"]
# S10 vs T1 wounds on 2+, and crit_wound_on=2 makes every wound
# critical, so every hit becomes a mortal wound: 8 * (5/6) hits, all
# devastating, each shrugged with probability 32/36.
want = 8 * (5 / 6) * (5 / 6) * (1 - 32 / 36)
assert abs(exact - want) < 1e-9, f"mortal FNP: {exact:.6f} != {want:.6f}"
rng = random.Random(99)
tot = 0
for _ in range(30000):
    tot += sum(e["amount"] for e in
               ar.resolve_weapon(DEV, REF, {}, m.copy(), rng)["events"])
assert abs(exact - tot / 30000) < 0.06, \
    f"mortal FNP: exact={exact:.4f} dice={tot / 30000:.4f}"
# INVERSE: without the re-roll the same weapon gets through more.
m2 = mech(devastating=True, crit_wound_on=2, fnp_mw=3)
plain = am.analyze_weapon(DEV, REF, {}, m2)["damage"]["mean"]
assert plain > exact + 0.5, \
    f"the re-roll did not reach the mortal stream: {plain:.4f} {exact:.4f}"

print("the mortal-wound Feel No Pain uses the same roll")

print("OK  test_fnp_roll")
