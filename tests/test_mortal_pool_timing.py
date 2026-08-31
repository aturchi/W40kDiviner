"""WHEN the spilling mortal-wound pool is spent, and why it matters.

11th-ed. rule under test (4.3): mortal wounds are resolved as a batch
at the end of each GROUP OF IDENTICAL ATTACKS - one weapon profile
against one target - and not at the very end of the unit's shooting,
which is where the 10th edition put them.

Spending them is a plain subtraction, since a spilling mortal wound
passes from a destroyed model to the next and wastes nothing. What the
timing changes is the model the NEXT weapon's damage events land on,
and so how much of that damage is wasted: a front model already brought
down to 1 wound by the mortals soaks a 3-damage event for 1.

The dice resolver has always done this - attack_resolve.resolve_saves()
spends its spill_pool before it returns - so this file is also a
consistency check between the two engines' sequencing.

The expected numbers are produced by a model-by-model bookkeeping
written from the rules below (walk_models), independently of the chain's
(total wounds, pool) state representation, and a handful of them are
also worked out in the comments.
"""
import testpaths                      # sets up sys.path to the engine src/
import kill_chain as kc

TOL = 1e-9


def close(a, b, what):
    assert abs(a - b) < TOL, f"{what}: engine={a!r} expected={b!r}"


def mean(pmf):
    return sum(i * p for i, p in enumerate(pmf))


# --- an independent oracle -------------------------------------------

def walk_models(weapons, w, n):
    """(kills, removed) by explicit model bookkeeping.

    'weapons' is [(events, pool)] where 'events' is a list of damage
    values allocated one at a time and 'pool' is the spilling mortal
    wounds that weapon produced. The rules, written out:

      * a damage event lands on the FIRST model still standing and is
        capped by the wounds it has left - the excess is wasted;
      * the pool is spent at the END of the weapon that built it, one
        point at a time, moving on to the next model as each dies -
        nothing is wasted.

    Nothing here knows about the chain's state representation, which is
    the point: it is a second opinion, not a re-derivation.
    """
    left = [w] * n

    def front():
        for i, v in enumerate(left):
            if v > 0:
                return i
        return None

    for events, pool in weapons:
        for d in events:
            i = front()
            if i is None:
                break
            left[i] = max(0, left[i] - d)      # the excess is wasted
        for _ in range(pool):
            i = front()
            if i is None:
                break
            left[i] -= 1                       # spills, wastes nothing
    return sum(1 for v in left if v <= 0), w * n - sum(left)


# --- the same scenarios as chain allocations -------------------------

def mortal(pool, attacks=1):
    """A weapon whose every attack adds 'pool' SPILLING mortal wounds."""
    ap = [0.0] * (attacks + 1)
    ap[attacks] = 1.0
    return {"per_attack": {(0, 0, pool): 1.0}, "joint": True,
            "event_damage": [0.0, 1.0], "event_damage_dev": [0.0, 1.0],
            "attacks_pmf": ap, "single": None}


def plain(dmg, attacks):
    """A weapon of 'attacks' attacks, each one event of 'dmg' damage."""
    ev = [0.0] * (dmg + 1)
    ev[dmg] = 1.0
    ap = [0.0] * (attacks + 1)
    ap[attacks] = 1.0
    return {"per_attack": [0.0, 1.0], "joint": False, "event_damage": ev,
            "attacks_pmf": ap, "single": None}


