"""The critical threshold, and the floor an unmodified 1 puts under it.

A critical hit or wound is scored on an UNMODIFIED roll of 6, and
abilities lower that threshold: CONVERSION (4+ at long range), ANTI-X
N+, the criticalThreshold effect of the ability editor. 11th ed. is
explicit that a critical is automatically successful whatever the
target says - the 05.01 FAQ confirms a 4+ critical threshold makes a 4
hit even when the BS needs a 5 - and equally explicit that an
unmodified 1 ALWAYS fails (05.01, 05.02).

Those two rules meet at the bottom of the die: the best a critical
threshold can ever be is 2+. "Critical on a 1+" is not a state the
rules can produce.

Regression this file anchors (see the handoff):

  * roll_probs built its face list from the RAW threshold while
    computing the critical probability from max(2, crit_on), so
    crit_on = 1 returned p_hit = 1.0 alongside p_crit = 5/6 - six faces
    hitting of which only five were critical, and the natural 1 among
    them. hit_threshold_mw_probs, three hundred lines away, had the
    right guard, so the same file disagreed with itself.
  * the threshold arrives from a FREE-TEXT field: the criticalThreshold
    effect reads one digit and so does the ANTI-X weapon keyword, both
    of which happily accept 1 or 0.

Both engines agreed on the wrong answer - the dice resolver reads the
same mech.crit_hit_on - so the parity sweep was quiet.

Every expected value below is written in closed form here, and each
claim carries an INVERSE check so the file cannot pass for the wrong
reason.
"""
import random

import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
import attack_resolve as ar
from unit_model import Weapon

TOL = 1e-12


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


# --- 1. the clamp itself ----------------------------------------------
for n in (2, 3, 4, 5, 6):
    assert am.crit_threshold(n) == n, n          # legal values untouched
for n in (1, 0, -3):
    assert am.crit_threshold(n) == 2, n          # floored at 2
# The ceiling is NOT clamped: every site lowers with min() from 6, so a
# threshold worse than 6 simply never fires and must stay that way.
assert am.crit_threshold(7) == 7
assert am.crit_threshold("4") == 4               # parse sites pass strings
# Garbage still raises, so parse_effect_strings can report the ability
# as unsupported instead of applying a threshold nobody asked for.
for bad in ("x", "", "4+"):
    try:
        am.crit_threshold(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"crit_threshold({bad!r}) should have raised")
print("the critical threshold is floored at 2+")


# --- 2. roll_probs against an independent oracle -----------------------
def oracle(target, mod, crit_on, unmod_min):
    """(p_hit, p_crit) from the rules, not from the engine.

    A face succeeds when it clears the unmodified floor AND is either a
    natural 6, or a critical, or beats the target once modified. A
    critical needs an unmodified crit_on+ with crit_on never better
    than 2. The natural 1 is absent from both lists by construction.
    """
    c = max(2, crit_on)
    ok = [r for r in range(2, 7)
          if r >= unmod_min and (r == 6 or r >= c or r + mod >= target)]
    return len(ok) / 6.0, len([r for r in ok if r >= c]) / 6.0


checked = 0
for target in range(2, 7):
    for mod in (-1, 0, 1):
        for crit_on in (-1, 0, 1, 2, 3, 4, 5, 6, 7):
            for unmod_min in (1, 4, 6):
                want = oracle(target, mod, crit_on, unmod_min)
                got = am.roll_probs(target, mod, None, crit_on=crit_on,
                                    unmod_min=unmod_min)
                assert abs(got[0] - want[0]) < TOL \
                    and abs(got[1] - want[1]) < TOL, \
                    (target, mod, crit_on, unmod_min, got, want)
                # Two invariants that hold for EVERY combination, and
                # that the regression broke: a critical is a success,
                # so its probability can never exceed the success one,
                # and the natural 1 can never be among the successes.
                assert got[1] <= got[0] + TOL, (target, mod, crit_on,
                                                unmod_min, got)
                assert got[0] <= 5 / 6 + TOL, (target, mod, crit_on,
                                               unmod_min, got)
                checked += 1
