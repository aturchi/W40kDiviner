"""session_rows: what the attack window shows, decided without Tkinter.

The window has two panels and both are driven entirely from an
AttackSession. What has to hold here is that the panels agree with the
rules the session enforces: the weapon queue shows what may still be
chosen, the target panel shows the allocation groups in the order they
take attacks with the current one marked, and the buttons offer exactly
the actions that are legal at that moment.

Rows are semantic, so nothing here asserts a column width or a wording
that the view is free to change.
"""
import testpaths                      # sets up sys.path to the engine src/
import alloc_groups as ag
import attack_math as am
import attack_session as asx
import session_rows as sr
from unit_model import Weapon


class Dice:
    def __init__(self, seq):
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


def body(key, wounds=1, cap=1, sv=None, entry=0, scarcity=1,
         character=False):
    return {"key": key, "label": key, "wounds": wounds, "max": cap,
            "sv": sv, "invuln": None, "fnp": None,
            "character": character, "entry": entry, "scarcity": scarcity}


def squad(n, cap=1, entry=0, prefix="b"):
    return [body(f"{prefix}{i}", wounds=cap, cap=cap, entry=entry,
                 scarcity=n) for i in range(n)]


def pair(name, a="1", d="1", count=1, keywords=None, **mkw):
    w = Weapon(name=name, wtype="Ranged", A=a, skill=3, S=8, AP=0, D=d,
               count=count, keywords=list(keywords or []))
    return {"weapon": w, "mech": mech(**mkw)}


UNIT_REF = {"T": 4, "keywords": set()}
LED = squad(3, cap=2) + [body("cpt", wounds=4, cap=4, character=True,
                              entry=1)]


def session(weapons=None, models=None, dice=(6,)):
    return asx.AttackSession(weapons or [pair("A"), pair("B")], UNIT_REF,
                             {}, models or squad(4), Dice(dice))


def kinds(rows, kind):
    return [r for r in rows if r["kind"] == kind]


# --- 1. the weapon queue: order, state, what may be picked ------------

s = session([pair("A"), pair("B"), pair("C")])
rows = sr.weapon_rows(s)
assert [r["index"] for r in rows] == [0, 1, 2]
assert [r["state"] for r in rows] == [sr.NEXT, sr.QUEUED, sr.QUEUED]
assert all(r["selectable"] and r["movable"] for r in rows)

s.fire()
rows = sr.weapon_rows(s)
# The fired weapon moves to the end, greyed out, and carries what it did.
assert [r["index"] for r in rows] == [1, 2, 0]
assert rows[-1]["state"] == sr.DONE and rows[-1]["index"] == 0
assert not rows[-1]["selectable"] and not rows[-1]["movable"]
assert rows[-1]["attacks"] == 1 and rows[-1]["killed"] == 1
assert rows[0]["state"] == sr.NEXT

# While a weapon is armed nothing in the queue may be moved: the dice
# were rolled for the one at its head.
s.arm()
rows = sr.weapon_rows(s)
armed = [r for r in rows if r["state"] == sr.ARMED]
assert len(armed) == 1 and armed[0]["index"] == 1
assert not any(r["movable"] for r in rows)
assert not armed[0]["selectable"]
s.discard()
print("the queue shows what fired, what is next and what may be moved")


# --- 2. weapons that were never offered are still listed --------------

rows = sr.weapon_rows(s, skipped=[("Melta (out of range)", "out of range")])
skipped = [r for r in rows if r["state"] == sr.SKIPPED]
assert len(skipped) == 1 and skipped[0]["index"] is None
assert skipped[0]["note"] == "out of range"
assert not skipped[0]["selectable"]
print("a weapon that never entered the attack is shown, not dropped")


# --- 3. the target panel follows the allocation order -----------------

