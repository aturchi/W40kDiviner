"""cmd_attack end to end, from the roster to the table.

Everything below cmd_attack has a test of its own. What none of them
covers is the WIRING: whether the assistant hands the right table rows
to defender_models, the right unit reference to the session, and writes
back what the window returns. That is a single method, it is the core of
program 2, and until now nothing exercised it at all.

So the whole application is built - headless, on the Tk stub - a roster
is put into it by hand, and cmd_attack is called. The window it opens is
then driven by pressing its buttons, exactly as the player would, and
what lands in the table and in the attack log is what is checked.

The stub is installed UNCONDITIONALLY: this must run the same way on a
machine with a display and on one without, and it must never pop up a
window in the middle of a suite.
"""
import json
import os
import random
import sys

import tkstub

tkstub.install()

import testpaths                      # noqa: E402  (after the stub)
import tkinter as tk                  # noqa: E402
import attack_log                     # noqa: E402
import leader_core as lc              # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.abspath(testpaths.__file__)), os.pardir))
import game_assistant as ga           # noqa: E402

DATA = json.load(open(testpaths.roster("space-marines.json")))
UNITS = {u["name"]: u for u in DATA["armies"][0]["units"]}

# Nothing may reach a real dialog: a suite that pops one up hangs, and
# an assertion that never runs is worse than none. Every messagebox is
# captured instead, and the captions are read back at the end.
SEEN = []
for name in ("showinfo", "showwarning", "showerror"):
    setattr(ga.messagebox, name,
            lambda *a, _n=name, **k: SEEN.append((_n, a, k)))


# The assistant seeds its dice from the clock (random.Random() with no
# argument), which is right for a program and fatal for a test: the
# assertions below are about what a given attack DID, and with free dice
# they were true most of the time. Measured before this was fixed: 2
# failures in 15 runs, and the failure was the guard that says the check
# needs at least one model destroyed - the very assertion that had been
# added to stop the loop running zero times. A test in the suite that
# fails one run in seven is worse than no test, because it teaches
# whoever sees the red to run it again.
SEED = 1


def build(attacker="Intercessor Squad", defender="Assault Intercessor Squad",
          leader=None, seed=SEED):
    app = ga.GameAssistantApp()
    app.rng = random.Random(seed)
    app.rosters["A"] = [lc.make_entry(UNITS[attacker])]
    app.rosters["B"] = [lc.make_entry(UNITS[defender],
                                      UNITS[leader] if leader else None)]
    for side in ("A", "B"):
        app._fill_tree(side)
    app.att_side.set("A")
    app.trees["A"].selection_set(app.trees["A"].get_children("")[0])
    app.trees["B"].selection_set(app.trees["B"].get_children("")[0])
    return app


def window_of(app):
    """The attack window cmd_attack just opened."""
    for child in app.winfo_children():
        if isinstance(child, ga.attack_session_view.AttackSessionWindow):
            return child
    return None


def hazard_of(app):
    """The HAZARDOUS closing window, if one was opened."""
    for child in app.winfo_children():
        if isinstance(child, ga.hazard_view.HazardWindow):
            return child
    return None


def copy_rows(app, side="B"):
    """The MODEL COPY rows only. A model group also holds weapon rows,
    a separator and the ability rows, and counting those would make the
    checks below agree with the session for the wrong reason."""
    tree = app.trees[side]
    out = []
    for mid in tree.get_children(tree.get_children("")[0]):
        for cid in tree.get_children(mid):
            _u, _m, _w, ci = app._parse_iid(cid)
            if ci is not None:
                out.append((mid, cid))
    return out


def wounds(app, side="B"):
    tree = app.trees[side]
    # As TEXT: _fill_tree puts an int in an untouched cell and the
    # writer puts a string in one it has changed, so comparing the raw
    # values would report a difference that is only a type.
    return {cid: str(tree.set(cid, "wounds"))
            for _mid, cid in copy_rows(app, side)}


# --- 1. cmd_attack opens the window and nothing else ------------------

SEEN.clear()
app = build()
app.cmd_attack()
win = window_of(app)
assert win is not None, SEEN
assert not SEEN, SEEN                  # no complaint, no picker, no report
# The queue holds the attacker's weapons and the target panel the
# defender's models.
assert win.weapons.get_children(""), "no weapon in the queue"
assert win.targets.get_children(""), "no target in the panel"
before = wounds(app)
assert before, "the defender has no model rows"
print("cmd_attack opens the attack window with both panels filled")


# --- 2. the session was given the profiles, not one reference ---------

session = win.session
assert session.unit_ref["T"], session.unit_ref
assert "keywords" in session.unit_ref
# Every model record carries its own save, and the wounds come from the
# table rather than the datasheet.
assert all("sv" in m for m in session.models)
assert len(session.models) == len(before)
assert {m["key"] for m in session.models} == set(before)
print("the session was built from the table rows and the combat view")


# --- 3. firing writes nothing until the player says so ----------------

