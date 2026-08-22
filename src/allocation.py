"""Assisted allocation of an attack's damage onto the defending models.

The game assistant rolls the attack and hands the player a list of
damaging attacks to write off by hand. This module does the arithmetic
of writing them off - which model eats what, how much is wasted, who
dies - under the allocation the rules prescribe, and leaves every real
CHOICE to the player.

The rules the arithmetic follows (the same ones kill_chain is built on,
so the estimate and the application cannot disagree):

* damage is allocated one EVENT at a time onto a single model until it
  is destroyed. Three attacks of 2 damage are not one of 6: each is
  capped separately by the wounds left on the model it lands on, and
  the excess on a model that dies is WASTED;
* a model that has already lost wounds must be allocated to first. When
  several have, which one is the player's choice - here, the first in
  the chosen order;
* DEVASTATING WOUNDS are mortal wounds for every rule that keys on
  them, but they are allocated like ordinary damage: no spill;
* mortal wounds that DO spill are pooled and applied LAST, after all
  the normal damage, one point at a time, passing from a destroyed
  model to the next.

What is left to the player, and only hinted at:

* which model to put in front (there is no 'champion' flag in the
  profiles, so the Shas'ui cannot be recognised - the player moves it
  down the order instead);
* PRECISION damage, which may be sent to an attached character;
* anything else the table decided. Every number the dialog proposes is
  editable before it is applied.

No tkinter: the whole allocation is a function from state to state.
"""

# Event kinds, as attack_resolve produces them.
KIND_DAMAGE = "damage"
KIND_MORTAL = "mortal"


def is_precision(weapon) -> bool:
    return any(str(k).strip().upper() == "PRECISION"
               for k in (getattr(weapon, "keywords", None) or ()))


def events_from_results(results) -> list:
    """Flatten the game assistant's [(weapon, hazardous, result)] into
    the events to allocate, in the order they were rolled.

    'spills' is carried from the event itself (attack_resolve sets it:
    False for a devastating wound, True for a real mortal wound), and
    'precision' from the weapon, because the rules let those be sent to
    a character of the attacker's choice - a decision, not a number."""
    out = []
    for weapon, _hazardous, res in results or ():
        prec = is_precision(weapon)
        for e in res.get("events") or ():
            amount = int(e.get("amount", 0) or 0)
            if amount <= 0:
                continue
            mortal = e.get("kind") == KIND_MORTAL
            out.append({"kind": e.get("kind"), "amount": amount,
                        "spills": bool(mortal and e.get("spills", True)),
                        "mortal": mortal, "precision": prec,
                        "weapon": str(getattr(weapon, "name", "?"))})
    return out


def split_events(events):
    """(events allocated one at a time, pooled spilling mortal wounds).
    The pool is a single number: spilling wounds are applied one point
    at a time, so their grouping into events carries no meaning."""
    normal = [e for e in events or () if not e.get("spills")]
    pool = sum(int(e.get("amount", 0) or 0)
               for e in events or () if e.get("spills"))
    return normal, pool


def totals(events) -> dict:
    """What there is to allocate, by category."""
    normal, pool = split_events(events)
    dev = [e for e in normal if e.get("mortal")]
    plain = [e for e in normal if not e.get("mortal")]
    return {"events": len(normal) + (1 if pool else 0),
            "damage": sum(e["amount"] for e in events or ()),
            "plain_events": len(plain),
            "plain": sum(e["amount"] for e in plain),
            "dev_events": len(dev),
            "devastating": sum(e["amount"] for e in dev),
            "spill": pool,
            "precision": sum(e["amount"] for e in events or ()
                             if e.get("precision"))}


