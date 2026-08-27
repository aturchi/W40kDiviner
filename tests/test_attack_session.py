"""attack_session: one unit's attacks, weapon profile by weapon profile.

The state machine, not the dice: attack_resolve is already covered by
test_deferred_saves, so what has to be proved here is the sequencing.
A weapon fires into the unit the previous ones left behind, the groups
are built again at every activation, BLAST counts the models that are
standing NOW, and an undo takes the dice back with the wounds.

The dice are scripted wherever the outcome is asserted, so the checks
are arithmetic rather than statistics.
"""
import testpaths                      # sets up sys.path to the engine src/
import alloc_groups as ag
import attack_math as am
import attack_session as asx
from unit_model import Weapon


class Dice:
    """A d6 that returns a written sequence, then repeats its last."""

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
         character=False, fnp=None, invuln=None):
    return {"key": key, "label": key, "wounds": wounds, "max": cap,
            "sv": sv, "invuln": invuln, "fnp": fnp,
            "character": character, "entry": entry, "scarcity": scarcity}


def squad(n, cap=1, sv=None, entry=0, prefix="b"):
    return [body(f"{prefix}{i}", wounds=cap, cap=cap, sv=sv, entry=entry,
                 scarcity=n) for i in range(n)]


# A target with no Save characteristic at all: no save die is ever
# drawn, so every die in the script belongs to the hit or wound roll and
# the arithmetic below is exact.
UNIT_REF = {"T": 4, "keywords": set()}
CTX = {}


def pair(name, a="1", count=1, d="1", **mkw):
    w = Weapon(name=name, wtype="Ranged", A=a, skill=3, S=8, AP=0, D=d,
               count=count)
    return {"weapon": w, "mech": mech(**mkw)}


# --- 1. the queue: order in, order out, and it can be changed ---------

s = asx.AttackSession([pair("A"), pair("B"), pair("C")], UNIT_REF, CTX,
                      squad(3), Dice([6]))
assert s.queue() == [0, 1, 2]
assert s.move(2, -1) and s.queue() == [0, 2, 1]
assert not s.move(0, -1)               # off the end, refused
s2 = asx.AttackSession([pair("A"), pair("B")], UNIT_REF, CTX, squad(3),
                       Dice([6]), order=[1, 0])
assert s2.queue() == [1, 0]
print("the firing queue keeps the order given and can be reordered")


# --- 2. one activation: arm stops at the wounds, apply resolves them --

s = asx.AttackSession([pair("A", a="3")], UNIT_REF, CTX, squad(4),
                      Dice([6]))
armed = s.arm()
assert armed["to_save"] == 3 and armed["attacks"] == 3, armed
# Nothing has moved yet: arm() allocates nothing.
assert s.standing() == 4 and s.queue() == [0], s.standing()
rec = s.apply()
assert rec["killed"] == 3 and s.standing() == 1, rec
assert s.queue() == [] and s.finished()
print("arm() stops at the wounds scored, apply() takes them off")


# --- 3. a weapon fires into what the previous one left ----------------

# Two one-attack weapons into two-wound bodies: the first leaves a
# model wounded, and the second must find it that way.
s = asx.AttackSession([pair("A", d="2"), pair("B", d="1")], UNIT_REF,
                      CTX, squad(2, cap=2), Dice([6]))
s.fire()
assert s.standing() == 1, [m["wounds"] for m in s.models]
s.fire()
assert s.standing() == 1 and s.models[1]["wounds"] == 1
print("each weapon fires into the unit the previous one left behind")


# --- 4. the groups are built again at every activation ----------------

# Three bodies of 2 wounds. The first weapon wounds one of them without
# killing it; at the NEXT activation that model's group is the one the
# rules put first, which is only visible if the groups were rebuilt.
mixed = squad(2, cap=2, entry=0, prefix="hard") \
    + squad(2, cap=2, sv=None, entry=1, prefix="soft")
for m in mixed[2:]:
    m["max"] = 3                       # a different W: a second group
    m["wounds"] = 3
s = asx.AttackSession([pair("A"), pair("B")], UNIT_REF, CTX, mixed,
                      Dice([6]))
before = ag.default_order(s.groups(), s.models)
s.fire()                               # one wound onto the first group
after = ag.default_order(s.groups(), s.models)
assert s.models[0]["wounds"] == 1
assert ag.order_problem(s.groups(), after, s.models) is None
# The wounded group has to be first now; before the shot both groups
# were untouched and the order was the size heuristic's.
assert s.groups()[after[0]]["members"][0] == 0, (before, after)
# And the allocation arm() hands the player is built from the wounds as
# they are NOW, not kept from the first activation.
s.arm()
# A FRESH allocation: it starts from the wounds as they are now and has
# resolved nothing yet. Carrying the previous activation's object over
# would leave the same left[] but a used history and a stale start.
assert s.alloc.before[0] == 1, s.alloc.before
assert s.alloc.left[0] == 1 and s.alloc.steps == [], s.alloc.steps
order = s.alloc.order
assert s.alloc.groups[order[0]]["members"][0] == 0, order
s.discard()
print("the allocation groups are rebuilt from the wounds at every shot")


# --- 5. BLAST counts the models standing NOW --------------------------

# A blast weapon gets one extra attack per five models in the target.
# Ten models -> +2, and after five have gone -> +1. The count is taken
# at the activation, which is the whole point of firing blast early.
killer = pair("Killer", a="5")
blast = pair("Blast", a="1", blast=1)
s = asx.AttackSession([blast, killer], UNIT_REF, CTX, squad(10),
                      Dice([6]))
