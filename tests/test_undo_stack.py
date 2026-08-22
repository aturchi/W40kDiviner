"""Undo / redo of the game assistant's table.

Two halves:

  * the stack itself (`undo_stack`), which is pure and fully testable -
    ordering, the redo branch, the depth limit, and the dropping of
    changes that change nothing;
  * the path a change takes back into the table. The GUI setter
    (`GameAssistantApp._set_cell`) is a dozen lines over a Treeview and
    the pure roster functions, so it is reproduced here over a fake tree
    with the same three methods, exactly as test_ability_rows.py
    reproduces the ability toggle. What is really being checked is the
    thing that could silently rot: undoing the masking of an ABILITY row
    must put the ability back into the combat view, not merely un-grey
    the row.

No tkinter, no external data.
"""
import testpaths                      # sets up sys.path to the engine src/
import leader_core as lc
import modifier_engine as me
import tree_ids
import undo_stack as us

MASK_TAG = "masked"


# ---------------- 1. the stack ----------------

st = us.UndoStack()
assert not st.can_undo() and not st.can_redo() and len(st) == 0
assert st.undo() is None and st.redo() is None
assert st.undo_label() == "" and st.redo_label() == ""

# a change that changes nothing is not a change
assert us.action("noop", [us.change("A", "u0", "wounds", "2", "2")]) is None
assert us.action("empty", []) is None
assert st.push(None) is False and len(st) == 0

a1 = us.action("edit Model 1", [us.change("A", "u0m0c0", "wounds", "2", "1")])
a2 = us.action("mask 2 rows", [us.change("B", "u1m0c0", "masked", False, True),
                               us.change("B", "u1m0c1", "masked", False, True)])
assert st.push(a1) and st.push(a2)
assert st.undo_label() == "mask 2 rows" and len(st) == 2
assert st.undo() is a2 and st.undo_label() == "edit Model 1"
assert st.redo_label() == "mask 2 rows" and st.can_redo()
assert st.redo() is a2 and not st.can_redo()

# a new action rewrites the future
st.undo()
assert st.can_redo()
st.push(us.action("mask 1 row", [us.change("A", "u0", "masked", False, True)]))
assert not st.can_redo(), "the redo branch must go when history is rewritten"

st.clear()
assert not st.can_undo() and not st.can_redo()

deep = us.UndoStack(limit=3)
for i in range(5):
    deep.push(us.action(f"step {i}",
                        [us.change("A", "u0", "wounds", str(i), str(i + 1))]))
assert len(deep) == 3 and deep.undo_label() == "step 4"
assert us.rows_label("mask", 1) == "mask 1 row"
assert us.rows_label("unmask", 3) == "unmask 3 rows"
print("stack semantics: ordering, redo branch, depth limit, no-ops")


# ---------------- 2. apply_action ----------------

seen = []


def setter(side, iid, field, value):
    seen.append((side, iid, field, value))
    return iid != "gone"


# Two writes to the SAME cell in one action: undo must unwind them in
# reverse, or the cell ends up holding the intermediate value.
act = us.action("two steps", [us.change("A", "c", "wounds", "2", "1"),
                              us.change("A", "c", "wounds", "1", "0")])
touched = us.apply_action(act, setter, undo=True)
assert [v for _s, _i, _f, v in seen] == ["1", "2"], seen
assert touched == [("A", "c"), ("A", "c")]
seen.clear()
us.apply_action(act, setter, undo=False)
assert [v for _s, _i, _f, v in seen] == ["1", "0"], seen

seen.clear()
gone = us.action("stale", [us.change("A", "gone", "masked", True, False),
                           us.change("A", "here", "masked", True, False)])
assert us.apply_action(gone, setter, undo=True) == [("A", "here")], \
    "a row that no longer exists must not be reported as touched"
print("apply_action replays old values in reverse and new ones forward")


# ---------------- 3. the table setter, over a fake tree ----------------


class FakeTree:
    """The three Treeview methods _set_cell uses."""

    def __init__(self, rows):
        self.rows = {iid: {"tags": (), "wounds": ""} for iid in rows}

    def exists(self, iid):
        return iid in self.rows

    def item(self, iid, key=None, tags=None):
        if tags is not None:
            self.rows[iid]["tags"] = tuple(tags)
            return None
        return self.rows[iid]["tags"]

    def set(self, iid, _col, value=None):
        if value is None:
            return self.rows[iid]["wounds"]
        self.rows[iid]["wounds"] = value


