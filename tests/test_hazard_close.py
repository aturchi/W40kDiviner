"""hazard_close: who owes the hazard tests, and where they land.

No Tk and no dice: the tests were rolled inside the resolver and their
outcome is in the session records, so everything here is a pure
function of those records and the attacker's model list.
"""
import testpaths                       # noqa: F401  (sets sys.path)
import hazard_close as hc


class FakeWeapon:
    """Only its identity and its name matter to this module."""

    def __init__(self, name):
        self.name = name


class FakeModel:
    def __init__(self, weapons):
        self.weapons = weapons


def model(key, entry, wounds=2, cap=2, char=False, scarcity=5):
    return {"key": key, "label": key, "wounds": wounds, "max": cap,
            "sv": 3, "invuln": None, "fnp": None, "character": char,
            "entry": entry, "scarcity": scarcity}


def record(index, label, self_damage):
    return {"index": index, "label": label, "self_damage": self_damage}


# Two model groups: four troopers carrying the plasma, one sergeant
# carrying nothing hazardous, one CHARACTER.
PLASMA = FakeWeapon("plasma gun")
BOLTER = FakeWeapon("bolter")
FIST = FakeWeapon("power fist")
BY_INDEX = {0: FakeModel([BOLTER, PLASMA]), 1: FakeModel([FIST])}
WEAPONS = [{"weapon": BOLTER}, {"weapon": PLASMA}, {"weapon": FIST}]


def squad():
    out = [model(f"t{i}", 0) for i in range(4)]
    out.append(model("sgt", 1, scarcity=1))
    return out


# --- 1. the bearer is traced by identity, not by name -----------------

by, problem = hc.bearers(WEAPONS, BY_INDEX)
assert problem is None, problem
assert by == {0: 0, 1: 0, 2: 1}, by

# A weapon of the same NAME that never hung off a view model is a
# different object and must not be claimed by anybody.
twin = FakeWeapon("plasma gun")
by2, problem2 = hc.bearers(WEAPONS + [{"weapon": twin}], BY_INDEX)
assert 3 not in by2, by2
assert problem2 and "1 of 4" in problem2, problem2
print("the bearer is found by identity, and a miss is reported not guessed")


# --- 2. only the activations that actually failed a test appear -------

models = squad()
items = hc.owed([record(0, "bolter", 0), record(1, "plasma gun", 1),
                 record(2, "power fist", 0)], WEAPONS, by, models)
assert len(items) == 1, items
assert items[0]["label"] == "plasma gun" and items[0]["damage"] == 1
assert models[items[0]["bearer"]]["entry"] == 0, "charged to the group"
assert hc.total(items) == 1
assert hc.total([]) == 0
print("only a failed test is owed, and it is charged to its own group")


# --- 3. the mortal wounds start on the bearer -------------------------

models = squad()
out = hc.resolve(models, items)
hurt = hc.changed(out["rows"])
assert len(hurt) == 1 and hurt[0]["damage"] == 1, hurt
assert models[0]["entry"] == 0
assert hurt[0]["key"].startswith("t"), hurt
assert out["leftover"] == 0
# The records themselves are untouched: the player can still back out.
assert all(m["wounds"] == 2 for m in models), models
print("the wounds land on the bearer and the table is not touched yet")


# --- 3b. among the copies of the group, the hurt one is charged -------

# Every copy of a group carries the same weapon, so which one is "the"
# bearer is the module's choice. It follows the same champion order the
# rest of the allocation uses: finish the model already wounded rather
# than spread the damage over a second one.
models = squad()
models[2]["wounds"] = 1
one = hc.owed([record(1, "plasma gun", 1)], WEAPONS, by, models)
assert one[0]["bearer"] == 2, one
out = hc.resolve(models, one)
hurt = hc.changed(out["rows"])
assert [r["key"] for r in hurt] == ["t2"], hurt
assert hurt[0]["dead"], "the wounded copy is finished, not a fresh one"
print("the wounded copy of the group takes the test, not a fresh one")


# --- 4. three mortal wounds outlive a 2W bearer and spill -------------

models = squad()
big = hc.owed([record(1, "plasma gun", 3)], WEAPONS, by, models)
out = hc.resolve(models, big)
hurt = hc.changed(out["rows"])
assert sum(r["damage"] for r in hurt) == 3, hurt
assert sum(1 for r in hurt if r["dead"]) == 1, "the bearer is destroyed"
assert out["leftover"] == 0, "a spilling wound is not wasted"
print("a wound larger than its bearer spills instead of being wasted")


# --- 5. an untraced weapon still closes, from the top of 06.02 --------

models = squad()
loose = hc.owed([record(9, "mystery gun", 2)], WEAPONS, {}, models)
assert loose[0]["bearer"] is None
assert loose[0]["label"] == "mystery gun"
out = hc.resolve(models, loose)
assert sum(r["damage"] for r in hc.changed(out["rows"])) == 2
print("a weapon with no known bearer is still resolved, by the sequence")


# --- 6. a CHARACTER is not fed to the sequence before the troopers ----

