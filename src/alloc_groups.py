"""Allocation groups: which model of the target unit an attack lands on.

11th ed. resolves the Save Rolls step (Core Rules 05.03) in three parts:

  1. CREATE GROUPS -- one group for each CHARACTER model, plus one
     group for all other models that share the same W, Sv and InSv;
  2. ALLOCATION ORDER -- the defender declares the order in which those
     groups take attacks, under three constraints;
  3. MAKE SAVE ROLLS -- one save roll per wounding attack, made against
     the CURRENT group, which only changes once every model in it has
     been destroyed (05.04.01).

Everything the game assistant needs from that sequence lives here as
pure data: no tkinter, no roster format, no dice, no imports from the
project. The caller hands over one record per model still standing and
gets back the groups, a legal default order, a validator for an order
the player has changed, and a mutable state that answers "which model
does the next attack hit" and takes the damage off it.

WHY THIS MODULE EXISTS. Until now a single reference profile was chosen
for the whole attack, so a Captain led by his Intercessors saved on the
Intercessors' 3+ -- or the Intercessors saved on the Captain's 2+, if
that was the profile picked. Toughness IS a property of the whole unit
(highest among the BODYGUARD models, and fixed for as long as the
attacking unit is resolving its attacks), but the Save is a property of
the model the attack was allocated to. They are two different things,
and only the first one was modelled.

INPUT RECORDS. One dict per PHYSICAL model, in table order:

    key       hashable identity (the tree row id, in the assistant)
    label     what to show the player
    wounds    wounds it has left right now
    max       its W characteristic
    sv        Save characteristic (None -> no armour save)
    invuln    invulnerable save, None when it has none
    fnp       Feel No Pain, None when it has none
    character True for a model of an attached Leader or Support part.
              NOT read off the CHARACTER keyword: a combined unit
              carries the UNION of its parts' keywords, so every model
              of an Attached unit has CHARACTER and the keyword cannot
              tell them apart. Only the structure knows.
    entry     index of the roster model group the copy belongs to
    scarcity  how many copies that model group had at FULL strength

Models with no wounds left are dropped from the groups: a destroyed
model cannot be grouped, and cannot have an attack allocated to it.
They are still carried in the state, so the caller gets a row back for
every record it passed in.

SCARCITY is the champion heuristic. There is no 'champion' flag in the
datasheets, but a squad lists its Sergeant as a model group of its own
with model_count 1 next to nine identical bodies, so the RARE profile
is the one worth keeping alive and the default order spends the common
models first. It ranks BELOW the wounded rule -- a wounded champion is
still spent first, because finishing off a hurt model is what the rules
do one level up and it wastes less damage. A default only: the player
reorders.
"""

# Reasons order_problem() can give, as constants so the view and the
# tests do not each carry their own copy of the wording.
ERR_PERMUTATION = "the order must list every group exactly once"
ERR_CHARACTER_EARLY = ("a CHARACTER group cannot come before a "
                       "non-CHARACTER group")
ERR_WOUNDED_LATE = ("a group holding a wounded model must come before "
                    "the groups that hold none")