def ability(name, kw=None, aid=None):
    eff = {"type": "special", "data": {}} if kw is None else {
        "type": "setKeyword", "data": {
            "target": {"title": "All weapons", "key": "allWeapons"},
            "operation": {"title": "Add", "key": "add"}, "keyword": kw}}
    return {"name": name, "description": "", "enabled": True, "id": aid,
            "share_with_unit": False, "conditions": [], "effect": eff}


def unit_dict(name):
    return {"name": name, "profile_name": name, "points": 10,
            "keywords": ["Infantry"],
            "abilities": [ability("Grant", kw="LETHAL HITS", aid="a-grant")],
            "core_abilities": [], "faction_abilities": [],
            "leader_effects": [], "leadership": [], "support": [],
            "apply_leader_effects_to_self": False, "damageable": False,
            "unit_composition": "", "wargear_options": "", "notes": "",
            "models": [{"name": f"{name} model", "model_count": 2, "M": 6,
                        "T": 4, "Sv": 3, "W": 2, "LD": 6, "OC": 1,
                        "invuln": None, "fnp": None, "keywords": [],
                        "abilities": [],
                        "weapons": [{"name": "gun", "type": "Ranged",
                                     "RNG": 24, "A": 2, "BS": 3, "S": 4,
                                     "AP": 0, "D": 1, "count": 2,
                                     "keywords": [], "abilities": []}]}]}


rosters = {"A": [lc.make_entry(unit_dict("Base"))]}
ab_iid = tree_ids.ability_iid(0, "a-grant")
copy_iid = tree_ids.copy_iid(0, 0, 0)
trees = {"A": FakeTree([ab_iid, copy_iid])}


def set_cell(side, iid, field, value):
    """What GameAssistantApp._set_cell does, on the pure functions."""
    tree = trees.get(side)
    if tree is None or not tree.exists(iid):
        return False
    if field == "masked":
        tags = set(tree.item(iid, "tags"))
        tags = (tags | {MASK_TAG}) if value else (tags - {MASK_TAG})
        tree.item(iid, tags=tuple(tags))
        ui, key = tree_ids.parse_ability(iid)
        if ui is not None and ui < len(rosters[side]):
            lc.set_entry_ability_enabled(rosters[side][ui], key, not value)
    elif field == "wounds":
        tree.set(iid, "wounds", value)
    else:
        return False
    return True


def weapon_keywords():
    unit = lc.build_entry_unit(rosters["A"][0], {}, set(), {}, "w40k-sim/6")
    view = me.build_view(unit, None, me.Context(), role="attacker")
    return {str(k).upper() for m in view.models() for w in m.weapons
            for k in w.keywords}


assert "LETHAL HITS" in weapon_keywords(), "ability inert to begin with"

# masking the ability row and the model copy, as one gesture
table = us.UndoStack()
changes = [us.change("A", ab_iid, "masked", False, True),
           us.change("A", copy_iid, "masked", False, True)]
for c in changes:
    set_cell(c["side"], c["iid"], c["field"], c["new"])
assert table.push_changes(us.rows_label("mask", 2), changes)
assert "LETHAL HITS" not in weapon_keywords()
assert MASK_TAG in trees["A"].item(copy_iid, "tags")

us.apply_action(table.undo(), set_cell, undo=True)
assert "LETHAL HITS" in weapon_keywords(), \
    "undoing a masked ability row must switch the ability back ON, " \
    "not merely un-grey the row"
assert MASK_TAG not in trees["A"].item(copy_iid, "tags")

us.apply_action(table.redo(), set_cell, undo=False)
assert "LETHAL HITS" not in weapon_keywords()
assert MASK_TAG in trees["A"].item(ab_iid, "tags")
print("undo of an ability row reaches the roster flag, not just the tag")

# a wounds cell: the value goes back verbatim, free text included
set_cell("A", copy_iid, "wounds", "4")
edit = us.action("edit Model 1",
                 [us.change("A", copy_iid, "wounds", "4", "1")])
set_cell("A", copy_iid, "wounds", "1")
us.apply_action(edit, set_cell, undo=True)
assert trees["A"].set(copy_iid, "wounds") == "4"
us.apply_action(edit, set_cell, undo=False)
assert trees["A"].set(copy_iid, "wounds") == "1"
assert set_cell("A", "u9m9c9", "wounds", "1") is False
assert set_cell("A", copy_iid, "nonsense", "1") is False
print("wounds cells round-trip through undo and redo")

print("OK: undo stack")
