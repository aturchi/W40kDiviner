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

They land on the BEARER first, which is the whole reason this module
exists. The unit-wide pool the session hands back has no bearer in it,
so the weapon has to be traced back to the model group carrying it. The
combat view keeps the very Weapon objects that hang off its models -
analyzer_core.select_weapons_split appends them, it does not copy them -
so the trace is an identity lookup and not a match on names. When it
fails it is REPORTED, never guessed: an unattributed point is allocated
from the top of the 06.02 sequence, which is a defensible answer, while
a point put on the wrong model is not.

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
    return ag._member_order(members, models)[0]


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
                    "bearer": None if mi is None
                    else _first_alive(models, mi)})
    return out


def _weapon_name(weapons, index):
    if index is None or not (0 <= index < len(weapons)):
        return "?"
    return getattr(weapons[index].get("weapon"), "name", "?")


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
        # target names ONE model: a spilling wound that outlives the
        # bearer carries on by the ordinary sequence, which is exactly
        # what the rule says happens.
        alloc.allocate(item.get("damage"), spill=True,
                       target=item.get("bearer"))
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
