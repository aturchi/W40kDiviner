"""The attack window, driven headless through the Tk stub.

What is worth testing in a widget is not that it draws, but that it
stays in step with the state underneath it: the panels are rebuilt from
the session after every action, the buttons offer only what is legal,
and End sequence hands back exactly the models whose wounds changed.
Everything else - colours, widths, wording - is the view's business and
is deliberately not asserted, so that changing a caption cannot fail a
test about the rules.

The stub is installed UNCONDITIONALLY here, not with install_if_missing:
this drives the widget deterministically even where a real tkinter
exists, with no window, no display and no timing. The window is
therefore never proof that it LOOKS right - that check belongs on real
hardware, with the probe scripts.
"""
import tkstub

tkstub.install()

import testpaths                      # noqa: E402  (after the stub)
import tkinter as tk                  # noqa: E402
import attack_math as am              # noqa: E402
import attack_session as asx          # noqa: E402
import attack_session_view as asv     # noqa: E402
import session_rows as sr             # noqa: E402
from unit_model import Weapon         # noqa: E402


class Dice:
    def __init__(self, seq=(6,)):
        self.seq = list(seq)
        self.drawn = 0

    def randint(self, _a, _b):
        v = self.seq[min(self.drawn, len(self.seq) - 1)]
        self.drawn += 1
        return v


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def body(key, wounds=1, cap=1, character=False, entry=0):
    return {"key": key, "label": key, "wounds": wounds, "max": cap,
            "sv": None, "invuln": None, "fnp": None,
            "character": character, "entry": entry, "scarcity": 1}


def pair(name, a="1", d="1", count=1, keywords=None, **mkw):
    return {"weapon": Weapon(name=name, wtype="Ranged", A=a, skill=3,
                             S=8, AP=0, D=d, count=count,
                             keywords=list(keywords or [])),
            "mech": mech(**mkw)}


LED = [body("b0", 2, 2), body("b1", 2, 2), body("b2", 2, 2),
       body("cpt", 4, 4, character=True, entry=1)]


def window(weapons=None, models=None, dice=(6,), skipped=()):
    root = tk.Tk()
    got = {}
    session = asx.AttackSession(weapons or [pair("A"), pair("B")],
                               {"T": 4, "keywords": set()}, {},
                               models or LED, Dice(dice))
    win = asv.AttackSessionWindow(root, session, "Target squad",
                                  lambda rows, haz: got.update(
                                      rows=rows, haz=haz),
                                  skipped=skipped,
                                  attacker_name="Firing squad")
    return win, got


def enabled(win, key):
    return str(win.buttons[key].cget("state")) != str(tk.DISABLED)


def labels(tree):
    """Every row of a tree, parents then children, as text."""
    out = []
    for iid in tree.get_children(""):
        out.append(tree.item(iid, "text"))
        out.extend(tree.item(k, "text") for k in tree.get_children(iid))
    return out


def names(tree):
    """labels(), with the "   <- ..." marker taken off.

    Both panels append a marker to the row they want the eye to land on
    (the group taking the next attack, the weapon about to fire). A
    check about WHICH row is where must not break when the marker is
    reworded, so identity is compared here and the marker itself is
    asserted separately, where it is the subject."""
    return [t.split("   <- ")[0] for t in labels(tree)]


# --- 1. both panels are populated from the session --------------------

win, _got = window([pair("A"), pair("B"), pair("C")],
                   skipped=[("Melta", "out of range")])
assert len(win.weapons.get_children("")) == 4, labels(win.weapons)
# The skipped weapon is listed and cannot be picked.
assert "Melta" in labels(win.weapons)[-1]
assert not any(r["label"].startswith("Melta")
               for r in win._w_iid.values())
# Right panel: two groups, four models, nested.
tops = win.targets.get_children("")
assert len(tops) == 2, labels(win.targets)
assert sum(len(win.targets.get_children(t)) for t in tops) == 4
print("both panels are drawn from the session, skipped weapons included")


# --- 2. the buttons follow the session, not the clicks ----------------

assert enabled(win, "fire") and enabled(win, "fire_all")
assert not enabled(win, "apply") and not enabled(win, "undo")
assert not enabled(win, "precision"), "no weapon is armed yet"

