"""The HAZARDOUS closing window, driven on the Tk stub.

hazard_close is tested on its own; what this covers is the window over
it: that it draws what the logic worked out, that it does not touch
anything before the player answers, and that each of the three ways out
of it - Apply, Skip, the close box - gives the caller exactly one
answer.
"""
import tkstub

tkstub.install()

import testpaths                       # noqa: E402  (after the stub)
import tkinter as tk                   # noqa: E402
import hazard_close as hc              # noqa: E402
import hazard_view as hv               # noqa: E402


class FakeWeapon:
    def __init__(self, name):
        self.name = name


class FakeModel:
    def __init__(self, weapons):
        self.weapons = weapons


PLASMA = FakeWeapon("plasma gun")
BOLTER = FakeWeapon("bolter")
WEAPONS = [{"weapon": BOLTER}, {"weapon": PLASMA}]
BY_INDEX = {0: FakeModel([BOLTER, PLASMA])}

ROOT = tk.Tk()


def model(key, entry=0, wounds=2, cap=2, char=False, scarcity=4):
    return {"key": key, "label": key, "wounds": wounds, "max": cap,
            "sv": 3, "invuln": None, "fnp": None, "character": char,
            "entry": entry, "scarcity": scarcity}


def squad(n=4):
    return [model(f"t{i}") for i in range(n)]


def window(damage, models=None, name="Intercessor Squad"):
    """The window, plus the answer box the caller gets."""
    models = squad() if models is None else models
    by, _p = hc.bearers(WEAPONS, BY_INDEX)
    items = hc.owed([{"index": 1, "label": "plasma gun",
                      "self_damage": damage}], WEAPONS, by, models)
    got = {}
    win = hv.HazardWindow(
        ROOT, items, models, name,
        lambda rows, entry: got.update(rows=rows, entry=entry,
                                       calls=got.get("calls", 0) + 1))
    return win, got, models


def rows_of(tree):
    return [tree.item(i, "text") for i in tree.get_children("")]


# --- 1. both panels are drawn from the resolved step ------------------

win, got, models = window(1)
assert got == {}, "nothing is reported before the player answers"
assert rows_of(win.weapons) == ["plasma gun"], rows_of(win.weapons)
assert win.weapons.item(win.weapons.get_children("")[0],
                        "values")[0] == 1
# One 2W model takes one mortal wound: one row, and it is not destroyed.
hurt = win.models.get_children("")
assert len(hurt) == 1, rows_of(win.models)
assert "destroyed" not in rows_of(win.models)[0]
assert win.models.item(hurt[0], "values")[0] == "2 -> 1"
# The records themselves are untouched while the window is open.
assert all(m["wounds"] == 2 for m in models), models
print("the window draws the resolved step and touches nothing yet")


# --- 2. the panel names the model the test lands on -------------------

assert win.weapons.item(win.weapons.get_children("")[0],
                        "values")[1] == "t0", "the bearer is named"
untraced = hc.owed([{"index": 9, "label": "mystery", "self_damage": 1}],
                   WEAPONS, {}, squad())
w2 = hv.HazardWindow(ROOT, untraced, squad(), "Squad",
                     lambda r, e: None)
assert w2.weapons.item(w2.weapons.get_children("")[0],
                       "values")[1] == "the unit", \
    "a weapon with no known bearer must not name one"
print("the panel names the bearer, and says so when there is none")


# --- 3. Apply hands back only the models that changed -----------------

win, got, models = window(3)          # spills off the 2W bearer
win.buttons["apply"].invoke()
assert got["calls"] == 1
keys = [r["key"] for r in got["rows"]]
assert keys == ["t0", "t1"], got["rows"]
assert got["rows"][0]["dead"] is True and got["rows"][0]["wounds"] == 0
assert got["rows"][1]["dead"] is False and got["rows"][1]["wounds"] == 1
assert got["entry"]["damage"] == 3 and got["entry"]["killed"] == 1
print("Apply reports the models that changed, and only those")


# --- 4. Skip is an answer, not an escape ------------------------------

win, got, _m = window(3)
win.buttons["skip"].invoke()
assert got["calls"] == 1
assert got["rows"] == [], got["rows"]
# The log field is the same either way: what was owed does not depend
# on whether the player chose to write it down.
assert got["entry"]["damage"] == 3 and got["entry"]["killed"] == 1
print("Skip answers with nothing to write, and still says what was owed")


# --- 5. the answer is given exactly once, however it is given ---------

# Three ways out - Apply, Skip, the window manager's close box - and one
# callback. Applying the same wounds twice would take them off the table
# twice, which is silent and unrecoverable in the middle of a game.
#
# The close box is not driven here: real Tk's protocol() getter returns
# the NAME of a command, not the callable, so a stub that handed back a
# function would be standing in for an API that does not exist. It is
# wired to the very method the Skip button calls, so the guard below is
# the guard it goes through.
win, got, _m = window(1)
assert win.buttons["skip"].cget("command") is not None
win.buttons["skip"].invoke()
win.buttons["apply"].invoke()
win.buttons["skip"].invoke()
assert got["calls"] == 1, "the callback fired more than once"
assert got["rows"] == [], "the first answer is the one that counts"
print("the answer is given exactly once, whichever button is pressed")


# --- 6. a unit that cannot absorb it says so --------------------------

win, _got, _m = window(3, models=[model("solo", wounds=1, cap=1,
                                        scarcity=1)])
assert any("no model left" in t for t in rows_of(win.models)), \
    rows_of(win.models)
print("points with nobody left to take them are shown, not dropped")


# --- 7. the caption counts the models the unit lost -------------------

win, _got, _m = window(5)
assert win.entry["killed"] == 2, win.entry
assert sum(1 for i in win.models.get_children("")
           if "destroyed" in win.models.item(i, "text")) == 2
print("the models the unit destroyed are marked in the panel")

print("hazard window: all checks passed (against the Tk stub)")
