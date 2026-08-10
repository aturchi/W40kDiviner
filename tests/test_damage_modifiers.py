"""Tests for the defender Damage-modifier flow (set / mult / add / floor).

Covers, in order:
  1. apply_damage_modifiers: the four fixed steps and their edge cases
     (rounding up, floor at 1, the set-to-zero special case), directly.
  2. Effect-string parsing: DMGREDUX set|mult|add and DMGSETZERO fold
     into the right WeaponMechanics fields.
  3. Exact maths <-> dice resolver parity: the analytic mean damage
     under a modifier matches the Monte-Carlo mean of the dice resolver
     (the two engines must never diverge on rules interpretation).

Self-contained: builds tiny synthetic weapons/defenders, no roster data.
"""
import math
import random
import unittest

import testpaths                      # sets up sys.path to the engine src/

import attack_math as am
from unit_model import Weapon
from characteristics import Characteristic


def _mech(**kw):
    """A WeaponMechanics with the given damage-modifier fields set."""
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


class TestApplyDamageModifiers(unittest.TestCase):
    def test_no_modifier_is_identity(self):
        m = _mech()
        self.assertFalse(am.has_damage_modifiers(m))
        for d in range(0, 7):
            self.assertEqual(am.apply_damage_modifiers(d, m), d)

    def test_zero_damage_stays_zero(self):
        # A missed attack (0 damage) is never lifted to 1 by the floor.
        m = _mech(dmg_add=-3, dmg_mult=0.5, dmg_set=5)
        self.assertEqual(am.apply_damage_modifiers(0, m), 0)

    def test_add_is_a_reduction_floored_at_one(self):
        m = _mech(dmg_add=-1)
        self.assertEqual(am.apply_damage_modifiers(3, m), 2)
        self.assertEqual(am.apply_damage_modifiers(1, m), 1)   # floor
        self.assertEqual(am.apply_damage_modifiers(2, m), 1)

    def test_mult_rounds_up(self):
        # GW halving rounds fractions UP.
        m = _mech(dmg_mult=0.5)
        self.assertEqual(am.apply_damage_modifiers(6, m), 3)
        self.assertEqual(am.apply_damage_modifiers(5, m), 3)   # 2.5 -> 3
        self.assertEqual(am.apply_damage_modifiers(1, m), 1)   # 0.5 -> 1

    def test_fixed_order_set_then_mult_then_add(self):
        # set 6 -> mult 0.5 (=>3) -> add -1 (=>2) -> floor(2)=2
        m = _mech(dmg_set=6, dmg_mult=0.5, dmg_add=-1)
        self.assertEqual(am.apply_damage_modifiers(1, m), 2)
        # The input value is irrelevant once 'set' fires:
        self.assertEqual(am.apply_damage_modifiers(99, m), 2)

    def test_order_is_independent_of_declaration(self):
        # add then mult must still be evaluated mult-first:
        # D=4 -> mult .5 (=>2) -> add +1 (=>3), NOT (4+1)*.5=3 by luck,
        # so use a case that separates them: D=3, add -1, mult .5.
        # mult-first: ceil(3*.5)=2, then -1 => 1 (floor 1).
        # add-first (wrong): (3-1)=2, *.5 => 1. Distinguish with D=5:
        # mult-first: ceil(5*.5)=3, -1 => 2 ; add-first: (5-1)=4,*.5=2 -> same.
        # Use add -2 to separate: mult-first ceil(5*.5)=3,-2=1(floor1);
        # add-first (5-2)=3,*.5=ceil1.5=2. Expect the mult-first result.
        m = _mech(dmg_mult=0.5, dmg_add=-2)
        self.assertEqual(am.apply_damage_modifiers(5, m), 1)

    def test_set_zero_bypasses_floor(self):
        m = _mech(dmg_set_zero=True)
        self.assertEqual(am.apply_damage_modifiers(4, m), 0)
        # set_zero wins even alongside other modifiers:
        m2 = _mech(dmg_add=+5, dmg_set_zero=True)
        self.assertEqual(am.apply_damage_modifiers(4, m2), 0)