# (name, W, models, [(chain alloc, (events, pool) for the oracle)])
CASES = [
    # 4 models of 3 wounds. One mortal wound first, then two events of
    # 3: the mortal leaves the front model on 2, so the first event
    # kills it wasting 1, and the second kills a fresh model exactly.
    # 2 dead, 6 wounds off. Spending the pool LAST instead would let
    # both events land on full models and report 7 wounds off.
    ("1 MW then 2 events of 3", 3, 4,
     [(mortal(1), ([], 1)), (plain(3, 2), ([3, 3], 0))]),
    ("2 MW then 3 events of 2", 3, 4,
     [(mortal(2), ([], 2)), (plain(2, 3), ([2, 2, 2], 0))]),
    ("3 MW then 3 events of 3", 4, 3,
     [(mortal(3), ([], 3)), (plain(3, 3), ([3, 3, 3], 0))]),
    ("1 MW then 4 events of 2", 2, 5,
     [(mortal(1), ([], 1)), (plain(2, 4), ([2, 2, 2, 2], 0))]),
    # The mortal weapon LAST: there is nothing left to interleave with,
    # so the timing cannot matter and the two readings agree. Kept so
    # the checks above cannot pass by flushing something else.
    ("4 events of 2 then 4 MW", 3, 6,
     [(plain(2, 4), ([2, 2, 2, 2], 0)), (mortal(2, 2), ([], 4))]),
    # ...and in the MIDDLE, where the correction goes the OTHER way:
    # the mortals leave the front model on 2, so the next 2-damage
    # event fits exactly instead of wasting a point.
    ("2 events, 4 MW, 2 events", 3, 6,
     [(plain(2, 2), ([2, 2], 0)), (mortal(2, 2), ([], 4)),
      (plain(2, 2), ([2, 2], 0))]),
]

for name, w, n, pairs in CASES:
    res = kc.resolve([a for a, _o in pairs], w, n)
    want_k, want_r = walk_models([o for _a, o in pairs], w, n)
    close(mean(res["kills"]), want_k, f"{name}: kills")
    close(mean(res["removed"]), want_r, f"{name}: wounds removed")
print("the pool is spent at the end of the weapon that built it")

# The two hand-worked figures of the first case, spelled out, so the
# oracle itself is anchored to something and not just to its own code.
first = kc.resolve([mortal(1), plain(3, 2)], 3, 4)
close(mean(first["kills"]), 2.0, "1 MW then 2 events of 3: kills")
close(mean(first["removed"]), 6.0, "1 MW then 2 events of 3: removed")
# Spending the pool at the readout instead would give 7 - the figure
# this file exists to keep out.
assert mean(first["removed"]) != 7.0

# The middle case, likewise: 11 wounds off, not the 10 of the old
# reading. The correction is NOT one-directional.
mid = kc.resolve([plain(2, 2), mortal(2, 2), plain(2, 2)], 3, 6)
close(mean(mid["removed"]), 11.0, "MW in the middle: removed")
print("the correction runs both ways, and the hand figures agree")


# --- what must NOT change --------------------------------------------
# 'spent' counts the weapons fired while the unit was still standing,
# and it already read the pool at every intermediate step: a unit
# finished off by the mortals of the second weapon costs two weapons,
# not three, whichever reading is used.
over = [mortal(3, 2), plain(3, 3), plain(3, 3)]
res = kc.resolve(over, 3, 2)
close(res["p_wipe"], 1.0, "6 mortal wounds wipe two 3-wound models")
close(res["spent"], 1.0, "and they cost exactly one weapon")

# A single weapon has nothing after it, so its own chain is untouched:
# this is the path run_analysis uses for the per-weapon rows.
solo = kc.resolve([mortal(2, 2)], 3, 4)
close(mean(solo["removed"]), 4.0, "one weapon alone: removed")
close(mean(solo["kills"]), 1.0, "one weapon alone: kills")

# An empty pool must survive the flush untouched, or every ordinary
# chain would move.
pair = [plain(2, 3), plain(3, 2)]
close(mean(kc.resolve(pair, 3, 4)["removed"]),
      walk_models([([2, 2, 2], 0), ([3, 3], 0)], 3, 4)[1],
      "no mortal wounds anywhere: unchanged")
print("spent, the single-weapon chain and pool-free chains are untouched")


# --- where the KILL count moves, and not just the wounds -------------
# One weapon that produces BOTH an ordinary event and a spilling mortal
# wound, into 3 models of 2 wounds:
#
#   4.3   the event takes model 1 to 1 wound, the mortal finishes it;
#         the next weapon's 2-damage event then kills model 2 outright.
#         2 dead, 4 wounds off.
#   old   the event takes model 1 to 1 wound and the mortal is HELD; the
#         next weapon's 2-damage event lands on that same 1-wound model
#         and wastes a point; the mortal is spent last, on model 2.
#         1 dead, 3 wounds off.
#
# A whole model, on a chain of two weapons and three attacks.
both = {"per_attack": {(1, 0, 1): 1.0}, "joint": True,
        "event_damage": [0.0, 1.0], "event_damage_dev": [0.0, 1.0],
        "attacks_pmf": [0.0, 1.0], "single": None}
