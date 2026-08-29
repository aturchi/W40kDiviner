"""Masks that follow from the table, not from a gesture.

Two rules, both added at the command level and both one-way:

  * a model copy whose wounds cell reads zero is a model that has been
    removed - before this it went on shooting, because _masks_for reads
    the mask and never the wounds cell;
  * a unit with nothing left standing has its own row masked, so
    cmd_attack refuses to let a wiped-out squad fight.

The derived change rides in the SAME undo action as the edit that
implied it, which is the whole reason it cannot live in _set_cell: that
is the one path undo itself replays, and a rule living there would be
re-applied by the undo meant to take it back.

The stub is installed unconditionally: this must run the same way with
and without a display, and must never pop a window up mid-suite.
"""
import json
import os
import random
import sys
import types

import tkstub

tkstub.install()

import testpaths                      # noqa: E402  (after the stub)
import tkinter as tk                  # noqa: E402
import leader_core as lc              # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.abspath(testpaths.__file__)), os.pardir))
import game_assistant as ga           # noqa: E402

DATA = json.load(open(testpaths.roster("space-marines.json")))
UNITS = {u["name"]: u for u in DATA["armies"][0]["units"]}

SEEN = []
for _name in ("showinfo", "showwarning", "showerror"):
    setattr(ga.messagebox, _name,
            lambda *a, _n=_name, **k: SEEN.append((_n, a, k)))


def build(unit="Intercessor Squad"):
    app = ga.GameAssistantApp()
    app.rng = random.Random(1)
    app.rosters["A"] = [lc.make_entry(UNITS[unit])]
    app.rosters["B"] = [lc.make_entry(UNITS[unit])]
    for side in ("A", "B"):
        app._fill_tree(side)
    return app


def groups(app, side="A"):
    tree = app.trees[side]
    return list(tree.get_children(tree.get_children("")[0]))


def copies(app, side="A"):
    """The model COPY rows only: a group also holds weapon rows, a
    separator and the ability rows, and none of those is a model."""
    tree = app.trees[side]
    out = []
    for mid in groups(app, side):
        for cid in tree.get_children(mid):
            if app._parse_iid(cid)[3] is not None:
                out.append(cid)
    return out


def unit_row(ui=0):
    return ga.tree_ids.unit_iid(ui)


def edit(app, iid, value, side="A"):
    """Type 'value' into a row's value column and press Return.

    The REAL editor is driven, not a copy of what it does: the point of
    these checks is that the rule reaches the command, and a helper that
    called the rule itself would pass with the command left unwired.
    identify_row answers with the focused row, which is how the row to
    edit is chosen here.
    """
    tree = app.trees[side]
    tree.focus(iid)
    app._edit_cell(types.SimpleNamespace(x=0, y=0), side)
    box = [w for w in tree.winfo_children() if isinstance(w, tk.Entry)][-1]
    box.delete(0, tk.END)
    box.insert(0, str(value))
    box.event_generate("<Return>")


# --- 1. a copy at zero wounds is a copy that has been removed ---------

app = build()
cs = copies(app)
assert len(cs) == 5, cs
assert not app._is_masked("A", cs[0])
edit(app, cs[0], "0")
assert app._is_masked("A", cs[0]), "zero wounds did not remove the model"
assert app._is_masked("A", cs[0]) and not app._is_masked("A", cs[1])
assert not app._is_masked("A", unit_row()), "one model is not the unit"
print("a model copy at zero wounds is masked off the table")


# --- 2. the mask rides in the same undo action as the edit ------------

assert len(app.undo) == 1, "the edit and its mask are one action"
app.cmd_undo()
assert not app._is_masked("A", cs[0]), "undo did not put the model back"
assert str(app.trees["A"].set(cs[0], "wounds")) != "0"
app.cmd_redo()
assert app._is_masked("A", cs[0]), "redo did not remove it again"
print("the derived mask is undone and redone with the edit that caused it")


# --- 3. one way only: putting the wounds back does not bring it back --

edit(app, cs[0], "2")
assert app._is_masked("A", cs[0]), \
    "raising the wounds must NOT unmask - the player does that by hand"
# And unmasking BY HAND sticks, even with the cell still reading zero:
# the player is putting a model back on the board and will set its
# wounds themselves. A rule that re-masked it here would make a
# zero-wound model impossible to bring back at all.
app2 = build()
c0 = copies(app2)[0]
edit(app2, c0, "0")
assert app2._is_masked("A", c0)
app2.trees["A"].selection_set(c0)
app2.cmd_mask()
assert not app2._is_masked("A", c0), \
    "unmasking by hand must stick, whatever the wounds cell says"