win.buttons["fire"].invoke()
assert enabled(win, "apply") and enabled(win, "discard")
assert not enabled(win, "fire") and not enabled(win, "undo")
assert not enabled(win, "move_weapon_up"), "the queue is frozen"

win.buttons["apply"].invoke()
assert enabled(win, "undo") and enabled(win, "fire")
assert not enabled(win, "apply")
# The move bar of the target panel is live from the start: the saves are
# the last step of every activation, so the order can be settled at any
# point before the one about to roll them. It used to be off until a
# weapon was armed, which was reported as a fault on the first real
# display run - the caption told the player to reorder and the buttons
# refused.
win2, _g2 = window([pair("A"), pair("B")], models=LED)
assert enabled(win2, "move_up"), "the order is open before Fire"
assert win2.tips["move"][0].cget("text") == win2.tips["move"][1], \
    "with the buttons live the caption must say what they do"
win2.buttons["fire"].invoke()
assert enabled(win2, "move_up"), "and it stays open once armed"
# When there IS nothing to order the caption has to say why, rather
# than describing the move the greyed buttons are refusing to make.
win3, _g3 = window([pair("A")],
                   models=[body("gone", wounds=0)])
assert not enabled(win3, "move_up")
assert "Nothing" in win3.tips["move"][0].cget("text"), \
    win3.tips["move"][0].cget("text")
print("every button reflects what the session allows at that moment")


# --- 3. the panels are rebuilt, never patched -------------------------

# The weapon that fired has left the queue and sits at the bottom with
# what it did; the target panel shows the wound it caused.
rows = names(win.weapons)
assert rows.index("A x1") > rows.index("B x1"), rows
assert rows.index("A x1") > rows.index("C x1"), rows
done = "w%d" % rows.index("A x1")
# The head of the queue is marked, and only the head: before this, every
# queued weapon was drawn identically and the player had to count rows
# to see which one Fire would take.
marked = [t for t in labels(win.weapons) if "<- fires next" in t]
assert len(marked) == 1 and marked[0].startswith("B x1"), \
    labels(win.weapons)
assert win.weapons.item(done, "values")[1], "the result column is filled"
hurt = [win.targets.item(k, "values")[0]
        for t in win.targets.get_children("")
        for k in win.targets.get_children(t)]
assert "1/2" in hurt, hurt
print("the panels are rebuilt from the state after every action")


# --- 4. undo takes the activation back, panels included ---------------

win.buttons["undo"].invoke()
assert enabled(win, "fire") and not enabled(win, "undo")
back = [win.targets.item(k, "values")[0]
        for t in win.targets.get_children("")
        for k in win.targets.get_children(t)]
assert "1/2" not in back and back.count("2/2") == 3, back
assert labels(win.weapons)[0].startswith("A x1"), labels(win.weapons)
print("undo puts the wounds, the queue and the panels back")


# --- 5. moving a weapon needs a selection and changes the order -------

win.buttons["move_weapon_down"].invoke()      # nothing selected
assert win.session.queue() == [0, 1, 2]
win.weapons.selection_set("w0")
win.buttons["move_weapon_down"].invoke()
assert win.session.queue() == [1, 0, 2], win.session.queue()
assert labels(win.weapons)[0].startswith("B x1")
print("Move up/down reorders the queue and redraws it")


# --- 6. moving a group needs a live allocation ------------------------

win, _got = window([pair("A")], models=LED)
win.targets.selection_set(win.targets.get_children("")[0])
win.buttons["move_down"].invoke()
assert win.session.alloc is None, "a preview must not be reordered"
win.buttons["fire"].invoke()
# A CHARACTER group can never be moved ahead of a bodyguard one, so the
# refusal comes from the rules and the panel must not move either - nor
# lose the selection, which a blind redraw would.
before = labels(win.targets)
picked = win.targets.get_children("")[1]
win.targets.selection_set(picked)
win.buttons["move_up"].invoke()
assert labels(win.targets) == before, "an illegal move must change nothing"
assert win.targets.selection() == (picked,), \
    "a refused move must not redraw and drop the selection"
print("group moves go through the rules, and a preview is read-only")


# --- 6b. a model that is gone belongs to no group and cannot move -----

win, _got = window([pair("A", a="4"), pair("B")], models=LED)
win.buttons["fire"].invoke()
win.buttons["apply"].invoke()
win.buttons["fire"].invoke()            # a LIVE allocation this time
fallen = [iid for iid in win._t_iid
          if win._t_iid[iid]["kind"] == "model"
          and win._t_iid[iid]["state"] == sr.DEAD]
