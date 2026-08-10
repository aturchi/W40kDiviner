"""Unit tests for src/profile_diff.py (pure diff/merge logic).

Run:  python3 tests/test_profile_diff.py
No tkinter needed. Validates on synthetic armies, with the central
invariant that accepting ALL changes of a modified unit converges it to
the v2 unit (diff becomes empty).
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

import profile_diff as pd  # noqa: E402


# ---------- fixtures ----------

def _ability(name, value=1, enabled=True, aid="x"):
    """A minimal but structurally-real ability dict."""
    return {"name": name, "description": f"{name} desc", "enabled": enabled,
            "share_with_unit": False, "id": aid,
            "conditions": [{"type": "profileRole", "data": {"role": "Attacker"}}],
            "effect": {"type": "modifyRelative", "data": {"value": value}}}


def _weapon(name, ap=0, kws=None, abilities=None, wtype="Ranged"):
    w = {"name": name, "type": wtype, "RNG": 24, "A": 1, "S": 5, "AP": ap,
         "D": 1, "count": 1, "keywords": list(kws or []),
         "abilities": abilities or []}
    w["WS" if wtype == "Melee" else "BS"] = 4
    return w


def _model(name, count=1, t=3, kws=None, weapons=None, abilities=None):
    return {"name": name, "model_count": count, "M": 6, "T": t, "Sv": 4,
            "W": 1, "LD": 7, "OC": 2, "invuln": None, "fnp": None,
            "keywords": list(kws or []),
            "abilities": abilities or [], "weapons": weapons or []}


def _unit(name, points=100, kws=None, models=None, abilities=None,
          leader_effects=None, leadership=None):
    return {"name": name, "profile_name": name, "points": points,
            "keywords": list(kws or []), "abilities": abilities or [],
            "leadership": list(leadership or []), "support": [],
            "leader_effects": leader_effects or [],
            "apply_leader_effects_to_self": False, "damageable": False,
            "unit_composition": "", "wargear_options": "", "notes": "",
            "models": models or []}


def _army(name, units):
    return {"name": name, "units": units}


# ---------- tests ----------

class TopLevelDiff(unittest.TestCase):
    def test_statuses(self):
        v1 = _army("A", [_unit("Same"), _unit("Gone"),
                         _unit("Changed", points=100)])
        v2 = _army("A", [_unit("Same"), _unit("New"),
                         _unit("Changed", points=110)])
        rows = {r.name: r.status for r in pd.diff_army(v1, v2)}
        self.assertEqual(rows, {"Same": "identical", "Gone": "removed",
                                "New": "added", "Changed": "modified"})

    def test_ability_id_ignored(self):
        # same content, different random ids -> identical
        u1 = _unit("U", abilities=[_ability("Buff", aid="aaa")])
        u2 = _unit("U", abilities=[_ability("Buff", aid="zzz")])
        rows = pd.diff_army(_army("A", [u1]), _army("A", [u2]))
        self.assertEqual(rows[0].status, "identical")

    def test_keyword_order_insensitive(self):
        u1 = _unit("U", kws=["FLY", "INFANTRY"])
        u2 = _unit("U", kws=["INFANTRY", "FLY"])
        other, ab = pd.diff_unit(u1, u2)
        self.assertEqual((other, ab), ([], []))


class UnitDiffContent(unittest.TestCase):
    def test_scalar_and_keyword_and_ability_split(self):
        u1 = _unit("U", points=100, kws=["A"],
                   abilities=[_ability("Old")])
        u2 = _unit("U", points=110, kws=["A", "B"],
                   abilities=[_ability("Old"), _ability("New")])
        other, ab = pd.diff_unit(u1, u2)
        # box 2: points change + keyword add ; box 3: ability add
        self.assertEqual({c.key for c in other}, {"points", "keywords"})
        self.assertTrue(all(c.category == "other" for c in other))
        self.assertEqual(len(ab), 1)
        self.assertEqual((ab[0].op, ab[0].category, ab[0].ident),
                         ("added", "ability", "New"))

    def test_nested_weapon_change(self):
        w1 = _weapon("Rifle", ap=0)
        w2 = _weapon("Rifle", ap=-1)
        u1 = _unit("U", models=[_model("M", weapons=[w1])])
        u2 = _unit("U", models=[_model("M", weapons=[w2])])
        other, ab = pd.diff_unit(u1, u2)
        self.assertEqual(len(other), 1)
        c = other[0]
        self.assertEqual((c.op, c.key, c.old, c.new), ("changed", "AP", 0, -1))
        # locator: model M -> weapon Rifle
        self.assertEqual(c.locator, (("models", "M"), ("weapons", "Rifle")))

    def test_whole_model_and_weapon_addition(self):
        u1 = _unit("U", models=[_model("M1")])
        u2 = _unit("U", models=[_model("M1", weapons=[_weapon("Extra")]),
                                _model("M2")])
        other, ab = pd.diff_unit(u1, u2)
        kinds = {(c.op, c.key, c.ident) for c in other}
        self.assertIn(("added", "models", "M2"), kinds)
        self.assertIn(("added", "weapons", "Extra"), kinds)

    def test_ability_replaced(self):
        u1 = _unit("U", abilities=[_ability("Buff", value=1, aid="keepme")])
        u2 = _unit("U", abilities=[_ability("Buff", value=3, aid="other")])
        other, ab = pd.diff_unit(u1, u2)
        self.assertEqual(len(ab), 1)
        self.assertEqual(ab[0].op, "replaced")


class Convergence(unittest.TestCase):
    """The core invariant: accepting every change converges v1 to v2."""

    def _rich_pair(self):
        u1 = _unit(
            "Warrior", points=100, kws=["INFANTRY", "OLD"],
            leadership=["Squad A"],
            abilities=[_ability("UnitBuff", value=1, aid="u1")],
            leader_effects=[_ability("LeadAura", value=2, aid="l1")],
            models=[
                _model("Sergeant", count=1, t=3, kws=["CHAR"],
                       abilities=[_ability("MdlAb", value=1, aid="m1")],
                       weapons=[_weapon("Pistol", ap=0, kws=["PISTOL"]),
                                _weapon("Blade", ap=-1, wtype="Melee")]),
                _model("Grunt", count=4, t=3),
            ])
        u2 = _unit(
            "Warrior", points=115, kws=["INFANTRY", "NEW", "FLY"],
            leadership=["Squad A", "Squad B"],
            abilities=[_ability("UnitBuff", value=5, aid="u2"),
                       _ability("Fresh", value=9, aid="u3")],
            leader_effects=[],                      # removed the aura
            models=[
                _model("Sergeant", count=1, t=4, kws=["CHAR", "TOUGH"],
                       abilities=[],                # removed MdlAb
                       weapons=[_weapon("Pistol", ap=-1, kws=["PISTOL", "LETHAL"],
                                        abilities=[_ability("WpnAb", aid="w1")]),
                                _weapon("Rifle", ap=0)]),   # Blade->Rifle: swap
                # Grunt removed; NewGuy added
                _model("NewGuy", count=2, t=3),
            ])
        return u1, u2

    def test_accept_all_converges(self):
        u1, u2 = self._rich_pair()
        work = copy.deepcopy(u1)
        other, ab = pd.diff_unit(work, u2)
        self.assertTrue(other or ab)                # there ARE differences
        for ch in other + ab:
            pd.apply_change(work, ch)
        again = pd.diff_unit(work, u2)
        self.assertEqual(again, ([], []),
                         f"residual diff after accept-all: {again}")

    def test_accept_all_reversed_order(self):
        # semantic locators must make batch application order-independent
        u1, u2 = self._rich_pair()
        work = copy.deepcopy(u1)
        other, ab = pd.diff_unit(work, u2)
        for ch in reversed(other + ab):
            pd.apply_change(work, ch)
        self.assertEqual(pd.diff_unit(work, u2), ([], []))

    def test_replaced_keeps_v1_id(self):
        u1 = _unit("U", abilities=[_ability("Buff", value=1, aid="keepme")])
        u2 = _unit("U", abilities=[_ability("Buff", value=3, aid="other")])
        work = copy.deepcopy(u1)
        other, ab = pd.diff_unit(work, u2)
        pd.apply_change(work, ab[0])
        self.assertEqual(work["abilities"][0]["id"], "keepme")
        self.assertEqual(work["abilities"][0]["effect"]["data"]["value"], 3)

    def test_partial_accept_reduces(self):
        u1, u2 = self._rich_pair()
        work = copy.deepcopy(u1)
        other, ab = pd.diff_unit(work, u2)
        total = len(other) + len(ab)
        pd.apply_change(work, (other + ab)[0])       # accept just one
        o2, a2 = pd.diff_unit(work, u2)
        self.assertEqual(len(o2) + len(a2), total - 1)


class MergeDelete(unittest.TestCase):
    def test_merge_unit_deepcopy(self):
        army = _army("A", [])
        src = _unit("New")
        pd.merge_unit(army, src)
        self.assertEqual(army["units"][0]["name"], "New")
        src["name"] = "MUTATED"                      # must not leak in
        self.assertEqual(army["units"][0]["name"], "New")

    def test_delete_unit(self):
        army = _army("A", [_unit("Keep"), _unit("Drop")])
        pd.delete_unit(army, "Drop")
        self.assertEqual([u["name"] for u in army["units"]], ["Keep"])


class CaseInsensitive(unittest.TestCase):
    def test_unit_name_case_only_is_match(self):
        # 'In' vs 'in' (the real 40kapp-vs-wahapedia difference) must pair
        v1 = _army("A", [_unit("Commander In Coldstar Battlesuit")])
        v2 = _army("A", [_unit("Commander in Coldstar Battlesuit")])
        rows = pd.diff_army(v1, v2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "identical")
        # display keeps the v1 spelling
        self.assertEqual(rows[0].name, "Commander In Coldstar Battlesuit")

    def test_nested_name_case_only_is_match(self):
        # a model/weapon differing only by case must not show add/remove
        v1 = _unit("U", models=[_model("Body", weapons=[_weapon("Rifle")])])
        v2 = _unit("U", models=[_model("BODY", weapons=[_weapon("rifle")])])
        other, ab = pd.diff_unit(v1, v2)
        self.assertEqual((other, ab), ([], []))

    def test_apply_survives_case_difference(self):
        # accepting a change on a case-mismatched unit still resolves
        v1 = _unit("U", points=100,
                   models=[_model("Body", weapons=[_weapon("Rifle", ap=0)])])
        v2 = _unit("U", points=100,
                   models=[_model("BODY", weapons=[_weapon("RIFLE", ap=-1)])])
        work = copy.deepcopy(v1)
        other, ab = pd.diff_unit(work, v2)
        self.assertEqual(len(other), 1)          # only the AP change
        for ch in other:
            pd.apply_change(work, ch)
        self.assertEqual(work["models"][0]["weapons"][0]["AP"], -1)


class DetailInspector(unittest.TestCase):
    def test_ability_internal_diff(self):
        old = _ability("Buff", value=1, enabled=True, aid="a")
        new = _ability("Buff", value=3, enabled=False, aid="b")
        rows = pd.diff_detail(old, new)
        labels = [r.label for r in rows]
        # id ignored; enabled + nested effect value reported
        self.assertTrue(any("enabled" in s for s in labels))
        self.assertTrue(any("effect.data.value" in s and "1 \u2192 3" in s
                            for s in labels))
        self.assertFalse(any("id" in s for s in labels))
        self.assertTrue(all(r.category == "detail" for r in rows))

    def test_added_removed_condition(self):
        old = {"conditions": [{"type": "x"}], "effect": {}}
        new = {"conditions": [{"type": "x"}, {"type": "y"}], "effect": {}}
        rows = pd.diff_detail(old, new)
        self.assertTrue(any(r.tag == "added" for r in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