print("raising the wounds again does not unmask: the rule is one-way")


# --- 4. free text is left alone --------------------------------------

app = build()
cs = copies(app)
edit(app, cs[0], "fled")
assert not app._is_masked("A", cs[0]), \
    "a cell that is not a number must not be read as zero"
edit(app, cs[1], "-1")
assert app._is_masked("A", cs[1]), "a negative count is still gone"
print("only a cell that reads as a number is judged")


# --- 5. the last model gone is the unit gone --------------------------

app = build()
cs = copies(app)
for c in cs[:-1]:
    edit(app, c, "0")
assert not app._is_masked("A", unit_row()), "one model is still standing"
edit(app, cs[-1], "0")
assert app._is_masked("A", unit_row()), \
    "a unit with nothing standing must be masked"
# And it really is out of the game, not just greyed.
masked_copies, _mw, _wc = app._masks_for("A", 0)
# Derived from the entry, never written down: a datasheet is free to
# split its models across several groups - the real Intercessor Squad
# keeps its Sergeant in one of its own - and a hardcoded {0: 5} was
# simply the synthetic roster's shape, which made this line fail under
# --real_data rather than test anything.
every_copy = {mi: int(m["model_count"])
              for mi, m in lc.entry_models(app.rosters["A"][0])}
assert masked_copies == every_copy, (masked_copies, every_copy)
assert sum(every_copy.values()) == len(cs), (every_copy, len(cs))
assert app._build_unit("A", 0) is None, "a wiped unit still built"
print("the unit row is masked once nothing of it is left standing")


# --- 6. a masked GROUP takes its copies with it -----------------------

# _masks_for counts a copy as removed when its GROUP is masked, so the
# unit rule has to read it the same way or a squad masked at group
# level would never count as destroyed.
app = build()
app.trees["A"].selection_set(*groups(app))
app.cmd_mask()
assert app._is_masked("A", unit_row()), \
    "every model group masked is the unit gone"
assert len(app.undo) == 1, "masking and the unit row are one gesture"
app.cmd_undo()
assert not app._is_masked("A", unit_row()), \
    "undo must take the derived mask back too"
print("a masked model group counts as destroyed, group level included")


# --- 7. masking the last copy by hand masks the unit ------------------

app = build()
cs = copies(app)
app.trees["A"].selection_set(*cs)
app.cmd_mask()
assert app._is_masked("A", unit_row())
assert len(app.undo) == 1
# Unmasking one copy is the player putting a model back: the unit row
# stays masked, and they unmask it themselves. Not symmetric, by
# decision - the alternative guesses at a gesture the player has not
# made yet.
app.trees["A"].selection_set(cs[0])
app.cmd_mask()
assert not app._is_masked("A", cs[0])
assert app._is_masked("A", unit_row()), \
    "unmasking a copy must not unmask the unit on its own"
print("masking the last copy masks the unit; unmasking stays manual")


# --- 8. a wiped unit is refused an attack ----------------------------

app = build()
for c in copies(app):
    edit(app, c, "0")
app.att_side.set("A")
app.trees["A"].selection_set(app.trees["A"].get_children("")[0])
app.trees["B"].selection_set(app.trees["B"].get_children("")[0])
SEEN.clear()
app.cmd_attack()
assert SEEN and any("masked" in str(a) for _n, a, _k in SEEN), SEEN
print("a unit with nothing left is refused the attack, with a reason")


# --- 9. a weapon count of zero is not a dead model --------------------

# The same column holds a model's wounds and a weapon's count. A weapon
# nobody carries any more is not a model that has been removed, and
# masking its row would take the weapon out of a squad that is still
# standing there.
app = build()
tree = app.trees["A"]
weapons = [w for mid in groups(app) for w in tree.get_children(mid)
           if app._parse_iid(w)[2] is not None]
assert weapons, "the roster unit has no weapon row to check"
edit(app, weapons[0], "0")
assert not app._is_masked("A", weapons[0]), \
    "a weapon count of zero is not a destroyed model"
assert not app._is_masked("A", unit_row())
print("a weapon count of zero is not read as a model being removed")

print("auto mask: all checks passed (against the Tk stub)")