s = session(models=LED)
rows = sr.target_rows(s)
groups = kinds(rows, "group")
# One group for the three bodyguard models, one for the CHARACTER, and
# the CHARACTER can never be first.
assert len(groups) == 2, [g["label"] for g in groups]
assert groups[0]["character"] is False and groups[1]["character"] is True
assert groups[0]["current"] is True and groups[1]["current"] is False
assert [g["position"] for g in groups] == [0, 1]
# Every model of every group is listed under it, in member order.
assert len(kinds(rows, "model")) == 4
assert rows[0]["kind"] == "group" and rows[1]["kind"] == "model"

# The panel follows the ALLOCATION order, which is not the order the
# groups were built in. Two non-CHARACTER groups, the second of them
# holding a wounded model: the rules put that one first.
uneven = squad(2, cap=2, entry=0, prefix="hard") + [body("soft", wounds=2,
                                                         cap=3, entry=1)]
built = ag.build_groups(uneven)
assert built[0]["members"][0] == 0, "built in table order"
order = ag.default_order(built, uneven)
assert order[0] == 1, "but the wounded group is allocated to first"
shown = kinds(sr.target_rows(session([pair("A")], models=uneven)), "group")
assert shown[0]["label"] == built[1]["label"], [g["label"] for g in shown]
assert [g["position"] for g in shown] == [0, 1]
print("the target panel lists the groups in the order they take attacks")


# --- 4. the panel is rebuilt from the state, and marks what changed ---

s = session([pair("A", d="1"), pair("B")], models=LED)
rec = s.fire()
rows = sr.target_rows(s, record=rec)
models = kinds(rows, "model")
hurt = [m for m in models if m["state"] == sr.HURT]
assert len(hurt) == 1 and hurt[0]["wounds"] == 1, models
assert hurt[0]["damage"] == 1
assert models[0]["model"] == hurt[0]["model"], "the wounded model leads"
# Without a record no damage is attributed to anyone.
assert all(m["damage"] == 0 for m in kinds(sr.target_rows(s), "model"))
print("model rows carry the wounds now and the damage just taken")


# --- 5. the current group moves only when its last model dies ---------

s = session([pair("A", a="6"), pair("B")], models=LED)
s.fire()
rows = sr.target_rows(s)
groups = kinds(rows, "group")
# Six one-damage attacks kill the three two-wound bodies exactly. Those
# models belong to no group any more, so the only group left standing is
# the CHARACTER's - which is now current, without a single attack ever
# having been allocated to it.
live_groups = [g for g in groups if not g["casualties"]]
assert len(live_groups) == 1 and live_groups[0]["character"] is True
assert live_groups[0]["current"] is True
# The three that fell are listed apart, not dropped from the panel.
fallen = [g for g in groups if g["casualties"]]
assert len(fallen) == 1 and not fallen[0]["movable"]
dead = [m for m in kinds(rows, "model") if m["state"] == sr.DEAD]
assert len(dead) == 3 and all(m["group"] is None for m in dead)
assert not any(m["movable"] for m in dead)
assert len(kinds(rows, "model")) == 4, "every model is still on screen"
# A model that is gone cannot be moved, even with a live allocation
# under the panel: it belongs to no group and has no place in an order.
s.arm()
dead = [m for m in kinds(sr.target_rows(s), "model")
        if m["state"] == sr.DEAD]
assert dead and not any(m["movable"] for m in dead)
assert any(m["movable"] for m in kinds(sr.target_rows(s), "model")), \
    "the surviving models must still be movable"
s.discard()
# And an undo brings them back into their group.
s.undo()
back = kinds(sr.target_rows(s), "group")
assert not any(g["casualties"] for g in back), [g["label"] for g in back]
print("the current group marker follows 05.04.01, and no row ever vanishes")


# --- 6. the buttons offer what is legal, and only that ----------------

s = session([pair("A"), pair("B")])
b = sr.buttons(s)
assert b["fire"] and b["fire_all"] and b["move_weapon"]
assert not b["apply"] and not b["discard"] and not b["undo"]
# A preview allocation may not be reordered: it is thrown away.
assert not b["move_model"] and not b["move_group"]

