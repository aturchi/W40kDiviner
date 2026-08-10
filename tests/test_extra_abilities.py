"""Tests for core_abilities / faction_abilities being first-class.

Run:  python3 tests/test_extra_abilities.py
No tkinter needed. Validates on synthetic units that: (1) native_format
normalises legacy name-string lists into ability dicts on load;
(2) the engine folds core/faction abilities into the unit's abilities so
every dynamic applies to them alike; (3) ids are stamped on them; and
(4) the merge diff routes them into the ability bucket and can apply.
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

import native_format as nf   # noqa: E402
import unit_model as um      # noqa: E402
import ability_ids           # noqa: E402
import profile_diff as pd    # noqa: E402


def _unit(core=None, faction=None, abilities=None):
    """A minimal but valid native unit dict with one model."""
    return {
        "name": "U", "profile_name": "U", "points": 10,
        "keywords": [], "abilities": abilities or [],
        "core_abilities": core if core is not None else [],
        "faction_abilities": faction if faction is not None else [],
        "leadership": [], "support": [],
        "leader_effects": [], "apply_leader_effects_to_self": False,
        "damageable": False, "unit_composition": "", "wargear_options": "",
        "notes": "",
        "models": [{"name": "m", "model_count": 1, "M": 6, "T": 4, "Sv": 3,
                    "W": 2, "LD": 6, "OC": 1, "invuln": None, "fnp": None,
                    "keywords": [], "abilities": [], "weapons": []}],
    }


class TestNormalize(unittest.TestCase):
    def test_load_wraps_name_strings(self):
        # legacy shape: bare name strings (as older ArmyFetcher emitted)
        data = {"format": "w40k-sim/6", "armies": [{"name": "a", "units": [
            _unit(core=["Deep Strike"], faction=["Oath of Moment"])]}]}
        out = nf.migrate(copy.deepcopy(data))
        u = out["armies"][0]["units"][0]
        for key, name in (("core_abilities", "Deep Strike"),
                          ("faction_abilities", "Oath of Moment")):
            self.assertTrue(all(isinstance(a, dict) for a in u[key]))
            ab = u[key][0]
            self.assertEqual(ab["name"], name)
            self.assertFalse(ab["enabled"])          # inert until structured
            self.assertEqual(ab["effect"]["type"], "special")

    def test_normalize_is_idempotent_and_defaults(self):
        good = nf.wrap_ability("Stealth")
        u = _unit(core=[good])
        del u["faction_abilities"]                    # missing key
        data = {"format": "w40k-sim/6",
                "armies": [{"name": "a", "units": [u]}]}
        out = nf.migrate(data)
        uu = out["armies"][0]["units"][0]
        self.assertEqual(uu["core_abilities"], [good])   # dict left untouched
        self.assertEqual(uu["faction_abilities"], [])    # missing -> []


class TestEngineFold(unittest.TestCase):
    def test_core_faction_fold_into_abilities(self):
        core = nf.wrap_ability("Deep Strike")
        fac = nf.wrap_ability("Oath of Moment")
        base = nf.wrap_ability("Astartes")
        native = {"format": nf.FORMAT_TAG, "armies": [{"name": "a", "units": [
            _unit(core=[core], faction=[fac], abilities=[base])]}]}
        unit = um.units_from_native(native)[0]
        names = [a.get("name") for a in unit.abilities]
        self.assertEqual(names, ["Astartes", "Deep Strike", "Oath of Moment"])

    def test_equivalent_to_a_plain_unit_ability(self):
        # the same ability, placed in `abilities` vs in `core_abilities`,
        # reaches the engine identically
        ab = nf.wrap_ability("X")
        a = um.units_from_native({"format": nf.FORMAT_TAG, "armies": [
            {"name": "a", "units": [_unit(abilities=[copy.deepcopy(ab)])]}]})[0]
        b = um.units_from_native({"format": nf.FORMAT_TAG, "armies": [
            {"name": "a", "units": [_unit(core=[copy.deepcopy(ab)])]}]})[0]
        self.assertEqual([x.get("name") for x in a.abilities],
                         [x.get("name") for x in b.abilities])

    def test_tolerates_legacy_strings_without_load(self):
        # a caller that bypasses native_format.load() must not crash the
        # engine on name-string entries
        native = {"units": [_unit(core=["Stealth"], faction=["Oath"])]}
        unit = um.units_from_native(native)[0]
        self.assertTrue(all(isinstance(a, dict) for a in unit.abilities))
        self.assertIn("Stealth", [a["name"] for a in unit.abilities])


class TestIds(unittest.TestCase):
    def test_ensure_ids_stamps_core_faction(self):
        data = {"format": nf.FORMAT_TAG, "armies": [{"name": "a", "units": [
            _unit(core=[nf.wrap_ability("Deep Strike")],
                  faction=[nf.wrap_ability("Oath of Moment")])]}]}
        ability_ids.ensure_ids(data)
        u = data["armies"][0]["units"][0]
        self.assertTrue(u["core_abilities"][0]["id"])
        self.assertTrue(u["faction_abilities"][0]["id"])


class TestMergeDiff(unittest.TestCase):
    def test_core_faction_changes_go_to_ability_bucket(self):
        u1 = _unit()
        u2 = _unit(core=[nf.wrap_ability("Deep Strike")],
                   faction=[nf.wrap_ability("Oath of Moment")])
        _other, ab_changes = pd.diff_unit(u1, u2)
        labels = [c.label for c in ab_changes]
        self.assertTrue(any("[core]" in l and "Deep Strike" in l
                            for l in labels))
        self.assertTrue(any("[faction]" in l and "Oath of Moment" in l
                            for l in labels))
        # applying the changes converges u1 to u2's extra-ability lists
        for c in ab_changes:
            pd.apply_change(u1, c)
        self.assertEqual([a["name"] for a in u1["core_abilities"]],
                         ["Deep Strike"])
        self.assertEqual([a["name"] for a in u1["faction_abilities"]],
                         ["Oath of Moment"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
