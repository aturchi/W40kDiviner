"""One unit's attack sequence, resolved weapon profile by weapon profile.

The game assistant used to roll every weapon of the attacking unit in
one go and hand the player a heap of damage to write off afterwards.
That is not how the sequence runs: a weapon fires into the unit the
previous ones left behind, and 11th ed. settles the allocation groups
and their order INSIDE the Save Rolls step (Core Rules 05.03), once per
attack pool. This module is that sequence as pure state -- no tkinter,
no roster format, no widgets -- so the window on top of it only has to
draw what it says.

THE SHAPE OF ONE ACTIVATION

    arm()     roll the attacks, the hits and the wounds. Nothing has
              been allocated yet: what comes back is how many wounds
              the defender has to save against, and 'alloc' holds the
              groups and a legal order for them.
    (player)  reorder the groups, move a model down inside its group,
              point a PRECISION weapon at a CHARACTER.
    apply()   roll the saves against the model each attack is allocated
              to, roll the damage, take it off, write the result back.

The split matters: the order has to be settled BEFORE the first save
is rolled, because a save made against a 3+ cannot be moved onto a 2+
model afterwards. Between one weapon and the next everything is free
again -- the groups are BUILT AGAIN at every activation, so a model
wounded by the last weapon changes which group has to go first.

WHAT CHANGES BETWEEN ACTIVATIONS

  * the models still standing, which is what BLAST and CLEAVE count:
    the reference handed to the resolver carries the CURRENT number,
    so firing the blast weapons first is worth something against a
    big unit;
  * the groups and their default order, rebuilt from the wounds as
    they now are;
  * the firing order itself, which the player may still change for the
    weapons that have not fired.

UNDO. An activation is undone whole, dice included: the wounds go back
and the weapon returns to the queue, and firing it again rolls again.
Restoring the state while keeping the dice would let a player re-run an
allocation until the dice fell better, which is not an undo.

HAZARDOUS. The self-damage of each weapon is accumulated but not
applied: 11th ed. makes the hazard rolls after the unit has resolved
ALL of its attacks, so the total belongs to a step of its own at the
end of the sequence, against the ATTACKING unit.
"""

import alloc_groups as ag
import attack_resolve as ar


def is_precision(weapon) -> bool:
    """True for a weapon whose attacks may be sent to a CHARACTER.

    Was deliberately a copy rather than an import of the pre-roll
    proposal module this one replaced; that module has since been
    deleted, which is exactly what the copy was there to survive.
    """
    return any(str(k).strip().upper() == "PRECISION"
               for k in (getattr(weapon, "keywords", None) or ()))


def weapon_label(weapon, mech=None) -> str:
    """How a weapon reads in the firing queue."""
    count = getattr(weapon, "count", 1) or 1
    tags = []
    if mech is not None and getattr(mech, "hazardous", False):
        tags.append("HAZARDOUS")
    if is_precision(weapon):
        tags.append("PRECISION")
    suffix = ("  [" + ", ".join(tags) + "]") if tags else ""
    return f"{getattr(weapon, 'name', '?')} x{count}{suffix}"