s.arm()
b = sr.buttons(s)
assert b["apply"] and b["discard"] and b["move_model"]
assert not b["fire"] and not b["fire_all"] and not b["move_weapon"]
assert not b["undo"], "undo must not reach past an armed activation"
s.apply()
assert sr.buttons(s)["undo"]
# With something to undo AND a weapon armed, undo is still off: the
# armed dice would be lost silently.
s.arm()
assert s.records(), "there is an activation to undo"
assert not sr.buttons(s)["undo"]
s.discard()
assert sr.buttons(s)["undo"]

# Nothing left to shoot at: firing is pointless and is not offered.
s = session([pair("A", a="9"), pair("B")])
s.fire()
assert s.wiped()
b = sr.buttons(s)
assert not b["fire"] and not b["fire_all"] and b["undo"]
print("the buttons follow the state instead of being switched by hand")


# --- 7. PRECISION is offered only when it is a real choice ------------

SNIPER = pair("Sniper", keywords=["PRECISION"])
s = session([SNIPER], models=LED)
s.arm()
assert sr.buttons(s)["precision"] is True
group = s.alloc.character_groups()[0]
s.alloc.set_precision(group)
marked = [g for g in kinds(sr.target_rows(s), "group") if g["precision"]]
assert len(marked) == 1 and marked[0]["group"] == group
s.discard()

# No CHARACTER in the unit: the keyword is there but there is nothing
# to point it at.
s = session([SNIPER], models=squad(3))
s.arm()
assert sr.buttons(s)["precision"] is False
s.discard()
# ... and an ordinary weapon never offers it.
s = session([pair("A")], models=LED)
s.arm()
assert sr.buttons(s)["precision"] is False
print("PRECISION is offered only with a CHARACTER to aim at")


# --- 8. the headline says what is about to happen, then what did -----

s = session([pair("A", a="3"), pair("B")], models=LED)
line = sr.headline(s)
assert "A x1" in line and "4 models standing" in line, line
armed = s.arm()
line = sr.headline(s, armed)
assert "3 attacks" in line and "3 wounds to save" in line, line
s.apply()
s.fire()
assert sr.headline(s) == "Every weapon has fired.", sr.headline(s)

s = session([pair("A", a="9"), pair("B")])
s.fire()
assert "destroyed" in sr.headline(s), sr.headline(s)
print("the headline names the weapon, the dice and the state of the unit")


# --- 9. the hint explains why the run stopped -------------------------

s = session([SNIPER], models=LED)
assert "PRECISION" in sr.hint(s)
# Two untouched non-CHARACTER groups: the order is the player's call.
free = squad(2, cap=2, entry=0, prefix="hard") + [body("soft", wounds=3,
                                                       cap=3, entry=1)]
s = session([pair("A")], models=free)
assert "order" in sr.hint(s), sr.hint(s)
# Nothing to decide, nothing to say.
s = session([pair("A")], models=squad(3))
assert sr.hint(s) == ""
print("the hint appears only when something has to be decided")


# --- 10. what is still owed at the end --------------------------------

s = session([pair("P", count=2, hazardous=True)], dice=(1,))
assert sr.closing_note(s) == ""
s.fire()
note = sr.closing_note(s)
assert "2 mortal wounds" in note and "HAZARDOUS" in note, note
assert "attacking unit" in note
s.undo()
assert sr.closing_note(s) == ""
print("hazardous is carried to a closing step, and undone with the rest")


# --- 11. an activation reads back in one line -------------------------

s = session([pair("A", a="4")], models=LED)
rec = s.fire()
note = sr.activation_note(rec)
assert "2 destroyed" in note, note
empty = dict(rec, killed=0, saves_made=0, shrugged=0, wasted=0,
             no_target=0, self_damage=0)
assert sr.activation_note(empty) == "no effect"
print("an applied activation reads back as one line")

print("session_rows: all checks passed")