# INVERSE: the sweep must contain cases that are NOT saturated, or the
# two invariants above would hold trivially.
p6, c6 = am.roll_probs(4, 0, None, crit_on=6)
assert abs(p6 - 3 / 6) < TOL and abs(c6 - 1 / 6) < TOL
# ...and cases where a lowered threshold really does lift the hit rate,
# which is the 05.01 FAQ: a 4+ critical hits even when the BS wants 5+.
p5, _ = am.roll_probs(5, 0, None, crit_on=6)
p5c, c5c = am.roll_probs(5, 0, None, crit_on=4)
assert abs(p5 - 2 / 6) < TOL and abs(p5c - 3 / 6) < TOL, (p5, p5c)
assert abs(c5c - 3 / 6) < TOL
print(f"roll_probs matches the rules on {checked} combinations")


# --- 3. the mortal-wound branch uses the same floor --------------------
def oracle_mw(target, mod, thr, crit_on, unmod_min):
    c, top, floor = max(2, crit_on), max(2, thr), max(1, unmod_min)
    mw = [r for r in range(1, 7) if r >= top and r >= floor]
    hit = [r for r in range(2, 7)
           if r >= floor and r < top
           and (r == 6 or r >= c or r + mod >= target)]
    return (len(mw) / 6.0, len(hit) / 6.0,
            len([r for r in hit if r >= c]) / 6.0)


checked_mw = 0
for target in range(2, 7):
    for mod in (-1, 0, 1):
        for thr in (4, 5, 6):
            for crit_on in (0, 1, 2, 4, 6):
                for unmod_min in (1, 4, 6):
                    want = oracle_mw(target, mod, thr, crit_on, unmod_min)
                    got = am.hit_threshold_mw_probs(
                        target, mod, None, thr, crit_on=crit_on,
                        unmod_min=unmod_min)
                    assert all(abs(a - b) < TOL
                               for a, b in zip(got, want)), \
                        (target, mod, thr, crit_on, unmod_min, got, want)
                    # The natural 1 does nothing at all: it is neither a
                    # hit nor the mortal-wound branch, so the two bands
                    # together can never cover more than five faces.
                    assert got[0] + got[1] <= 5 / 6 + TOL, \
                        (target, mod, thr, crit_on, unmod_min, got)
                    # ...and the criticals are a subset of the hits.
                    assert got[2] <= got[1] + TOL, \
                        (target, mod, thr, crit_on, unmod_min, got)
                    checked_mw += 1
# INVERSE: the sweep must reach the case where a positive modifier would
# otherwise drag the natural 1 over a low target - that is the only
# place the guard on the die is doing work rather than the target check.
mw_lo = am.hit_threshold_mw_probs(2, 1, None, 6)
assert abs(mw_lo[0] + mw_lo[1] - 5 / 6) < TOL, mw_lo
print(f"the mortal-wound threshold branch agrees on {checked_mw} "
      f"combinations")


# --- 4. the parse sites clamp before the maths ever sees it ------------
for text, attr, want in (("CRITON HIT 1", "crit_hit_on", 2),
                         ("CRITON HIT 0", "crit_hit_on", 2),
                         ("CRITON HIT 4", "crit_hit_on", 4),
                         ("CRITON WOUND 1", "crit_wound_on", 2),
                         ("CRITON WOUND 3", "crit_wound_on", 3)):
    m = am.WeaponMechanics()
    am.parse_effect_strings([text], "Ranged", m)
    assert getattr(m, attr) == want and not m.warnings, \
        (text, getattr(m, attr), m.warnings)
# ANTI-X off the weapon keyword line, same floor.
m = am.WeaponMechanics()
am.parse_weapon_keywords(["ANTI-VEHICLE 1+", "ANTI-INFANTRY 4+"], m)
assert m.anti == [("VEHICLE", 2), ("INFANTRY", 4)], m.anti
assert not m.warnings, m.warnings
# "on an unmodified N+ the wound is always critical", same floor. The
# condition is a PREFIX on the effect string (_split_conditions), so it
# is written the way modifier_engine emits it.
for text, want in (("IF ROLL WOUND 1+ UNMOD: OVERRIDE WOUND ALWAYS CRIT", 2),
                   ("IF ROLL WOUND 0+ UNMOD: OVERRIDE WOUND ALWAYS CRIT", 2),
                   ("IF ROLL WOUND 5+ UNMOD: OVERRIDE WOUND ALWAYS CRIT", 5)):
    m = am.WeaponMechanics()
    am.parse_effect_strings([text], "Ranged", m)
    assert m.crit_wound_on == want and not m.warnings, \
        (text, m.crit_wound_on, m.warnings)