win.buttons["fire_all"].invoke()
assert session.records(), "nothing fired"
assert wounds(app) == before, "the table moved before End sequence"
assert not app.undo.can_undo(), "an undo step appeared too early"
print("the table is untouched until the damage is written")


# --- 4. End sequence writes the wounds, the masks and the log ---------

logged = len(app.log)
win.buttons["write"].invoke()
after = wounds(app)
assert after != before, (before, after)
assert app.undo.can_undo(), "the write must be one undo step"
assert len(app.log) == logged + 1, "the attack was not logged"
entry = app.log.entries[-1]
assert entry["weapons"], entry
assert entry["allocation"]["models"], entry["allocation"]
# Every weapon that fired is in the log, with the attacks it rolled.
assert len(entry["weapons"]) == len(session.records())
assert all(w["attacks"] >= 0 for w in entry["weapons"])
# A model reduced to zero wounds is masked in the same step. The loop
# is guarded: an assertion that runs zero times because nothing died
# would report a masking rule nobody checked. The seed is fixed so the
# scenario is REPRODUCIBLE, not so that it is favourable - firing the
# whole unit kills something on 22 of the first 24 seeds - and the
# guard is what makes an unlucky one, or a changed roster, say so
# instead of passing quietly.
tree = app.trees["B"]
killed = [cid for cid, left in after.items() if str(left) == "0"]
assert killed, "this check needs at least one model destroyed"
for cid in killed:
    assert app._is_masked("B", cid), cid
# The log carries what was actually taken off, not just a row count:
# labels that read '?' and a before of 0 would still be a non-empty
# list, and would tell the player nothing two turns later.
models = entry["allocation"]["models"]
assert all(m["label"] and m["label"] != "?" for m in models), models
totals = attack_log.allocation_totals(entry)
assert totals["removed"] > 0 and totals["killed"] == len(killed), totals
print("End sequence writes wounds, masks and the log as one step")


# --- 5. and Ctrl-Z takes the lot back ---------------------------------

app.cmd_undo()
assert wounds(app) == before, wounds(app)
assert not any(app._is_masked("B", cid) for cid in before)
print("one undo step puts the table back")


# --- 6. a led unit: the CHARACTER is not touched first -----------------

SEEN.clear()
app = build(defender="Assault Intercessor Squad", leader="Captain")
app.cmd_attack()
win = window_of(app)
assert win is not None, SEEN
session = win.session
chars = [m for m in session.models if m["character"]]
assert len(chars) == 1, [m["label"] for m in session.models]
# The Captain's profile is his own, not the squad's.
squad = [m for m in session.models if not m["character"]][0]
assert chars[0]["max"] != squad["max"], (chars[0], squad)
# Toughness is the bodyguard's, for the whole attack - the Captain's
# own is ignored even when it is the one that differs.
squad_t = int(UNITS["Assault Intercessor Squad"]["models"][0]["T"])
assert session.unit_ref["T"] == squad_t, (session.unit_ref["T"], squad_t)
win.buttons["fire_all"].invoke()
win.buttons["write"].invoke()
captain_rows = [cid for mid, cid in copy_rows(app)
                if "Captain" in app.trees["B"].item(mid, "text")]
assert captain_rows, "the Captain has no row"
full = int(UNITS["Captain"]["models"][0]["W"])
assert all(int(wounds(app)[c]) == full for c in captain_rows), \
    "the CHARACTER took damage while bodyguard models stood"
print("a led unit keeps its CHARACTER out of the way, end to end")


# --- 6b. masked copies are models already removed ---------------------

SEEN.clear()
app = build()
rows = copy_rows(app)
for _mid, cid in rows[:2]:
    app._set_cell("B", cid, "masked", True)
app.cmd_attack()
win = window_of(app)
assert win is not None, SEEN
assert len(win.session.models) == len(rows) - 2, \
    [m["label"] for m in win.session.models]
assert all(m["key"] not in {c for _m, c in rows[:2]}
           for m in win.session.models)
# Masking the model GROUP row removes every copy under it, which is a
# different code path from masking the copies one by one. It needs a
# defender with more than one group, so the led unit is used: masking
# the Captain's row must take the Captain out and leave the squad.
SEEN.clear()
app = build(leader="Captain")
groups = sorted({mid for mid, _cid in copy_rows(app)})
assert len(groups) > 1, groups
victim = groups[-1]
gone = {cid for mid, cid in copy_rows(app) if mid == victim}
assert gone, "the masked group had no copies"
app._set_cell("B", victim, "masked", True)
app.cmd_attack()
win = window_of(app)
assert win is not None, SEEN
assert not (gone & {m["key"] for m in win.session.models}), \
    "a masked model group still took damage"
assert len(win.session.models) == len(copy_rows(app)) - len(gone)
print("a masked copy is a model already removed, and takes no damage")


# --- 6c. only some weapons fired: the log says so ---------------------