class TestEffectStringParsing(unittest.TestCase):
    def _parse(self, s):
        m = am.WeaponMechanics()
        am.parse_effect_strings([s], "Ranged", m, weapon=None)
        return m

    def test_add_default_and_explicit(self):
        m = self._parse("DMGREDUX add -1")
        self.assertEqual(m.dmg_add, -1)
        self.assertIsNone(m.dmg_set)
        self.assertEqual(m.dmg_mult, 1.0)

    def test_mult_factor(self):
        m = self._parse("DMGREDUX mult 0.5")
        self.assertEqual(m.dmg_mult, 0.5)

    def test_set_keeps_best_lowest(self):
        m = am.WeaponMechanics()
        am.parse_effect_strings(["DMGREDUX set 3", "DMGREDUX set 2"],
                                "Ranged", m, weapon=None)
        self.assertEqual(m.dmg_set, 2)

    def test_multiple_mult_are_cumulative(self):
        m = am.WeaponMechanics()
        am.parse_effect_strings(["DMGREDUX mult 0.5", "DMGREDUX mult 0.5"],
                                "Ranged", m, weapon=None)
        self.assertEqual(m.dmg_mult, 0.25)

    def test_set_zero_token(self):
        m = self._parse("DMGSETZERO")
        self.assertTrue(m.dmg_set_zero)


def _weapon(dmg="2", attacks="10"):
    """A trivial high-Strength, high-AP weapon (S8 AP-4 vs T4 Sv6+):
    reliably hits and wounds so the Damage-modifier maths is isolated."""
    return Weapon(name="synthetic", wtype="Ranged", A=attacks, skill=2,
                  S=8, AP=-4, D=dmg, count=1)


def _defender():
    # No save (Sv far worse than AP), no invuln/fnp: every attack lands,
    # isolating the Damage-modifier maths.
    return {"T": 4, "Sv": 6, "W": 4, "invuln": None, "fnp": None,
            "models": 1, "keywords": set()}


def _mc_mean_damage(weapon, ref, mech, trials=40000, seed=1):
    """Monte-Carlo mean gross damage from the dice resolver."""
    import attack_resolve as ar
    rng = random.Random(seed)
    tot = 0
    for _ in range(trials):
        res = ar.resolve_weapon(weapon, ref, {"half_range": False},
                                _clone_mech(mech), rng)
        tot += sum(e["amount"] for e in res["events"]
                   if e["kind"] == "damage")
    return tot / trials


def _clone_mech(mech):
    """Fresh mechanics copy so the resolver can't mutate the shared one."""
    m = am.WeaponMechanics()
    m.__dict__.update(mech.__dict__)
    m.__dict__["ignore_malus"] = set(mech.ignore_malus)
    m.__dict__["anti"] = list(mech.anti)
    m.__dict__["warnings"] = []
    return m


class TestExactVsDiceParity(unittest.TestCase):
    """The analytic mean must match the dice resolver's mean under the
    same damage modifiers (loose tolerance: Monte-Carlo noise)."""

    def _check(self, mech, tol=0.06):
        w, ref = _weapon(), _defender()
        exact = am.analyze_weapon(w, ref, {"half_range": False},
                                  _clone_mech(mech))
        exact_mean = exact["damage"]["mean"]
        mc_mean = _mc_mean_damage(w, ref, mech)
        self.assertAlmostEqual(exact_mean, mc_mean, delta=max(tol, tol * exact_mean),
                               msg=f"exact={exact_mean:.3f} mc={mc_mean:.3f}")

    def test_plain(self):
        self._check(_mech())

    def test_add_minus_one(self):
        self._check(_mech(dmg_add=-1))

    def test_halve(self):
        self._check(_mech(dmg_mult=0.5))

    def test_full_chain(self):
        self._check(_mech(dmg_set=6, dmg_mult=0.5, dmg_add=-1))

    def test_set_zero_is_zero(self):
        w, ref = _weapon(), _defender()
        exact = am.analyze_weapon(w, ref, {"half_range": False},
                                  _mech(dmg_set_zero=True))
        self.assertEqual(exact["damage"]["mean"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
