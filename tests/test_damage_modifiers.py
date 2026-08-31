"""Tests for the defender Damage-modifier flow (set / mult / add / floor).

Covers, in order:
  1. apply_damage_modifiers: the four fixed steps and their edge cases
     (rounding up, floor at 1, the set-to-zero special case), directly.
  2. Effect-string parsing: DMGREDUX set|mult|add and DMGSETZERO fold
     into the right WeaponMechanics fields.
  3. Exact maths <-> dice resolver parity, on the damage-modifier chain
     specifically: the analytic PMF matches the dice resolver, mean and
     whole distribution, within the statistical tolerance of mc_support
     (SIGMA standard errors, the error computed from the exact
     variance). The broad sweep over every mechanic lives in
     test_mc_parity; this file keeps the damage chain covered where its
     own unit tests are.

Self-contained: builds tiny synthetic weapons/defenders, no roster data.
"""
import unittest

import testpaths                      # sets up sys.path to the engine src/

import attack_math as am
import mc_support as mcs
from unit_model import Weapon


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


class TestFiveStepOrder(unittest.TestCase):
    """The three places the five-step order of Rules Appendix 02.02.01
    disagrees with the four-step model that preceded it. Every value is
    worked out by hand from the rulebook order:

        set -> multiply -> add -> divide -> subtract -> round up once
    """

    @staticmethod
    def _mech(**kw):
        m = am.WeaponMechanics()
        for name, value in kw.items():
            setattr(m, name, value)
        return m

    def _row(self, mech, melta=0):
        return [am.apply_damage_modifiers(d, mech, melta)
                for d in range(1, 9)]

    def test_melta_survives_a_set(self):
        # MELTA is an addition (step 3) and the set is step 1, so the
        # bonus is added to the value the set left: 1 + 2 = 3, at every
        # base Damage. Convolving the bonus in before the chain deleted
        # it and gave 1.
        self.assertEqual(self._row(self._mech(dmg_set=1), melta=2), [3] * 8)

    def test_a_positive_modifier_lands_before_the_halving(self):
        # +2 at step 3, halve at step 4: ceil((D + 2) / 2). Halving
        # first and adding afterwards gives one MORE at every D.
        self.assertEqual(self._row(self._mech(dmg_div=0.5, dmg_add=2)),
                         [2, 2, 3, 3, 4, 4, 5, 5])

    def test_rounding_happens_once_at_the_end(self):
        # halve then subtract 1 on D = 5: 2.5 - 1 = 1.5 -> 2. Rounding
        # after the halving would give 3 - 1 = 2 as well, which is why
        # this pair alone never exposed the difference; the assertion is
        # here so a future reader does not mistake that for luck.
        self.assertEqual(self._row(self._mech(dmg_div=0.5, dmg_sub=-1)),
                         [1, 1, 1, 1, 2, 2, 3, 3])

    def test_the_old_shapes_are_unmoved(self):
        # Everything the shipped rosters contain: a halving, a -1, and a
        # melta into either. All identical to the four-step answers.
        self.assertEqual(self._row(self._mech(dmg_div=0.5), melta=2),
                         [2, 2, 3, 3, 4, 4, 5, 5])
        self.assertEqual(self._row(self._mech(dmg_sub=-1)),
                         [1, 1, 2, 3, 4, 5, 6, 7])

    def test_a_set_to_zero_stops_the_chain(self):
        # 02.02.01: a characteristic set to 0 cannot be modified by
        # anything else, so neither the melta nor the addition revives
        # it.
        self.assertEqual(
            self._row(self._mech(dmg_set=0, dmg_add=5), melta=3), [0] * 8)


class TestEffectStringParsing(unittest.TestCase):
    def _parse(self, s):
        m = am.WeaponMechanics()
        am.parse_effect_strings([s], "Ranged", m, weapon=None)
        return m

    def test_add_default_and_explicit(self):
        # 'add -1' is the datasheet's "reduce the Damage by 1", which the
        # rules resolve at step 5, not step 3: the sign picks the step.
        m = self._parse("DMGREDUX add -1")
        self.assertEqual(m.dmg_sub, -1)
        self.assertEqual(m.dmg_add, 0)
        self.assertIsNone(m.dmg_set)
        self.assertEqual(m.dmg_mult, 1.0)
        self.assertEqual(m.dmg_div, 1.0)

    def test_add_positive_is_a_real_addition(self):
        m = self._parse("DMGREDUX add 2")
        self.assertEqual(m.dmg_add, 2)
        self.assertEqual(m.dmg_sub, 0)

    def test_mult_factor(self):
        # 'mult 0.5' is "halve the Damage", a DIVISION (step 4).
        m = self._parse("DMGREDUX mult 0.5")
        self.assertEqual(m.dmg_div, 0.5)
        self.assertEqual(m.dmg_mult, 1.0)

    def test_mult_above_one_is_a_real_multiplication(self):
        m = self._parse("DMGREDUX mult 2")
        self.assertEqual(m.dmg_mult, 2.0)
        self.assertEqual(m.dmg_div, 1.0)

    def test_set_keeps_best_lowest(self):
        m = am.WeaponMechanics()
        am.parse_effect_strings(["DMGREDUX set 3", "DMGREDUX set 2"],
                                "Ranged", m, weapon=None)
        self.assertEqual(m.dmg_set, 2)

    def test_multiple_mult_are_cumulative(self):
        m = am.WeaponMechanics()
        am.parse_effect_strings(["DMGREDUX mult 0.5", "DMGREDUX mult 0.5"],
                                "Ranged", m, weapon=None)
        self.assertEqual(m.dmg_div, 0.25)

    def test_incoming_damage_modifier_splits_by_sign(self):
        # A modifier on the incoming D reaches the same two steps, so the
        # sign rule cannot be dodged by writing it as a characteristic
        # modifier instead of a DMGREDUX.
        worse = self._parse("CHARMOD D 1")
        self.assertEqual((worse.dmg_add, worse.dmg_sub), (1, 0))
        better = self._parse("CHARMOD D -1")
        self.assertEqual((better.dmg_add, better.dmg_sub), (0, -1))

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


class TestExactVsDiceParity(unittest.TestCase):
    """The analytic PMF must match the dice resolver under the same
    damage modifiers. The tolerance is statistical, not a guess: the
    standard error comes from the exact variance, and mc_support.SIGMA
    says how many of them are allowed (see mc_support for the knobs and
    for why the CDF check is corrected for the number of points)."""

    def _check(self, mech):
        w, ref = _weapon(), _defender()
        ok, msg = mcs.check_weapon(self._testMethodName, w, ref,
                                   {"half_range": False}, mech)
        self.assertTrue(ok, msg)

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
