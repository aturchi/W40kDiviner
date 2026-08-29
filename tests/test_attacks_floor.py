"""The Attacks characteristic: every modifier first, then the limit.

The Rules Appendix (02.02.01) is explicit about the order. All the
modifiers to a characteristic are applied - change/replace, multiply,
add, divide, subtract - and only THEN are the limits enforced, of which
"A cannot be less than 1" is one.

RAPID FIRE X, BLAST X, CLEAVE X and "X extra attacks" all add to the
same Attacks characteristic, and a defender ability can subtract from
it ("subtract 1 from the Attacks characteristic of that attack"). So
the floor belongs on the TOTAL:

    A 1, -1 from the defender, RAPID FIRE 1 at half range
      rules:  1 - 1 + 1        = 1
      before: max(1, 1 - 1) + 1 = 2

Regression this file anchors (see the handoff): both engines clamped
the datasheet value the moment the defender's modifier was applied and
only then added the extras, so a weapon whose Attacks had been reduced
to zero or below still collected its Rapid Fire and Blast bonuses on
top of a floor of 1. Both engines did it the same way, so the parity
sweep was quiet - the only way to see it is against the rules.

The floor is applied only when there IS a modifier to apply. Without
one the total is the datasheet's own value plus non-negative extras,
which cannot fall below it, so nothing is clamped and a weapon with no
Attacks at all keeps behaving as it did.

Every expected value below is written in closed form here, and each
claim carries an INVERSE check.
"""
import random

import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
import attack_resolve as ar
from unit_model import Weapon

TOL = 1e-9

# A target that cannot survive and cannot save, so the mean damage IS
# the mean number of attacks: BS2+ hits 5/6, S10 vs T1 wounds on 2+
# (another 5/6), AP-6 against no save, D1 against W99.
REF = {"T": 1, "Sv": None, "W": 99, "invuln": None, "fnp": None,
       "models": 10, "keywords": ()}
HIT_WOUND = (5 / 6) * (5 / 6)


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def gun(a="1", count=1):
    return Weapon(name="gun", wtype="Ranged", A=a, skill=2, S=10, AP=-6,
                  D="1", count=count)


def attacks(weapon, ctx, m):
    return am.analyze_weapon(weapon, REF, ctx, m.copy())["attacks"]["mean"]


# --- 1. the floor lands on the total ----------------------------------
HALF = {"half_range": True}
CASES = [
    # (name, A, attacks_mod, mechanics, ctx, expected attacks per copy)
    ("A1, -1, RAPID FIRE 1 at half", "1", -1, {"rapid_fire": 1}, HALF, 1),
    ("A2, -2, RAPID FIRE 1 at half", "2", -2, {"rapid_fire": 1}, HALF, 1),
    ("A1, -1, BLAST 1 vs 10 models", "1", -1, {"blast": 1}, {}, 2),
    ("A1, -1, 2 extra attacks", "1", -1, {"extra_attacks": 2}, {}, 2),
    ("A3, -1, RAPID FIRE 2 at half", "3", -1, {"rapid_fire": 2}, HALF, 4),
    ("A1, -5, BLAST 1 vs 10 models", "1", -5, {"blast": 1}, {}, 1),
    # ...and with no modifier at all nothing is clamped, so the extras
    # simply add on as before.
    ("A1, RAPID FIRE 1 at half", "1", 0, {"rapid_fire": 1}, HALF, 2),
    ("A2, BLAST 1 vs 10 models", "2", 0, {"blast": 1}, {}, 4),
    ("A1, -1, no extras", "1", -1, {}, {}, 1),
    ("A4, -1, no extras", "4", -1, {}, {}, 3),
]
for name, a, amod, kw, ctx, want in CASES:
    m = mech(attacks_mod=amod, **kw)
    got = attacks(gun(a), ctx, m)
    assert abs(got - want) < TOL, f"{name}: {got} != {want}"