class AttackSession:
    """weapons: [{'weapon': Weapon, 'mech': WeaponMechanics}] in the
    order they should be offered; unit_ref: the reference the WHOLE unit
    fixes ('T', 'keywords' - 'models' is filled in per activation);
    models: the alloc_groups model records of the defender, carrying
    the wounds they have now; rng: the dice.
    """

    def __init__(self, weapons, unit_ref, ctx, models, rng,
                 haz_damage: int = 1, order=None):
        self.weapons = []
        for entry in weapons:
            w, m = entry["weapon"], entry["mech"]
            self.weapons.append({"weapon": w, "mech": m,
                                 "label": weapon_label(w, m),
                                 "hazardous": bool(
                                     getattr(m, "hazardous", False)),
                                 "precision": is_precision(w)})
        self.unit_ref = dict(unit_ref or {})
        self.ctx = dict(ctx or {})
        self.models = [dict(m) for m in models]
        self.rng = rng
        self.haz_damage = haz_damage
        self._queue = (list(order) if order is not None
                       else list(range(len(self.weapons))))
        self._records = []          # one per activation already applied
        self._armed = None          # the activation waiting for apply()
        self.alloc = None           # its allocation state
        # The allocation order the player has declared, in names that
        # survive the groups being rebuilt (see alloc_groups.group_key).
        # It is kept on the SESSION and not on the Allocation because
        # the Allocation lasts one activation and this has to last the
        # whole sequence: the saves are the last step of every one of
        # them, so the order can be settled at any point before the one
        # that is about to roll them.
        self.declared = {"groups": [], "members": []}

    # ---------- the firing queue ----------

    def queue(self) -> list:
        """Weapon indices that have not fired, in the order they will."""
        return list(self._queue)

    def next_index(self):
        """The weapon at the head of the queue, or None when done."""
        return self._queue[0] if self._queue else None

    def move(self, position: int, delta: int) -> bool:
        """Move a weapon within the queue. Refused while an activation
        is armed: its dice were rolled for the weapon at the head."""
        target = position + delta
        if self._armed is not None:
            return False
        if not (0 <= position < len(self._queue)
                and 0 <= target < len(self._queue)):
            return False
        q = self._queue
        q[position], q[target] = q[target], q[position]
        return True

    def finished(self) -> bool:
        return not self._queue and self._armed is None

    # ---------- the defender as it stands now ----------

    def standing(self) -> int:
        """Models of the defender still on the battlefield."""
        return sum(1 for m in self.models if int(m.get("wounds") or 0) > 0)

    def reference(self) -> dict:
        """The unit reference for the NEXT activation: what the whole
        unit fixes, plus the model count as it is right now, which is
        what BLAST and CLEAVE read."""
        ref = dict(self.unit_ref)
        ref["models"] = self.standing()
        return ref

    def groups(self):
        """The allocation groups as they would be built right now."""
        return ag.build_groups(self.models)

    def needs_choice(self, index=None) -> bool:
        """True when this activation asks the player something the
        program must not decide: where a PRECISION weapon is pointed,
        or an allocation order the rules leave open."""
        index = self.next_index() if index is None else index
        if index is None:
            return False
        groups = self.groups()
        if not groups:
            return False
        if self.weapons[index]["precision"] and any(g["character"]
                                                    for g in groups):
            return True
        return not ag.order_is_forced(groups, self.models)

    # ---------- one activation ----------

    def preview(self):
        """The allocation as it stands, with nothing armed: the groups
        the next weapon will find and the order the player has declared
        for them. Rebuilt on demand rather than kept, because a model
        dying between activations changes the groups."""
        return ag.Allocation(self.models, prefer=self.declared["groups"],
                             members=self.declared["members"])

    def reorder(self, what: str, position: int, delta: int,
                group=None) -> bool:
        """Move a group, or a model inside its group, and REMEMBER it.

        Works whether or not an activation is armed. Before one, the
        move is made on a throw-away preview and only the declaration
        is kept; during one it is made on the live Allocation as well,
        so the attacks already rolled land where the player has just
        said. Either way the declaration outlives the activation, which
        is the point: reordering used to be possible only after Fire
        and was forgotten again at the next weapon.

        Returns False and changes nothing when the move would break one
        of the rules' constraints, so the view can refuse the gesture
        without explaining it.
        """
        alloc = self.alloc if self.alloc is not None else self.preview()
        if what == "group":
            ok = alloc.move_group(position, delta)
        else:
            ok = alloc.move_member(group, position, delta)
        if ok:
            self.declared = alloc.declaration()
        return ok

    def arm(self, index=None) -> dict:
        """Roll the attacks, the hits and the wounds of one weapon and
        stop there. Returns what the defender now has to save against;
        'self.alloc' holds the groups and a legal order to be settled
        before apply() rolls a single save."""
        if self._armed is not None:
            raise RuntimeError("an activation is already armed")
        index = self.next_index() if index is None else index
        if index not in self._queue:
            raise ValueError("that weapon has already fired")
        entry = self.weapons[index]
        # A fresh mechanics copy per activation: the resolver is allowed
        # to write on it, and the entry's own must survive a re-roll.
        mech = entry["mech"].copy()
        first = ar.resolve_weapon(entry["weapon"], self.reference(),
                                  self.ctx, mech, self.rng,
                                  self.haz_damage, defer_save=True)
        self.alloc = ag.Allocation(self.models,
                                   prefer=self.declared["groups"],
                                   members=self.declared["members"])
        self._armed = {"index": index, "mech": mech, "first": first,
                       "wounds_before": [int(m.get("wounds") or 0)
                                         for m in self.models]}
        pending = first["pending"]
        return {"index": index, "label": entry["label"],
                "attacks": first["attacks"],
                "to_save": sum(1 for p in pending if p["kind"] == "wound"),
                "mortals": sum(1 for p in pending if p["kind"] == "mortal"),
                "self_damage": first["self_damage"],
                "warnings": list(first["warnings"]),
                "precision": entry["precision"]}

    def discard(self):
        """Throw the armed activation away without applying it. The
        dice go with it: arming the same weapon again re-rolls."""
        self._armed, self.alloc = None, None

    def apply(self) -> dict:
        """Roll the saves against the model each attack is allocated to,
        roll the damage, take it off and write the result back."""
        if self._armed is None:
            raise RuntimeError("nothing is armed")
        armed = self._armed
        entry = self.weapons[armed["index"]]
        second = ar.resolve_saves(armed["first"]["pending"],
                                  entry["weapon"], armed["mech"],
                                  self.rng, self.alloc, self.ctx)
        rows = self.alloc.result()
        for model, row in zip(self.models, rows):
            model["wounds"] = row["after"]
        record = {"index": armed["index"], "label": entry["label"],
                  "attacks": armed["first"]["attacks"],
                  "self_damage": armed["first"]["self_damage"],
                  "warnings": list(armed["first"]["warnings"]),
                  "events": second["events"],
                  "saves_made": second["saves_made"],
                  "shrugged": second["shrugged"],
                  "no_target": second["no_target"],
                  "wasted": self.alloc.wasted,
                  "leftover": self.alloc.leftover,
                  "killed": self.alloc.killed(),
                  "rows": rows,
                  "wounds_before": armed["wounds_before"]}
        self._queue.remove(armed["index"])
        self._records.append(record)
        self._armed, self.alloc = None, None
        return record

    def fire(self, index=None) -> dict:
        """arm() and apply() in one move, with the default order: the
        fast path for a weapon that asks the player nothing."""
        self.arm(index)
        return self.apply()

    def fire_all(self, stop_on_choice: bool = True) -> list:
        """Fire the rest of the queue. Stops - without arming it -
        before a weapon that would ask the player something, unless
        told not to."""
        if self._armed is not None:
            raise RuntimeError("an activation is already armed")
        out = []
        while self._queue:
            index = self.next_index()
            if stop_on_choice and self.needs_choice(index):
                break
            out.append(self.fire(index))
        return out

    # ---------- history ----------

    def records(self) -> list:
        """The activations already applied, in the order they fired."""
        return list(self._records)

    def can_undo(self) -> bool:
        return bool(self._records) and self._armed is None

    def undo(self):
        """Take back the last activation, dice included: the wounds go
        back and the weapon returns to the head of the queue. Firing it
        again rolls again - see the module docstring."""
        if not self.can_undo():
            return None
        record = self._records.pop()
        for model, before in zip(self.models, record["wounds_before"]):
            model["wounds"] = before
        self._queue.insert(0, record["index"])
        return record

    def self_damage(self) -> int:
        """Hazardous self-damage owed by the attacking unit so far. Not
        applied here: 11th ed. rolls the hazard tests after the unit has
        resolved all of its attacks, so it belongs to a closing step."""
        return sum(r["self_damage"] for r in self._records)

    def killed(self) -> int:
        """Defending models destroyed by the whole sequence."""
        return sum(1 for i, m in enumerate(self.models)
                   if int(m.get("wounds") or 0) <= 0
                   and self._records
                   and self._records[0]["wounds_before"][i] > 0)

    def wiped(self) -> bool:
        return self.standing() == 0