assert fallen, "some models should have been destroyed"
before = labels(win.targets)
win.targets.selection_set(fallen[0])
win.buttons["move_up"].invoke()
win.buttons["move_down"].invoke()
assert labels(win.targets) == before

# Arming again must clear the damage the PREVIOUS weapon did: the column
# says what just happened, not what happened at some point.
damage = [win.targets.item(k, "values")[1]
          for t in win.targets.get_children("")
          for k in win.targets.get_children(t)]
assert not any(damage), damage
win.buttons["discard"].invoke()
print("a destroyed model cannot be moved, and stale damage is cleared")


# --- 7. PRECISION is offered only when it is a choice, and marks it ---

win, _got = window([pair("S", keywords=["PRECISION"])], models=LED)
win.buttons["fire"].invoke()
assert enabled(win, "precision")
win.buttons["precision"].invoke()
assert win.session.alloc.precision == win.session.alloc.character_groups()[0]
assert any("PRECISION" in t for t in labels(win.targets)), \
    labels(win.targets)
win.buttons["precision"].invoke()          # a toggle, not a latch
assert win.session.alloc.precision is None
assert not any("PRECISION" in t for t in labels(win.targets))
win.buttons["apply"].invoke()

# An ordinary weapon never offers it.
win, _got = window([pair("A")], models=LED)
win.buttons["fire"].invoke()
assert not enabled(win, "precision")
print("PRECISION is offered, marked and cleared from the panel")


# --- 8. Fire all runs the queue and stops at a decision ---------------

win, _got = window([pair("A"), pair("S", keywords=["PRECISION"]),
                    pair("C")], models=LED)
win.buttons["fire_all"].invoke()
assert win.session.queue() == [1, 2], win.session.queue()
assert "PRECISION" in win.hint_lbl.cget("text")
# Once the weapon is armed the choice is no longer pending - it is being
# made, in the panel - so the hint stands down instead of nagging.
win.buttons["fire"].invoke()
assert win.hint_lbl.cget("text") == "", win.hint_lbl.cget("text")
win.buttons["discard"].invoke()
assert "PRECISION" in win.hint_lbl.cget("text")
print("Fire all stops where the player has to decide, and says why")


# --- 9. End sequence hands back only what changed ---------------------

win, got = window([pair("A", a="4"), pair("B")], models=LED)
win.buttons["fire"].invoke()
win.buttons["apply"].invoke()
win.buttons["write"].invoke()
rows = got["rows"]
assert rows and all(r["wounds"] != 2 or r["dead"] is False for r in rows)
assert {r["key"] for r in rows} <= {"b0", "b1", "b2", "cpt"}
assert all(r["key"] != "cpt" for r in rows), "the CHARACTER was untouched"
dead = [r for r in rows if r["dead"]]
assert len(dead) == 2 and all(r["wounds"] == 0 for r in dead), rows
assert got["haz"] == 0
# The row says what CHANGED, not only the new value: the attack log
# reads 'label' and 'before' off it, and both default silently
# (allocation_record gives '?' and 0), so a missing key does not raise -
# it writes a log entry that reads "? : 0 -> 0" and totals to nothing.
assert all(r["label"] and r["label"] != "?" for r in rows), rows
assert all(r["before"] > r["wounds"] for r in rows), rows

# Nothing fired: End sequence writes nothing at all.
win, got = window([pair("A")], models=LED)
win.buttons["write"].invoke()
assert got == {}, got
print("End sequence reports exactly the models whose wounds changed")


# --- 10. hazardous is carried out to the caller -----------------------

win, got = window([pair("P", count=2, hazardous=True)], models=LED,
                  dice=(1,))
win.buttons["fire"].invoke()
win.buttons["apply"].invoke()
assert "HAZARDOUS" in win.foot_lbl.cget("text")
# It is damage the attacking unit has already taken, not advice, so it
# is drawn in the alert colour and not the hint one.
assert win.foot_lbl.cget("foreground") == asv.ALERT, \
    win.foot_lbl.cget("foreground")
win.buttons["write"].invoke()
assert got["haz"] == 2, got
print("hazardous self-damage reaches the caller, not just the label")

print("attack window: all checks passed (against the Tk stub)")
