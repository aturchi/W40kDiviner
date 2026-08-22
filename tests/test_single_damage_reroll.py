"""ONE Damage re-roll per activation (Aquilon Optics and the like).

The hit and wound versions of this ability ADD a die: every failed hit
roll is interchangeable, so re-rolling one is exactly one more attack
convolved in, and the maths is exact. The Damage version REPLACES a
result, which is a different problem altogether - see
attack_math._damage_single_total.

What is checked here:

  1. closed form. On a weapon that always hits, always wounds and gets
     no save, the gain is computable by hand, so the chain is compared
     against a number worked out on paper rather than against itself.
  2. mass and positivity. The chain subtracts one sub-probability law
     from another, which is exactly where a sign error would hide.
  3. multi-dice Damage. 2D6 must spend ONE re-roll between the two
     dice, not one each - that case is exact, not approximate.
  4. the two degenerate cases: a flat Damage characteristic has no roll
     to re-roll, and a weapon that already re-rolls low Damage dice has
     nothing left to buy (a die may be re-rolled once). Both must warn
     and change nothing.
  5. parity with the dice resolver, and the SIZE of the one declared
     approximation - measured, so that a future change that makes it
     worse shows up as a failure rather than as a slightly different
     number nobody looks at.

No tkinter needed.
"""
import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
import mc_support as mcs
from unit_model import Weapon


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


REF = {"T": 4, "Sv": 4, "W": 6, "invuln": None, "fnp": None,
       "models": 1, "keywords": set()}
# always hits (BS 2+ with no modifiers still misses on a 1, so the
# closed form below uses the real probabilities instead of assuming 1).
SOFT = {"T": 1, "Sv": 7, "W": 20, "invuln": None, "fnp": None,
        "models": 1, "keywords": set()}


def gun(D, A="4", skill=3, S=5, AP=-1):
    return Weapon(name="g", wtype="Ranged", A=A, skill=skill, S=S, AP=AP,
                  D=D, count=1)


def mean(weapon, m, ref=REF, ctx=None):
    return am.analyze_weapon(weapon, ref, ctx or {}, m)["damage"]["mean"]


# --- 1. the gain, worked out on paper ---------------------------------
# One attack, D6 damage. A D6 is worth re-rolling on 1-3 (below the 3.5
# mean, see damage_reroll_range), so:
#   p(spend)  = p(the attack damages) * P(die in 1..3) = p * 1/2
#   gain      = E[D6] - E[D6 | 1..3] = 3.5 - 2 = 1.5
# and over n attacks the re-roll is spent exactly when at least one of
# them produced a low die.
# probability that ONE attack deals damage: read it off the per-attack
# 'wounds' chain the engine itself built, so the check does not re-derive
# the hit/wound/save probabilities and merely repeat a possible mistake.
one = am.analyze_weapon(gun("D6", A="1"), REF, {}, mech())
p_one = 1.0 - one["wounds_pmf"][0]
for n in (1, 2, 4):
    got = mean(gun("D6", A=str(n)), mech(single_reroll="damage"))
    flat = mean(gun("D6", A=str(n)), mech())
    p_spend = p_one * 0.5
    expected = flat + (1.0 - (1.0 - p_spend) ** n) * 1.5
    assert abs(got - expected) < 1e-9, (n, got, expected)
print("the gain matches the closed form, attack by attack")


# --- 2. it is still a probability distribution -------------------------
for D, A in (("D6", "4"), ("2D6", "2"), ("D3", "6"), ("D6+1", "4")):
    res = am.analyze_weapon(gun(D, A), REF, {},
                            mech(single_reroll="damage"))
    for key in ("damage", "damage_net", "wounds"):
        pmf = res[key + "_pmf"]
        assert abs(sum(pmf) - 1.0) < 1e-12, (D, key, sum(pmf))
        assert min(pmf) >= 0.0, (D, key, min(pmf))
    # it can only help
    assert res["damage"]["mean"] >= mean(gun(D, A), mech()) - 1e-12
print("the three totals stay proper distributions, and the gain is a gain")


# --- 3. multi-dice Damage spends ONE re-roll, not one per die ----------
# 2D6: P(at least one die in 1..3) = 3/4, and the first such die is
# replaced by a fresh D6 - gain 1.5, not 3.0.
two = am.analyze_weapon(gun("2D6", A="1"), REF, {},
                        mech(single_reroll="damage"))["damage"]["mean"]
two_flat = mean(gun("2D6", A="1"), mech())
assert abs((two - two_flat) - p_one * 0.75 * 1.5) < 1e-9, (two, two_flat)
print("a 2D6 Damage roll spends one re-roll between its two dice")


# --- 4. the two cases where it buys nothing ---------------------------
fist = Weapon(name="fist", wtype="Melee", A="3", skill=3, S=6, AP=-1,
              D="2", count=1)
res = am.analyze_weapon(fist, REF, {}, mech(single_reroll="damage"))
assert abs(res["damage"]["mean"] - mean(fist, mech())) < 1e-12
assert any("flat Damage" in w for w in res["warnings"]), res["warnings"]

res = am.analyze_weapon(gun("D6"), REF, {},
                        mech(single_reroll="damage", dmg_reroll_any=True))
assert abs(res["damage"]["mean"]
           - mean(gun("D6"), mech(dmg_reroll_any=True))) < 1e-12
assert any("only once" in w for w in res["warnings"]), res["warnings"]
print("a flat Damage, or one already re-rolled, warns and changes nothing")


# --- 5. parity with the dice, and the size of the approximation -------
# The declared approximation is that an attack producing SEVERAL damage
# events re-rolls a low die in each, where the rules allow one. The bias
# is upward; these are the numbers, so a change that makes it worse
# fails here instead of passing quietly.
# The band is widened by the Monte Carlo's own standard error, three
# sigma of it: without that the test would be measuring the sampling
# noise as if it were the approximation, and would fail on a new seed.
TRIALS = 60000
for name, extra, limit in (("plain", {}, 0.005),
                           ("sustained 1", {"sustained": 1}, 0.02),
                           ("sustained 3", {"sustained": 3}, 0.05)):
    m = mech(single_reroll="damage", **extra)
    exact = am.analyze_weapon(gun("D6"), REF, {}, m)["damage"]["mean"]
    samples = mcs.sample_damage(gun("D6"), REF, {}, m, trials=TRIALS,
                                seed=20260822)
    dice = sum(samples) / len(samples)
    var = sum((v - dice) ** 2 for v in samples) / (len(samples) - 1)
    noise = 3.0 * (var / len(samples)) ** 0.5 / dice
    bias = (exact - dice) / dice
    assert bias > -noise, (name, bias, noise)      # never BELOW the dice
    assert bias < limit + noise, (name, bias, limit, noise)
print("dice parity holds, and the declared bias stays the size it should")

# and with no bonus events at all the two engines agree outright
for label, D, A in (("D6", "D6", "4"), ("2D6", "2D6", "2"),
                    ("D3", "D3", "6")):
    ok, msg = mcs.check_weapon(label, gun(D, A), REF, {},
                               mech(single_reroll="damage"),
                               trials=40000, seed=99)
    assert ok, msg
print("exact and dice agree on every single-event profile")

print("OK: one Damage re-roll per activation")