SEEN.clear()
app = build()
app.cmd_attack()
win = window_of(app)
assert len(win.session.queue()) > 1, "this check needs two weapons"
win.buttons["fire"].invoke()
win.buttons["apply"].invoke()
left = win.session.queue()
win.buttons["write"].invoke()
entry = app.log.entries[-1]
reasons = {w["reason"] for w in entry["skipped"]}
assert "not fired" in reasons, entry["skipped"]
assert sum(1 for w in entry["skipped"]
           if w["reason"] == "not fired") == len(left), entry["skipped"]
print("weapons the player never fired are logged as not fired")


# --- 7. a defender with nothing left is refused, not resolved ---------

SEEN.clear()
app = build()
tree = app.trees["B"]
for _mid, cid in copy_rows(app):
    app._set_cell("B", cid, "masked", True)
app.cmd_attack()
assert window_of(app) is None, "an attack was resolved against nothing"
assert SEEN and any("masked" in str(a) for _n, a, _k in SEEN), SEEN
print("an attack with no model to allocate to is refused with a reason")


# --- 7b. ... and so is one whose wounds cells cannot be read ----------

# The unit is still there as far as the roster is concerned, so the
# earlier guard does not fire: this is the branch that catches it.
SEEN.clear()
app = build()
for _mid, cid in copy_rows(app):
    app._set_cell("B", cid, "wounds", "?")
app.cmd_attack()
assert window_of(app) is None, "an attack was resolved against free text"
assert SEEN and any("free text" in str(a) for _n, a, _k in SEEN), SEEN
# When only SOME cells are unreadable the attack goes ahead, and the
# player is told how many models were left out of it - otherwise the
# damage would quietly spread over fewer models than the unit has.
SEEN.clear()
app = build()
rows = copy_rows(app)
for _mid, cid in rows[:2]:
    app._set_cell("B", cid, "wounds", "ok?")
app.cmd_attack()
win = window_of(app)
assert win is not None, SEEN
assert len(win.session.models) == len(rows) - 2
assert SEEN and any("2 model rows" in str(a) for _n, a, _k in SEEN), SEEN
print("wounds cells holding free text stop the attack, with a reason")


# --- 8. hazardous is reported to the player, not silently dropped -----

SEEN.clear()
app = build()
app.cmd_attack()
win = window_of(app)
win.session._records.append({"index": 0, "label": "x", "attacks": 0,
                             "self_damage": 3, "warnings": [],
                             "events": [], "saves_made": 0,
                             "shrugged": 0, "no_target": 0, "wasted": 0,
                             "leftover": 0, "killed": 0, "rows": [],
                             "wounds_before": [
                                 int(m["wounds"]) for m in
                                 win.session.models]})
before_att = wounds(app, "A")
win.buttons["write"].invoke()

# It is no longer a messagebox telling the player to do it by hand: a
# window opens with the closing step already worked out.
haz = hazard_of(app)
assert haz is not None, SEEN
assert haz.entry["damage"] == 3, haz.entry
assert haz.entry["weapons"], haz.entry
assert wounds(app, "A") == before_att, \
    "the attacker's table must not move until the player answers"

# Apply writes the wounds into the ATTACKER's table, as its own undo
# step, and the log records the step apart from the allocation.
haz.buttons["apply"].invoke()
after_att = wounds(app, "A")
assert after_att != before_att, "the closing step reached the table"
entry = app.log.entries[-1]
assert entry["hazardous_step"]["damage"] == 3, entry
assert entry["hazardous_step"]["applied"] is True, entry
assert "hazardous_step" not in attack_log.allocation_record([]), \
    "the closing step must not ride in the defender's allocation"
assert app.undo.can_undo(), "the closing step is undoable on its own"
assert "hazardous" in app.undo.undo_label(), app.undo.undo_label()
app.cmd_undo()
assert wounds(app, "A") == before_att, \
    "one undo step puts the attacker's table back"
print("hazardous opens a closing step and writes it as its own undo step")


# --- 8b. Skip leaves the table alone but still logs what was owed -----

SEEN.clear()
app = build()
app.cmd_attack()
win = window_of(app)
win.session._records.append({"index": 0, "label": "x", "attacks": 0,
                             "self_damage": 2, "warnings": [],
                             "events": [], "saves_made": 0,
                             "shrugged": 0, "no_target": 0, "wasted": 0,
                             "leftover": 0, "killed": 0, "rows": [],
                             "wounds_before": [
                                 int(m["wounds"]) for m in
                                 win.session.models]})
before_att = wounds(app, "A")
win.buttons["write"].invoke()
haz = hazard_of(app)
haz.buttons["skip"].invoke()
assert wounds(app, "A") == before_att, "Skip must not touch the table"
entry = app.log.entries[-1]
assert entry["hazardous_step"]["damage"] == 2, entry
assert entry["hazardous_step"]["applied"] is False, entry
print("Skip leaves the table alone and still records what was owed")

print("game assistant attack: all checks passed (against the Tk stub)")