assert s.arm(0)["attacks"] == 3, "10 models: 1 + 2 blast attacks"
s.discard()
s.fire(1)                              # five models removed
assert s.standing() == 5
assert s.arm(0)["attacks"] == 2, "5 models: 1 + 1 blast attack"
print("BLAST is recounted at every activation, not fixed at the start")


# --- 6. undo takes the dice back with the wounds ----------------------

s = asx.AttackSession([pair("A", a="2"), pair("B"), pair("C")],
                      UNIT_REF, CTX, squad(4), Dice([6]))
s.fire()
assert s.standing() == 2 and s.queue() == [1, 2]
rec = s.undo()
assert rec["index"] == 0
assert s.standing() == 4, [m["wounds"] for m in s.models]
assert s.queue() == [0, 1, 2], s.queue()   # at the head, not the tail
assert not s.records()
# An armed activation blocks undo even when there IS something to undo,
# and blocks reordering the queue: those dice were rolled for the weapon
# at the head of it.
s.fire()                               # history is no longer empty
assert s.can_undo()
s.arm()
assert len(s.queue()) > 1, s.queue()   # a move that would be legal
assert not s.can_undo(), "undo must not reach past an armed activation"
assert not s.move(0, 1), "the queue must not move while a weapon is armed"
s.discard()
assert s.can_undo() and s.move(0, 1) and s.queue() == [2, 1]
print("undo restores the wounds and puts the weapon back in the queue")


# --- 7. fire_all stops where the player has to decide -----------------

PRECISE = Weapon(name="Sniper", wtype="Ranged", A="1", skill=3, S=8,
                 AP=0, D="1", count=1, keywords=["PRECISION"])
led = squad(2) + [body("cpt", wounds=3, cap=3, character=True, entry=1)]
s = asx.AttackSession([pair("A"), {"weapon": PRECISE, "mech": mech()},
                       pair("C")], UNIT_REF, CTX, led, Dice([6]))
done = s.fire_all()
assert [r["index"] for r in done] == [0], done
assert s.queue() == [1, 2], s.queue()
assert s.needs_choice() is True
# Told to decide nothing, it runs the lot with the default order.
done = s.fire_all(stop_on_choice=False)
assert [r["index"] for r in done] == [1, 2], done
assert s.finished()

# An allocation order the rules leave open stops it too: two untouched
# non-CHARACTER groups sit in the same block, so which goes first is the
# player's call and the program must not make it.
free = squad(2, cap=2, entry=0, prefix="hard")
free += [body("soft0", wounds=3, cap=3, entry=1, scarcity=1)]
s = asx.AttackSession([pair("A"), pair("B")], UNIT_REF, CTX, free,
                      Dice([6]))
assert not ag.order_is_forced(s.groups(), s.models)
assert s.needs_choice() is True
assert s.fire_all() == [], "fire_all must stop before an open order"
assert s.queue() == [0, 1]

# With no CHARACTER present a PRECISION weapon asks nothing, and a
# forced order does not stop the run either.
s = asx.AttackSession([{"weapon": PRECISE, "mech": mech()}], UNIT_REF,
                      CTX, squad(3), Dice([6]))
assert s.needs_choice() is False
assert len(s.fire_all()) == 1
print("fire_all runs the queue and stops only at a real decision")


# --- 8. PRECISION sends the attacks to the chosen CHARACTER -----------

s = asx.AttackSession([{"weapon": PRECISE, "mech": mech()}], UNIT_REF,
                      CTX, led, Dice([6]))
s.arm()
s.alloc.set_precision(s.alloc.character_groups()[0])
s.apply()
assert s.models[2]["wounds"] == 2, [m["wounds"] for m in s.models]
assert s.standing() == 3                # no bodyguard model was touched
print("PRECISION reaches the CHARACTER while the bodyguard stands")


# --- 9. hazardous is accumulated, never applied here ------------------

haz = pair("Plasma", a="1", count=2, hazardous=True)
s = asx.AttackSession([haz], UNIT_REF, CTX, squad(3), Dice([1]))
s.fire()
assert s.self_damage() == 2, s.self_damage()   # two copies, both roll 1
s.undo()
assert s.self_damage() == 0                    # undone with the rest
print("hazardous self-damage is carried to the end, and undone with it")


# --- 10. labels carry what the player has to notice -------------------

assert asx.is_precision(PRECISE) and not asx.is_precision(pair("A")["weapon"])
assert "PRECISION" in asx.weapon_label(PRECISE)
assert "HAZARDOUS" in asx.weapon_label(haz["weapon"], haz["mech"])
assert asx.weapon_label(pair("A", count=5)["weapon"]) == "A x5"
print("the queue label names the keywords that change the flow")


# --- 11. the mechanics handed in are not written on -------------------

# The session copies them per activation. Nothing in attack_resolve is
# known to write on a WeaponMechanics - a sweep of 17 configurations x
# both modes x 6 seeds changed no field - so this pins the contract
# rather than a bug, and will fail the day the resolver starts caching
# something on it.
import copy as _copy
entry = pair("A", a="2")
s = asx.AttackSession([entry], UNIT_REF, CTX, squad(4), Dice([6]))
snap = {k: _copy.deepcopy(v) for k, v in vars(entry["mech"]).items()}
s.fire()
assert all(v == snap[k] for k, v in vars(entry["mech"]).items()), \
    [k for k, v in vars(entry["mech"]).items() if v != snap[k]]
print("the mechanics passed in come back untouched")

print("attack_session: all checks passed")