mixed = kc.resolve([both, plain(2, 1)], 2, 3)
want_k, want_r = walk_models([([1], 1), ([2], 0)], 2, 3)
close(mean(mixed["kills"]), want_k, "event + mortal, then an event: kills")
close(mean(mixed["removed"]), want_r, "...: wounds removed")
close(mean(mixed["kills"]), 2.0, "the hand figure: 2 models dead")
close(mean(mixed["removed"]), 4.0, "the hand figure: 4 wounds off")


def resolve_no_flush(allocs, w, n):
    """The OLD reading, rebuilt here from the chain's own primitives:
    the pool is carried across every weapon and only _read_state, at
    the very end, ever subtracts it. Kept so the checks above are
    anchored to a number that is actually different, rather than to
    themselves."""
    tmax = w * n
    state = {(tmax, 0): 1.0}
    for alloc in allocs:
        state = kc.apply_weapon(state, alloc, w, tmax)
    return kc._read_state(state, w, n, tmax)


old_kills, old_removed = resolve_no_flush([both, plain(2, 1)], 2, 3)
close(mean(old_kills), 1.0, "the old reading killed one model fewer")
close(mean(old_removed), 3.0, "...and took one wound fewer off")
print("a weapon that spills AND damages moves the kill count by a model")


# --- the pool never outruns the wounds still standing -----------------
# resolve() flushes after every weapon, so the pool reaching the readout
# is always zero and the subtraction there looks like dead code. It is
# not: _read_state is the general reader (resolve_no_flush above is one
# caller, and the intermediate 'spent' reads are another).
#
# It used to CLAMP that subtraction at zero, because a weapon that
# damages AND spills could put the two on the wrong side of each other:
# the ordinary events bring the remaining wounds down while the pool
# climbs. _attack_op now caps the pool at the wounds still standing
# instead, which is exact - a pool bigger than what is left spends the
# same as one exactly as big - and halves the state the joint chain
# carries. The clamp is gone and an assertion stands in its place, so a
# cap that ever stopped holding would be an error and not a plausible
# figure.
big = {"per_attack": {(1, 0, 3): 1.0}, "joint": True,
       "event_damage": [0.0, 0.0, 1.0], "event_damage_dev": [0.0, 0.0, 1.0],
       "attacks_pmf": [0.0, 0.0, 1.0], "single": None}
k, r = resolve_no_flush([big], 2, 3)
close(mean(k), 3.0, "an over-killing pool wipes the unit")
close(mean(r), 6.0, "and never removes more wounds than the unit had")

# The invariant itself, on the state that used to break it: this is the
# weapon that produced pool > T before the cap, so if the assertion is
# ever going to be needed it is needed here.
tmax = 2 * 3
state = {(tmax, 0): 1.0}
for _ in range(2):
    state = kc.apply_weapon(state, big, 2, tmax)
assert state, "the probe state is empty - the invariant check proves nothing"
for (t, pool), p in state.items():
    assert pool <= t, f"pool {pool} past the {t} wounds still standing"

# ...and the assertion bites: a state built by hand past the cap must be
# refused, not clamped. An invariant nothing can violate is one nothing
# can check.
try:
    kc._read_state({(2, 5): 1.0}, 2, 3, tmax)
except AssertionError:
    pass
else:
    raise AssertionError("_read_state accepted a pool past the wounds left")
try:
    kc._spend_pool({(2, 5): 1.0})
except AssertionError:
    pass
else:
    raise AssertionError("_spend_pool accepted a pool past the wounds left")
print("the pool never outruns the wounds still standing")


# --- a weapon that does nothing was still fired ------------------------
# 'spent' counts the weapons pointed at this target, not the ones that
# did something: an allocation the caller could not build (a weapon that
# cannot hurt the target at all) is skipped by the chain but still cost
# the player a weapon, and the firing order is chosen on that count.
close(kc.resolve([{}, plain(2, 1)], 2, 3)["spent"], 2.0,
      "an empty allocation is still a weapon spent")
close(kc.resolve([], 2, 3)["spent"], 0.0, "no weapons, nothing spent")
print("'spent' counts every weapon pointed at the target")

print("OK  test_mortal_pool_timing")