# A threshold that is not a number is still REPORTED, not guessed: the
# clamp must not swallow the ValueError the parser relies on.
m = am.WeaponMechanics()
am.parse_effect_strings(["CRITON HIT x"], "Ranged", m)
assert m.crit_hit_on == 6 and m.warnings, (m.crit_hit_on, m.warnings)
print("every threshold is clamped where it is parsed")


# --- 5. both engines, end to end ---------------------------------------
# S4 vs T8 wounds on 6+ only, so a critical wound threshold is the whole
# story: 6 attacks at BS4+ (3/6, the natural 1 fails anyway).
W = Weapon(name="p", wtype="Ranged", A="6", skill=4, S=4, AP=0, D="1",
           count=1)
REF = {"T": 8, "Sv": None, "W": 9, "invuln": None, "fnp": None,
       "models": 1, "keywords": ()}
for name, kw, want in (
        ("crit wound 6+ (plain)", {"crit_wound_on": 6}, 6 * .5 * (1 / 6)),
        ("crit wound 2+", {"crit_wound_on": 2}, 6 * .5 * (5 / 6)),
        ("crit wound 1+ -> floored to 2+", {"crit_wound_on": 1},
         6 * .5 * (5 / 6)),
        ("crit hit 1+ -> floored to 2+", {"crit_hit_on": 1},
         6 * (5 / 6) * (1 / 6))):
    m = mech(**kw)
    exact = am.analyze_weapon(W, REF, {}, m.copy())["damage"]["mean"]
    assert abs(exact - want) < 1e-9, f"{name}: {exact:.6f} != {want:.6f}"
    rng = random.Random(31337)
    tot = 0
    for _ in range(30000):
        tot += sum(e["amount"] for e in
                   ar.resolve_weapon(W, REF, {}, m.copy(), rng)["events"])
    assert abs(exact - tot / 30000) < 0.05, \
        f"{name}: exact={exact:.4f} dice={tot / 30000:.4f}"
# INVERSE: a threshold of 1+ must land on the SAME answer as 2+ and a
# DIFFERENT one from 6+, or the floor could be doing nothing.
one = am.analyze_weapon(W, REF, {}, mech(crit_wound_on=1))["damage"]["mean"]
two = am.analyze_weapon(W, REF, {}, mech(crit_wound_on=2))["damage"]["mean"]
six = am.analyze_weapon(W, REF, {}, mech(crit_wound_on=6))["damage"]["mean"]
assert abs(one - two) < TOL and one > six + 1.0, (one, two, six)

# The audit trail records "the numbers the chain ACTUALLY used", so a
# threshold the maths floored to 2+ must not be reported as 1+: that is
# precisely the drift the audit exists to prevent, and audit.py reads
# this field to decide whether to print an ANTI note at all.
for kw, where in ((("crit_hit_on", 1), "hit"), (("crit_wound_on", 1),
                                                "wound")):
    m = mech(**{kw[0]: kw[1]})
    rec = am.analyze_weapon(W, REF, {}, m)["audit"][where]
    assert rec["crit_on"] == 2, \
        f"the audit reports a critical threshold of {rec['crit_on']}+"
# INVERSE: a legal threshold reaches the audit unchanged, so the field
# is not simply pinned to 2.
assert am.analyze_weapon(W, REF, {}, mech(crit_hit_on=4))["audit"]["hit"][
    "crit_on"] == 4
assert am.analyze_weapon(W, REF, {}, mech())["audit"]["wound"][
    "crit_on"] == 6
print("both engines agree once the threshold is floored")

print("OK  test_crit_threshold")