def _int(value, default=0):
    """int(value) with a fallback: the wounds cells can hold free text."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _profile(model):
    """Grouping key of a model: W, Sv and InSv, as 05.03 step 1 lists
    them, plus Feel No Pain. FNP is not part of the rules' key because
    the rules take it to be a property of the whole unit; this engine
    allows it per model, so splitting on it as well is STRICTER than
    the rules and never wrong where the rules apply."""
    return (_int(model.get("max"), 1), model.get("sv"),
            model.get("invuln"), model.get("fnp"))


def _is_wounded(model):
    """True for a model standing with less than its full wounds. A
    destroyed model is not wounded -- it is gone."""
    left, cap = _int(model.get("wounds")), _int(model.get("max"), 1)
    return 0 < left < cap


def _group_label(members, models):
    """Caption of a group: the model's own label when it is alone (a
    CHARACTER always is), otherwise how many models share the profile
    and what that profile saves on."""
    if len(members) == 1:
        return str(models[members[0]].get("label", "?"))
    m = models[members[0]]
    sv = m.get("sv")
    inv = f" inv{m['invuln']}+" if m.get("invuln") else ""
    fnp = f" fnp{m['fnp']}+" if m.get("fnp") else ""
    save = f"Sv{sv}+" if sv is not None else "no save"
    return (f"{len(members)} models  (W{_int(m.get('max'), 1)} "
            f"{save}{inv}{fnp})")


def _member_order(members, models):
    """Members of one group in the order they take damage.

    Four keys. The WOUNDED model goes FIRST: that is what the rules do
    one level up, where a group holding a wounded model must precede
    the groups that hold none, and it wastes less than opening a fresh
    body. Among models in the same state the RAREST profile goes LAST
    -- the champion heuristic -- so scarcity is the weaker of the two
    and a wounded champion is still spent first. The table order breaks
    whatever is left, so the result is stable.
    """
    def key(i):
        m = models[i]
        return (0 if _is_wounded(m) else 1,
                -_int(m.get("scarcity"), 1),
                _int(m.get("entry"), 0), i)

    return sorted(members, key=key)


def build_groups(models) -> list:
    """Allocation groups of 'models' (05.03 step 1), in table order.

    Returns [{'label', 'character', 'profile', 'members', 'ref'}], where
    'members' are indices into 'models' already in the order they take
    damage and 'ref' is the defensive profile of the group in the shape
    the attack maths expects ('Sv', 'invuln', 'fnp', 'W').

    One group per CHARACTER model; every other model joins the group of
    its profile. Destroyed models are left out entirely.
    """
    groups, by_profile = [], {}
    for i, m in enumerate(models):
        if _int(m.get("wounds")) <= 0:
            continue                        # destroyed: cannot be grouped
        if m.get("character"):
            groups.append({"character": True, "profile": _profile(m),
                           "members": [i]})
            continue
        key = _profile(m)
        g = by_profile.get(key)
        if g is None:
            g = {"character": False, "profile": key, "members": []}
            by_profile[key] = g
            groups.append(g)
        g["members"].append(i)
    for g in groups:
        g["members"] = _member_order(g["members"], models)
        m = models[g["members"][0]]
        g["ref"] = {"Sv": m.get("sv"), "invuln": m.get("invuln"),
                    "fnp": m.get("fnp"), "W": _int(m.get("max"), 1)}
        g["label"] = _group_label(g["members"], models)
    return groups


def _tier(group, models):
    """Which of the four blocks of the allocation order a group belongs
    to. The rules fix the blocks; the order INSIDE a block is free.

      0  non-CHARACTER, holds a wounded model  -- must be first
      1  non-CHARACTER, holds none
      2  CHARACTER, holds a wounded model      -- before block 3
      3  CHARACTER, holds none
    """
    wounded = any(_is_wounded(models[i]) for i in group["members"])
    return (2 if group["character"] else 0) + (0 if wounded else 1)


def default_order(groups, models) -> list:
    """A legal allocation order (05.03 step 2): the four blocks of
    _tier in sequence, and inside a block the most numerous group
    first -- the scarcity rule again, one level up, so a lone model
    with its own save profile is spent after the rank and file."""
    idx = list(range(len(groups)))
    return sorted(idx, key=lambda i: (_tier(groups[i], models),
                                      -len(groups[i]["members"]), i))


def order_is_forced(groups, models) -> bool:
    """True when the rules leave the defender no choice at all, so the
    order can be settled without asking. That happens exactly when no
    two groups share a block of _tier: with a bodyguard unit and one
    attached CHARACTER the two sit in different blocks and the order is
    fixed, while two untouched non-CHARACTER groups sit in the same one
    and the player must pick."""
    tiers = [_tier(g, models) for g in groups]
    return len(set(tiers)) == len(tiers)


def order_problem(groups, order, models):
    """Why 'order' is not a legal allocation order, or None if it is.

    The three constraints of 05.03 step 2. Note the second one is
    written as "a group holding a wounded model comes before those that
    hold none" WITHIN its half of the order rather than "must be
    first": several groups can hold a wounded model, and the rules let
    those be ordered freely among themselves.
    """
    order = list(order)
    if sorted(order) != list(range(len(groups))):
        return ERR_PERMUTATION
    tiers = [_tier(groups[i], models) for i in order]
    for a, b in zip(tiers, tiers[1:]):
        # A CHARACTER block (2, 3) may never precede a non-CHARACTER
        # one (0, 1).
        if a >= 2 and b < 2:
            return ERR_CHARACTER_EARLY
        # Inside either half, wounded before unwounded.
        if a == 1 and b == 0 or a == 3 and b == 2:
            return ERR_WOUNDED_LATE
    return None


class Allocation:
    """Mutable state of ONE attack sequence against one unit.

    Built from the model records, it holds the groups, the order they
    take attacks in and the wounds every model has left, and answers the
    only question the dice resolver needs: which model is the attack
    allocated to, so whose Save and whose Feel No Pain apply.

    The order is meant to be settled BEFORE any save is rolled, which is
    what the rules require and what makes the state consistent: a save
    already rolled against a 3+ cannot be moved onto a 2+ model after
    the fact. Between one weapon profile and the next the whole
    sequence starts again, so the order is free to change there.
    """

    def __init__(self, models, order=None):
        self.models = [dict(m) for m in models]
        self.before = [_int(m.get("wounds")) for m in self.models]
        self.left = list(self.before)
        self.groups = build_groups(self.models)
        self.order = (default_order(self.groups, self.models)
                      if order is None else list(order))
        problem = order_problem(self.groups, self.order, self.models)
        if problem:
            raise ValueError(problem)
        # The CHARACTER group a PRECISION weapon is sending its attacks
        # to, or None. An override, not a reordering: it lasts for one
        # activation and never changes the declared order.
        self.precision = None
        self.wasted = 0            # damage lost on a model that died
        self.leftover = 0          # damage with nowhere left to go
        self.steps = []            # (model index or None, applied, wasted)

    # ---------- order ----------

    def set_order(self, order):
        """Replace the allocation order, refusing an illegal one."""
        problem = order_problem(self.groups, order, self.models)
        if problem:
            raise ValueError(problem)
        self.order = list(order)

    def move_group(self, position: int, delta: int) -> bool:
        """Move the group at 'position' of the order by 'delta' places.
        Returns False and changes nothing when the result would break
        one of the rules' constraints, so the view can simply refuse
        the gesture instead of explaining it."""
        target = position + delta
        if not (0 <= position < len(self.order)
                and 0 <= target < len(self.order)):
            return False
        order = list(self.order)
        order[position], order[target] = order[target], order[position]
        if order_problem(self.groups, order, self.models):
            return False
        self.order = order
        return True

    def move_member(self, group: int, position: int, delta: int) -> bool:
        """Move a model inside its group. Always allowed: every model of
        a group shares W, Sv and InSv, so which of them dies first is a
        preference of the player's and changes no roll -- this is where
        the Sergeant is kept alive."""
        members = self.groups[group]["members"]
        target = position + delta
        if not (0 <= position < len(members) and 0 <= target < len(members)):
            return False
        members[position], members[target] = (members[target],
                                              members[position])
        return True

    def character_groups(self) -> list:
        """Indices of the CHARACTER groups still standing -- what a
        PRECISION weapon may choose between."""
        return [i for i, g in enumerate(self.groups)
                if g["character"] and self._group_alive(i)]

    def set_precision(self, group=None):
        """Send this activation's attacks to a CHARACTER group, or take
        the override off with None. The CHOICE is the player's: the
        rules allow it, they never require it, and a wound spent on a
        healthy character kills no model at all."""
        if group is not None:
            if not (0 <= group < len(self.groups)
                    and self.groups[group]["character"]):
                raise ValueError("PRECISION can only pick a CHARACTER "
                                 "group")
        self.precision = group

    # ---------- who takes the next attack ----------

    def _group_alive(self, group: int) -> bool:
        return any(self.left[i] > 0 for i in self.groups[group]["members"])

    def current_group(self):
        """The group the next attack is allocated to (05.04.01): the
        first one of the order with a model still standing. A PRECISION
        override wins while its group is standing -- once it is not,
        the declared order takes over again."""
        if self.precision is not None and self._group_alive(self.precision):
            return self.precision
        for gi in self.order:
            if self._group_alive(gi):
                return gi
        return None

    def current_model(self):
        """Index of the model the next attack lands on, or None when
        the unit has been wiped out."""
        gi = self.current_group()
        if gi is None:
            return None
        return next(i for i in self.groups[gi]["members"] if self.left[i] > 0)

    def ref_of(self, model: int) -> dict:
        """Defensive profile of one model, in the shape the attack maths
        reads ('Sv', 'invuln', 'fnp', 'W')."""
        m = self.models[model]
        return {"Sv": m.get("sv"), "invuln": m.get("invuln"),
                "fnp": m.get("fnp"), "W": _int(m.get("max"), 1)}

    def ref(self):
        """Defensive profile of the model the next attack lands on, or
        None when there is nothing left to allocate to."""
        i = self.current_model()
        return None if i is None else self.ref_of(i)

    def mortal_model(self):
        """Index of the model a SPILLING mortal wound is allocated to,
        or None. Mortal wounds have a selection sequence of their own
        (06.02) which is NOT the declared allocation order: a wounded
        non-CHARACTER, else any non-CHARACTER, else a wounded CHARACTER,
        else a CHARACTER. Among equals the champion heuristic picks, so
        the rare model is still spent last."""
        alive = [i for i in self._pref_order() if self.left[i] > 0]
        if not alive:
            return None
        for want_char in (False, True):
            pool = [i for i in alive
                    if bool(self.models[i].get("character")) == want_char]
            if not pool:
                continue
            hurt = [i for i in pool
                    if self.left[i] < _int(self.models[i].get("max"), 1)]
            return (hurt or pool)[0]
        return None

    def _pref_order(self):
        """Every model, in the champion-heuristic order, ignoring the
        groups: the sequence mortal wounds are selected along."""
        return _member_order(list(range(len(self.models))), self.models)

    # ---------- applying damage ----------

    def allocate(self, amount: int, spill: bool = False,
                 target=None) -> list:
        """Take 'amount' damage off the unit; returns [(model, applied)].

        A normal damage event -- and a DEVASTATING mortal wound, which
        is a mortal wound for every rule that keys on it but is
        allocated like ordinary damage -- lands on ONE model and is
        capped by the wounds that model has left: the excess is WASTED.
        A spilling mortal wound is applied one point at a time and
        passes from a destroyed model to the next, so nothing of it is
        lost until the unit itself is gone.

        'target' names the model explicitly. A caller that had to pick
        the model BEFORE rolling something against it -- the save, or
        the Feel No Pain of the model a spilling wound landed on -- must
        pass the model it picked, so that the roll and the wound cannot
        drift onto two different models. It names ONE model: a spilling
        wound that outlives it carries on by the usual sequence. A
        target with nothing left is ignored.
        """
        amount = max(0, _int(amount))
        if amount <= 0:
            return []
        if target is not None and not (0 <= target < len(self.left)
                                       and self.left[target] > 0):
            target = None
        if not spill:
            i = self.current_model() if target is None else target
            if i is None:
                self.leftover += amount
                self.steps.append((None, 0, 0))
                return []
            applied = min(amount, self.left[i])
            self.left[i] -= applied
            self.wasted += amount - applied
            self.steps.append((i, applied, amount - applied))
            return [(i, applied)]
        hits, pool = [], amount
        while pool > 0:
            i = self.mortal_model() if target is None else target
            target = None
            if i is None:
                self.leftover += pool
                break
            take = min(pool, self.left[i])
            self.left[i] -= take
            pool -= take
            self.steps.append((i, take, 0))
            hits.append((i, take))
        return hits

    # ---------- reading the outcome ----------

    def group_of(self, model: int):
        """Index of the group a model belongs to, or None (a model that
        was already destroyed when the sequence began has none)."""
        for gi, g in enumerate(self.groups):
            if model in g["members"]:
                return gi
        return None

    def result(self) -> list:
        """One row per model record passed in, whatever happened to it:
        {'key', 'label', 'before', 'after', 'max', 'damage', 'dead',
        'character', 'group'}. 'dead' marks a model this sequence
        destroyed, which is what the caller masks off the table."""
        out = []
        for i, m in enumerate(self.models):
            before, after = self.before[i], self.left[i]
            out.append({"key": m.get("key"), "label": m.get("label", "?"),
                        "before": before, "after": after,
                        "max": _int(m.get("max"), 1),
                        "damage": before - after,
                        "dead": after <= 0 and before > 0,
                        "character": bool(m.get("character")),
                        "group": self.group_of(i)})
        return out

    def standing(self) -> int:
        """Models of the unit still on the battlefield.

        BLAST and CLEAVE count them, and the count is taken again at
        every weapon activation rather than once for the whole attack,
        so a weapon firing into a squad the previous one has thinned
        gets fewer bonus attacks. Ruled that way deliberately: it makes
        firing the BLAST weapons FIRST worth something against a big
        unit, which is how the table plays. The rules leave a crack
        here -- 05.04.04 defers the removal of a destroyed model until
        the attacking unit has resolved all its attacks WHEN a rule is
        triggered by that model's destruction -- so a strict reading
        would freeze the count in that case. It is not modelled.
        """
        return sum(1 for n in self.left if n > 0)

    def snapshot(self) -> dict:
        """Everything this state has that can change, copied out. Undo
        of a whole activation restores it: the dice are NOT part of it,
        so re-firing re-rolls, which is what keeps an undo from being a
        way to shop for a better result."""
        return {"left": list(self.left), "wasted": self.wasted,
                "leftover": self.leftover, "steps": list(self.steps),
                "order": list(self.order), "precision": self.precision,
                "members": [list(g["members"]) for g in self.groups]}

    def restore(self, snap: dict):
        """Put back what snapshot() took out."""
        self.left = list(snap["left"])
        self.wasted = snap["wasted"]
        self.leftover = snap["leftover"]
        self.steps = list(snap["steps"])
        self.order = list(snap["order"])
        self.precision = snap["precision"]
        for g, members in zip(self.groups, snap["members"]):
            g["members"] = list(members)

    def killed(self) -> int:
        """Models this sequence destroyed."""
        return sum(1 for r in self.result() if r["dead"])

    def wiped(self) -> bool:
        """True when nothing of the unit is left standing."""
        return self.current_model() is None
