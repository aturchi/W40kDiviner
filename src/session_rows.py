"""What the attack window shows, as data.

The window that replaced the results report and the allocation dialog
has two panels: the weapons of the attacking unit on the left, in the
order they will fire, and the defending unit on the right, grouped the
way the Save Rolls step groups it. Both change after every activation -
a weapon leaves the queue, models die, the allocation groups are built
again - and the buttons come and go with them.

None of that needs Tkinter to be decided, so none of it is decided in
Tkinter. This module turns an attack_session.AttackSession into rows,
button states and lines of text; the widget on top only draws them.
That is the same split as dist_stats/dist_view, and it exists because a
window cannot be tested on a machine with no display, while a list of
dictionaries can.

Rows are SEMANTIC: they carry what a thing is, not how wide its column
should be. The view decides the formatting, so a change of wording or
column order cannot break a test about the rules.
"""

import alloc_groups as ag

# Weapon states, left panel.
QUEUED = "queued"        # waiting its turn
NEXT = "next"            # at the head of the queue
ARMED = "armed"          # its dice are rolled, waiting for Apply
DONE = "done"            # fired: greyed out and no longer selectable
SKIPPED = "skipped"      # never offered (out of range, wrong phase...)

# Model states, right panel.
FULL = "full"
HURT = "hurt"
DEAD = "dead"


def allocation_of(session):
    """The allocation the right panel is showing: the one belonging to
    the armed activation, or a preview of the target as it stands now.

    The second value says whether an activation is armed, which the
    panel still needs - a preview has no dice behind it and no
    PRECISION to offer. It no longer means "read-only": the preview is
    rebuilt on every call and anything done to it would be lost, so the
    window reorders through session.reorder(), which remembers the
    declaration instead of the object."""
    if session.alloc is not None:
        return session.alloc, True
    return session.preview(), False


def weapon_rows(session, skipped=()) -> list:
    """One row per weapon: the queue in firing order, then the weapons
    already fired in the order they fired, then the ones never offered.

    'skipped' is [(label, reason)] from the weapon selection, which the
    session never sees: a weapon out of range is not part of the attack,
    but leaving it off the panel entirely makes the player wonder where
    it went.
    """
    rows, armed = [], session._armed
    armed_index = armed["index"] if armed else None
    for position, index in enumerate(session.queue()):
        entry = session.weapons[index]
        if index == armed_index:
            state = ARMED
        elif position == 0:
            state = NEXT
        else:
            state = QUEUED
        rows.append({"kind": "weapon", "index": index,
                     "label": entry["label"], "state": state,
                     "position": position,
                     "precision": entry["precision"],
                     "hazardous": entry["hazardous"],
                     "selectable": state != ARMED,
                     "movable": armed is None and state != DONE,
                     "attacks": None, "killed": None, "note": ""})
    for record in session.records():
        rows.append({"kind": "weapon", "index": record["index"],
                     "label": record["label"], "state": DONE,
                     "position": None,
                     "precision": session.weapons[record["index"]]
                     ["precision"],
                     "hazardous": session.weapons[record["index"]]
                     ["hazardous"],
                     "selectable": False, "movable": False,
                     "attacks": record["attacks"],
                     "killed": record["killed"],
                     "note": activation_note(record)})
    for label, reason in skipped:
        rows.append({"kind": "weapon", "index": None, "label": label,
                     "state": SKIPPED, "position": None,
                     "precision": False, "hazardous": False,
                     "selectable": False, "movable": False,
                     "attacks": None, "killed": None, "note": reason})
    return rows


def _model_state(model) -> str:
    left = int(model.get("wounds") or 0)
    cap = int(model.get("max") or 1)
    if left <= 0:
        return DEAD
    return HURT if left < cap else FULL


def target_rows(session, record=None) -> list:
    """The defending unit as the Save Rolls step sees it: one row per
    allocation group, in the order they take attacks, each followed by
    its models in the order damage lands on them.

    A group row is 'current' when it is the one the next attack would
    be allocated to (05.04.01), which is what tells the player where the
    damage is about to go. 'record' is an activation just applied, and
    adds the damage each model took to its row.

    Destroyed models are listed apart, under a section of their own.
    They belong to no group - a model that is gone cannot be grouped or
    allocated to, so build_groups leaves it out - but dropping them from
    the panel would make rows silently vanish between one weapon and the
    next, and an undo would have to conjure them back.
    """
    alloc, live = allocation_of(session)
    # A group or a live model can be moved whether or not a weapon is
    # armed: session.reorder() keeps the declaration, so a move made on
    # a preview is not lost. 'live' still decides what is DRAWN - the
    # current group, the PRECISION mark - because those need dice.
    movable = True
    damage = {}
    if record:
        damage = {r["key"]: r["damage"] for r in record["rows"]
                  if r["damage"]}
    current = alloc.current_group()
    rows = []
    for position, gi in enumerate(alloc.order):
        group = alloc.groups[gi]
        rows.append({"kind": "group", "group": gi, "position": position,
                     "label": group["label"],
                     "character": group["character"],
                     "current": gi == current,
                     "precision": alloc.precision == gi,
                     "movable": movable, "casualties": False,
                     "models": len([i for i in group["members"]
                                    if alloc.left[i] > 0])})
        for slot, mi in enumerate(group["members"]):
            rows.append(_model_row(alloc, gi, slot, mi, damage,
                                   movable))
    fallen = [i for i in range(len(alloc.models)) if alloc.left[i] <= 0]
    if fallen:
        rows.append({"kind": "group", "group": None,
                     "position": len(alloc.order), "label": "Destroyed",
                     "character": False, "current": False,
                     "precision": False, "movable": False,
                     "casualties": True, "models": 0})
        for slot, mi in enumerate(fallen):
            # 'movable' is passed through unchanged: whether a fallen
            # model may be moved is decided in ONE place, by the group
            # being None, and not by two guards that can drift apart.
            rows.append(_model_row(alloc, None, slot, mi, damage,
                                   movable))
    return rows