models = squad()
models.append(model("cpt", 2, wounds=5, cap=5, char=True, scarcity=1))
lots = hc.owed([record(1, "plasma gun", 4)], WEAPONS, by, models)
out = hc.resolve(models, lots)
cpt = [r for r in out["rows"] if r["key"] == "cpt"][0]
assert cpt["damage"] == 0, "the CHARACTER takes nothing while troopers live"
print("the spill follows 06.02 and leaves the CHARACTER for last")


# --- 7. a group with no live copy left falls back to the sequence -----

models = squad()
for m in models:
    if m["entry"] == 0:
        m["wounds"] = 0
gone = hc.owed([record(1, "plasma gun", 1)], WEAPONS, by, models)
assert gone[0]["bearer"] is None, "no copy of the group is left to charge"
out = hc.resolve(models, gone)
assert [r["key"] for r in hc.changed(out["rows"])] == ["sgt"], out["rows"]
print("with every copy of the bearer gone the wound goes to who is left")


# --- 8. the log entry is separate from the defender's allocation ------

models = squad()
items = hc.owed([record(1, "plasma gun", 3)], WEAPONS, by, models)
entry = hc.log_entry(items, hc.resolve(models, items)["rows"])
assert entry["damage"] == 3 and entry["killed"] == 1, entry
assert entry["weapons"] == [{"label": "plasma gun", "damage": 3}], entry
assert entry["models"] and all(
    set(m) == {"label", "before", "after"} for m in entry["models"]), entry
assert all(m["after"] < m["before"] for m in entry["models"]), entry
# Nothing that attack_log.allocation_totals would pick up as damage
# dealt to the enemy.
assert "allocation" not in entry and "removed" not in entry, entry
print("the closing step logs itself without touching the defender totals")


# --- 9. a unit that kills itself outright reports the leftover --------

models = [model("solo", 0, wounds=1, cap=1, scarcity=1)]
by3, _p = hc.bearers(WEAPONS, BY_INDEX)
suicide = hc.owed([record(1, "plasma gun", 3)], WEAPONS, by3, models)
out = hc.resolve(models, suicide)
assert out["leftover"] == 2, out
assert out["alloc"].wiped(), "the unit destroyed itself"
# The allocation stops at zero rather than going through it, whatever
# the overkill: callers rely on this and would otherwise have to clamp.
assert all(r["after"] >= 0 for r in out["rows"]), out["rows"]
huge = hc.resolve(squad(), hc.owed([record(1, "plasma gun", 99)],
                                   WEAPONS, by3, squad()))
assert all(r["after"] == 0 for r in huge["rows"]), huge["rows"]
# squad() is four troopers and a sergeant, every one of them 2W.
assert huge["leftover"] == 99 - 5 * 2, huge["leftover"]
print("points with nobody left to take them are reported, not lost quietly")

# --- 10. the identity trace holds on the REAL pipeline ----------------

# Every assertion above rests on one claim about code that lives
# elsewhere: analyzer_core.select_weapons_split hands back the very
# Weapon objects that hang off the combat view's models rather than
# copies of them. If that ever stops being true the trace silently
# returns nothing and every hazard test lands on the wrong model, so it
# is checked against the real loader and not assumed.
import json                                              # noqa: E402
import analyzer_core as ac                               # noqa: E402
import leader_core as lc                                 # noqa: E402
import defender_models as dm                             # noqa: E402

data = json.load(open(testpaths.roster("space-marines.json")))
UNITS = {u["name"]: u for u in data["armies"][0]["units"]}
FLAGS = {}
checked = 0
for name, native in sorted(UNITS.items()):
    entry = lc.make_entry(native)
    unit = lc.build_entry_unit(entry, {}, set(), {}, None)
    if unit is None:
        continue
    aview, _dv = ac.build_views(unit, unit, FLAGS, {})
    weapons, _skip = ac.select_weapons_split(aview, "ranged", None, False)
    if not weapons:
        continue
    surviving = [mi for mi, _m in lc.entry_models(entry)]
    by_index, join = dm.view_by_model_index(surviving, entry, aview)
    if join:
        continue
    found, problem = hc.bearers([{"weapon": w} for w in weapons], by_index)
    assert problem is None, f"{name}: {problem}"
    assert len(found) == len(weapons), f"{name}: {found}"
    for wi, mi in found.items():
        assert weapons[wi] in by_index[mi].weapons, \
            f"{name}: weapon {wi} traced to a model that does not carry it"
    checked += 1
assert checked >= 3, f"only {checked} units exercised the real trace"
print(f"the identity trace holds on the real loader ({checked} units)")

# --- 11. aim(): the player's choice, and it keeps its hands off -------

models = squad()
one = hc.owed([record(1, "plasma gun", 1)], WEAPONS, by, models)
picked = hc.aim(one, 0, 3)
assert one[0]["target"] is None, "aim must not mutate what it was given"
assert picked[0]["target"] == 3 and picked[0]["damage"] == 1
assert [r["key"] for r in hc.changed(hc.resolve(models, picked)["rows"])] \
    == ["t3"]
assert hc.aim(picked, 0, None)[0]["target"] is None
# An index that names no entry leaves every one of them alone.
assert hc.aim(one, 9, 3) == one
print("the player's target is honoured, and aim() keeps its hands off")

print("hazard_close: all checks passed")