def allocate(copies, events, order=None) -> dict:
    """Apply 'events' to 'copies' and return the proposal.

    copies: [{'iid', 'label', 'wounds', 'max'}] - one entry per model
    still on the table, 'wounds' its remaining wounds.
    order:  indices into 'copies', the order in which they take damage
            (default: as given). A model that has already lost wounds
            still goes first, as the rules require.

    Returns {'state': [...], 'wasted', 'leftover', 'killed', 'steps'},
    where 'state' mirrors 'copies' with 'after' and 'dead' filled in and
    'steps' records every event: (copy index or None, applied, wasted).
    """
    order = list(order if order is not None else range(len(copies)))
    left = [max(0, int(c.get("wounds") or 0)) for c in copies]
    caps = [max(1, int(c.get("max") or 1)) for c in copies]
    wasted = leftover = 0
    steps = []

    def front():
        """The model the next event lands on: one that has already lost
        wounds if there is one (the rules require it), otherwise the
        first alive model of the chosen order."""
        alive = [i for i in order if 0 <= i < len(left) and left[i] > 0]
        if not alive:
            return None
        hurt = [i for i in alive if left[i] < caps[i]]
        return hurt[0] if hurt else alive[0]

    normal, pool = split_events(events)
    for e in normal:
        amount = int(e.get("amount", 0) or 0)
        i = front()
        if i is None:                     # the unit is already wiped out
            leftover += amount
            steps.append((None, 0, 0))
            continue
        applied = min(amount, left[i])
        left[i] -= applied
        wasted += amount - applied
        steps.append((i, applied, amount - applied))
    # The spilling mortal wounds, last and one point at a time: nothing
    # of them is ever wasted, they simply run out of models.
    while pool > 0:
        i = front()
        if i is None:
            leftover += pool
            break
        take = min(pool, left[i])
        left[i] -= take
        pool -= take
        steps.append((i, take, 0))

    state = []
    for i, c in enumerate(copies):
        before = max(0, int(c.get("wounds") or 0))
        state.append({"iid": c.get("iid"), "label": c.get("label", "?"),
                      "before": before, "after": left[i],
                      "max": caps[i], "damage": before - left[i],
                      "dead": left[i] <= 0 and before > 0})
    return {"state": state, "wasted": wasted, "leftover": leftover,
            "killed": sum(1 for s in state if s["dead"]), "steps": steps}


def hints(events, copies, plan) -> list:
    """What the player has to decide, and what the arithmetic assumed.

    Deliberately short: a wall of text at the table is not read."""
    out = []
    t = totals(events)
    hurt = [c for c in copies
            if 0 < int(c.get("wounds") or 0) < int(c.get("max") or 1)]
    if hurt:
        out.append("Already wounded: " + ", ".join(
            c.get("label", "?") for c in hurt[:3])
            + " - the rules make you allocate there first.")
    if t["dev_events"]:
        out.append(f"{t['devastating']} damage from DEVASTATING WOUNDS "
                   f"({t['dev_events']} events): mortal for every rule "
                   "that keys on them, but they do NOT spill - the "
                   "excess on a destroyed model is wasted.")
    if t["spill"]:
        out.append(f"{t['spill']} mortal wounds spill over: applied "
                   "last, one at a time, passing to the next model.")
    if t["precision"]:
        out.append(f"{t['precision']} damage comes from PRECISION "
                   "weapons and may be sent to an attached character "
                   "instead - the proposal does not do it for you.")
    out.append("No 'champion' flag exists in the profiles: move the "
               "model you want to keep alive to the bottom of the "
               "order.")
    if plan.get("leftover"):
        out.append(f"{plan['leftover']} damage has nowhere to go: the "
                   "unit is destroyed.")
    return out


def summary(plan) -> str:
    """One line under the table."""
    bits = [f"{plan['killed']} models destroyed",
            f"{sum(s['damage'] for s in plan['state'])} wounds removed"]
    if plan["wasted"]:
        bits.append(f"{plan['wasted']} wasted on destroyed models")
    if plan["leftover"]:
        bits.append(f"{plan['leftover']} left over")
    return ", ".join(bits)