def _model_row(alloc, gi, slot, mi, damage, movable) -> dict:
    model = alloc.models[mi]
    left = alloc.left[mi]
    return {"kind": "model", "group": gi, "model": mi, "slot": slot,
            "label": model.get("label", "?"), "wounds": left,
            "max": int(model.get("max") or 1),
            "state": _model_state(dict(model, wounds=left)),
            "damage": damage.get(model.get("key"), 0),
            "movable": movable and gi is not None}


def buttons(session) -> dict:
    """Which actions the window may offer right now.

    Move up/down on the weapons is off while an activation is armed:
    those dice were rolled for the weapon at the head of the queue. Move
    on the GROUPS is on only while armed, because a preview allocation
    is discarded and reordering it would do nothing the player can see.
    """
    armed = session._armed is not None
    alloc, live = allocation_of(session)
    has_target = alloc.current_model() is not None
    return {"fire": not armed and bool(session.queue()) and has_target,
            "fire_all": not armed and bool(session.queue()) and has_target,
            "apply": armed,
            "discard": armed,
            "undo": session.can_undo(),
            "move_weapon": not armed and len(session.queue()) > 1,
            # Not gated on an activation being armed. The saves are the
            # LAST step of every activation, so the order can be settled
            # at any point before the one about to roll them - and
            # settling it after Fire only, as this did, meant the choice
            # was made under time pressure and forgotten at the next
            # weapon.
            "move_group": len(alloc.groups) > 1,
            "move_model": bool(alloc.groups),
            "precision": (live and bool(alloc.character_groups())
                          and session.weapons[session._armed["index"]]
                          ["precision"] if armed else False)}


def headline(session, armed=None) -> str:
    """The line at the top: what the player is looking at."""
    if armed:
        parts = [f"{armed['attacks']} attacks"]
        if armed["to_save"]:
            parts.append(f"{armed['to_save']} wounds to save")
        if armed["mortals"]:
            parts.append(f"{armed['mortals']} mortal wounds")
        if not armed["to_save"] and not armed["mortals"]:
            parts.append("nothing got through")
        return f"{armed['label']}: " + ", ".join(parts)
    if session.wiped():
        return "The target unit has been destroyed."
    if session.finished():
        return "Every weapon has fired."
    index = session.next_index()
    return (f"Next: {session.weapons[index]['label']} - "
            f"{session.standing()} models standing")


def activation_note(record) -> str:
    """One line summarising an activation that has been applied."""
    bits = []
    if record["killed"]:
        bits.append(f"{record['killed']} destroyed")
    if record["saves_made"]:
        bits.append(f"{record['saves_made']} saved")
    if record["shrugged"]:
        bits.append(f"{record['shrugged']} shrugged")
    if record["wasted"]:
        bits.append(f"{record['wasted']} wasted")
    if record["no_target"]:
        bits.append(f"{record['no_target']} with no target")
    if record["self_damage"]:
        bits.append(f"{record['self_damage']} hazardous")
    return ", ".join(bits) or "no effect"


def hint(session) -> str:
    """Why the run stopped here, when it did. Empty when there is
    nothing the player has to decide."""
    index = session.next_index()
    if index is None or not session.needs_choice(index):
        return ""
    alloc, _live = allocation_of(session)
    if (session.weapons[index]["precision"]
            and any(g["character"] for g in alloc.groups)):
        return ("This weapon has PRECISION: you can legally move the "
                "model order as you want.")
    return ("Move the model order as you like. Legally, character "
            "models should go last.")


def closing_note(session) -> str:
    """What is still owed when the sequence ends. Hazardous self-damage
    is rolled per weapon but belongs to the attacking unit, after all
    of its attacks have been resolved."""
    owed = session.self_damage()
    if not owed:
        return ""
    return (f"{owed} mortal wounds from HAZARDOUS still to allocate to "
            f"the attacking unit.")
