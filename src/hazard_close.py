"""The HAZARDOUS closing step, as data.

11th ed. rolls the hazard tests after the attacking unit has resolved
all of its attacks, so the self-damage a session accumulates is owed by
the unit at the END of the sequence and not weapon by weapon. This
module answers the two questions that closing step asks, and nothing
else: WHO owes it, and WHERE the mortal wounds land first.

Each failed test costs the unit mortal wounds -- three when the unit is
a MONSTER or a VEHICLE, one otherwise (attack_math.hazardous_damage_per_
fail, already applied by the resolver) -- and they spill like any other
mortal wound: a point that outlives the model it landed on passes to the
next by the 06.02 sequence rather than being lost.

They land wherever any other mortal wound would: the 06.02 sequence
decides, and the wound spills across the WHOLE unit rather than stopping
at the model that failed the test. The bearer has no special standing in
the rules - it did in an earlier version of this module, which allocated
from the bearer outwards, and that was wrong.

The bearer is still worked out, because it is worth SHOWING: it says
which model group the test came from, which is what a player weighing up
where to put the wounds wants to know. The weapon is traced back to its
group by identity - analyzer_core.select_weapons_split appends the very
Weapon objects that hang off the view's models, it does not copy them -
and when the trace fails it is REPORTED, never guessed.

Where the wounds actually go is the PLAYER's to say. Each entry carries
a 'target': None means the sequence decides, and a model index means the
player has pointed that weapon's wounds at a model of their choosing.
A wound larger than its target still spills on from there.

Nothing here rolls a die: the tests were rolled inside the resolver and
their outcome is already in the session's records. Nothing here draws
either - the caller renders the rows and decides whether to apply them.
"""

import alloc_groups as ag


def bearers(weapons, by_index):
    """({weapon index: model-group index}, problem).

    'weapons' is the session's weapon list ([{'weapon', 'mech'}, ...]);
    'by_index' is {model-group index: combat-view model}, which is what
    defender_models.view_by_model_index returns for the attacker.

    A weapon that cannot be traced is simply absent from the map, and
    'problem' names how many were lost. The caller can still close the
    step - the mortal wounds start at the top of the 06.02 sequence
    instead - and can say that the bearer is a guess.
    """
    owner = {}
    for mi, model in (by_index or {}).items():
        for w in getattr(model, "weapons", ()) or ():
            owner.setdefault(id(w), mi)
    out, lost = {}, 0
    for index, pair in enumerate(weapons):
        mi = owner.get(id(pair.get("weapon")))
        if mi is None:
            lost += 1
        else:
            out[index] = mi
    problem = None
    if lost:
        problem = (f"{lost} of {len(weapons)} weapons could not be traced "
                   "to the model carrying them")
    return out, problem


def _first_alive(models, mi):
    """The copy of model group 'mi' a hazard test is charged to.

    Every copy of a group has the same profile, so any live one is as
    good as another; the champion order is used so the choice is
    deterministic and the scarce copy of a group is still spent last.
    """
    members = [i for i, m in enumerate(models)
               if m.get("entry") == mi and int(m.get("wounds") or 0) > 0]
    if not members:
        return None
    return ag.member_order(members, models)[0]


def owed(records, weapons, bearer_of, models):
    """One entry per activation that failed at least one hazard test.

    [{'index', 'label', 'damage', 'bearer'}] in the order the weapons
    fired. 'bearer' is the model the mortal wounds start on, or None
    when the weapon could not be traced or every copy of its group is
    already gone - in both cases the 06.02 sequence decides on its own.
    """
    out = []
    for record in records:
        damage = int(record.get("self_damage") or 0)
        if damage <= 0:
            continue
        index = record.get("index")
        mi = bearer_of.get(index)
        out.append({"index": index,
                    "label": record.get("label")
                    or _weapon_name(weapons, index),
                    "damage": damage,
                    # Shown, not obeyed: see the module docstring.
                    "bearer": None if mi is None
                    else _first_alive(models, mi),
                    # The player's choice, once they have made one.
                    "target": None})
    return out


def _weapon_name(weapons, index):
    if index is None or not (0 <= index < len(weapons)):
        return "?"
    return getattr(weapons[index].get("weapon"), "name", "?")


def aim(items, index, target=None) -> list:
    """A copy of 'items' with the entry at 'index' pointed at 'target'.

    A copy rather than a mutation so the caller can recompute from the
    original list every time and never accumulate a half-applied state:
    the whole closing step is cheap to redo.
    """
    out = []
    for n, item in enumerate(items):
        out.append(dict(item, target=target) if n == index else dict(item))
    return out


def total(items) -> int:
    """Mortal wounds the whole closing step owes."""
    return sum(int(i.get("damage") or 0) for i in items)


def resolve(models, items):
    """Apply every entry of 'owed' to a copy of the attacker's records.

    Returns {'alloc', 'rows', 'leftover'}. 'rows' is
    alloc_groups.Allocation.result() - one entry per model, with the
    wounds it started and finished with - and 'leftover' the points that
    had no model left to take them, which happens only when the unit
    kills itself outright.

    The models are NOT modified: the Allocation works on its own copy of
    the wounds, so the caller can show the outcome and still let the
    player back out of it.
    """
    alloc = ag.Allocation(models)
    for item in items:
        # No target unless the player set one: hazardous mortal wounds
        # go where any other mortal wound goes. A target names ONE
        # model and a wound that outlives it carries on by the ordinary
        # sequence, so pointing it somewhere never loses a point.
        alloc.allocate(item.get("damage"), spill=True,
                       target=item.get("target"))
    return {"alloc": alloc, "rows": alloc.result(),
            "leftover": alloc.leftover}


def changed(rows) -> list:
    """The rows of resolve() that a caller has to write back."""
    return [r for r in rows if r["after"] != r["before"]]


def log_entry(items, rows):
    """The closing step as one attack-log field.

    Kept apart from the 'allocation' the defender fills in: that one is
    summed by attack_log.allocation_totals, and folding damage the
    ATTACKER did to itself into those totals would report it as damage
    dealt to the enemy.
    """
    hurt = changed(rows)
    return {"damage": total(items),
            "weapons": [{"label": i["label"], "damage": i["damage"]}
                        for i in items],
            "models": [{"label": r["label"], "before": r["before"],
                        "after": r["after"]} for r in hurt],
            "killed": sum(1 for r in hurt if r["dead"])}