# INVERSE: the old order is a DIFFERENT number on the reduced cases, so
# they cannot pass under both readings. max(1, A + mod) + extras.
for name, a, amod, kw, ctx, want in CASES[:4]:
    old = max(1, int(a) + amod) + (
        kw.get("rapid_fire", 0) if ctx.get("half_range") else 0
    ) + kw.get("blast", 0) * (REF["models"] // 5) + kw.get("extra_attacks", 0)
    assert old != want, f"{name}: the two orders agree, so it proves nothing"
print("the Attacks floor is applied after every modifier")


# --- 2. per weapon COPY, not per activation ---------------------------
# The characteristic belongs to the weapon, so three copies of a weapon
# reduced to its floor make three attacks and not one.
m = mech(attacks_mod=-1, rapid_fire=1)
assert abs(attacks(gun("1", count=3), HALF, m) - 3) < TOL
# INVERSE: without the modifier the same three copies make six.
assert abs(attacks(gun("1", count=3), HALF, mech(rapid_fire=1)) - 6) < TOL


# --- 3. a dice Attacks characteristic ---------------------------------
# A D6 with -1 and RAPID FIRE 1 at half range: each face v becomes
# max(1, v + 1 - 1) = v, so the mean is 3.5. Under the old order it was
# max(1, v - 1) + 1, i.e. 2,2,3,4,5,6 -> 3.6667.
got = attacks(gun("D6"), HALF, mech(attacks_mod=-1, rapid_fire=1))
assert abs(got - 3.5) < TOL, got
assert abs(got - (2 + 2 + 3 + 4 + 5 + 6) / 6) > 0.1, \
    "the old order and the new one agree, so this case proves nothing"
# A D3 with -2 and BLAST 1 against 10 models: faces 1,2,3 become
# max(1, v + 2 - 2) = v, mean 2.
got = attacks(gun("D3"), {}, mech(attacks_mod=-2, blast=1))
assert abs(got - 2.0) < TOL, got
print("a dice Attacks characteristic is clamped face by face on the total")


# --- 4. the dice resolver draws the same number -----------------------
for name, a, amod, kw, ctx, want in CASES:
    m = mech(attacks_mod=amod, **kw)
    rng = random.Random(4242)
    tot = sum(ar.resolve_weapon(gun(a), REF, ctx, m.copy(), rng)["attacks"]
              for _ in range(3000))
    assert abs(tot / 3000 - want) < 1e-9, \
        f"{name}: dice={tot / 3000} exact={want}"
# ...and with a dice characteristic, where the resolver rolls it.
m = mech(attacks_mod=-1, rapid_fire=1)
rng = random.Random(77)
tot = sum(ar.resolve_weapon(gun("D6"), REF, HALF, m.copy(), rng)["attacks"]
          for _ in range(60000))
assert abs(tot / 60000 - 3.5) < 0.03, tot / 60000
print("the dice resolver clamps in the same place")


# --- 5. end to end, both engines --------------------------------------
for name, a, amod, kw, ctx, want in CASES:
    m = mech(attacks_mod=amod, **kw)
    exact = am.analyze_weapon(gun(a), REF, ctx, m.copy())["damage"]["mean"]
    assert abs(exact - want * HIT_WOUND) < TOL, \
        f"{name}: damage {exact} != {want * HIT_WOUND}"
    rng = random.Random(2026)
    tot = 0
    for _ in range(20000):
        tot += sum(e["amount"] for e in
                   ar.resolve_weapon(gun(a), REF, ctx, m.copy(),
                                     rng)["events"])
    assert abs(exact - tot / 20000) < 0.05, \
        f"{name}: exact={exact:.4f} dice={tot / 20000:.4f}"
print("both engines agree on the damage once the floor moves")


# --- 6. a weapon with no Attacks at all -------------------------------
# The floor is applied only when there IS a modifier to apply. A weapon
# whose Attacks characteristic is '-' or 0 makes no attacks, and must
# keep making none: clamping it unconditionally would turn a weapon
# that cannot be fired into one that fires once. (The appendix says a
# characteristic set to '0', '-' or '*' is not modified further at all,
# which is the same answer by a shorter route.)
for a in ("0", "-"):
    assert abs(attacks(gun(a), {}, mech()) - 0.0) < TOL, a
    assert abs(attacks(gun(a), HALF, mech(rapid_fire=2)) - 2.0) < TOL, a
    rng = random.Random(5)
    tot = sum(ar.resolve_weapon(gun(a), REF, {}, mech(), rng)["attacks"]
              for _ in range(500))
    assert tot == 0, (a, tot)
# INVERSE: with a modifier present the floor DOES bite, so the gate is
# a gate and not a way of never clamping.
assert abs(attacks(gun("0"), {}, mech(attacks_mod=-1)) - 1.0) < TOL
print("a weapon with no Attacks characteristic still makes none")


# --- 7. the audit reports the attacks the chain used ------------------
# A2 with -1 and BLAST 1 against 10 models is 2 - 1 + 2 = 3, while the
# datasheet value alone averages 2: the two numbers differ, so the
# field cannot pass by reporting the raw characteristic.
rec = am.analyze_weapon(gun("2"), REF, {},
                        mech(attacks_mod=-1, blast=1))["audit"]
assert abs(rec["attacks"]["mean"] - 3) < TOL, rec["attacks"]
assert abs(am.pmf_stats(am.char_pmf(gun("2").A))["mean"] - 2) < TOL
assert rec["attacks"]["mod"] == -1, rec["attacks"]
assert rec["attacks"]["blast"] == 1, rec["attacks"]
# ...and the rapid-fire field is the one actually applied, so it is 0
# when the attack is not at half range.
assert am.analyze_weapon(gun("1"), REF, {}, mech(rapid_fire=1))[
    "audit"]["attacks"]["rapid_fire"] == 0
assert am.analyze_weapon(gun("1"), REF, HALF, mech(rapid_fire=1))[
    "audit"]["attacks"]["rapid_fire"] == 1
print("the audit trail shows the attacks the chain actually used")

print("OK  test_attacks_floor")
