"""analyzer_core.suggested_firing_order: which weapon to fire first.

Additive to the analyzer: run_analysis is not involved, and the order
this returns never reaches a die - it is where the queue starts, and
the player moves it.

Two effects pull against each other and both have to be visible here:

  * WASTE. A big damage event throws its excess away on a model that
    was already wounded, so heavy weapons want to go first, into models
    at full wounds.
  * BLAST. [BLAST] and [CLEAVE] count the models still standing when
    they fire, so they want to go first too, into a unit still intact.

The second one is why the obvious implementation does not work, and
this file pins that down: handing kill_chain a fixed set of allocations
and asking it to compare orders CANNOT see the blast effect, because
every allocation was worked out at one model count.
"""
import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import attack_math as am
import kill_chain as kc
from unit_model import Weapon


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def gun(name, a="1", d="1", count=1):
    # No Save on the target side, S8 vs T4: every hit that lands wounds,
    # so the numbers below are about the ORDER and nothing else.
    return Weapon(name=name, wtype="Ranged", A=a, skill=3, S=8, AP=0,
                  D=d, count=count)


REF10 = {"T": 4, "Sv": None, "W": 1, "invuln": None, "fnp": None,
         "models": 10, "keywords": set()}
REF_W3 = {"T": 4, "Sv": None, "W": 3, "invuln": None, "fnp": None,
          "models": 6, "keywords": set()}


# --- 1. the degenerate cases ------------------------------------------

assert ac.suggested_firing_order([], REF10) == []
assert ac.suggested_firing_order([(gun("A"), mech())], REF10) == [0]
print("nothing to decide with fewer than two weapons")


# --- 2. heavy first, and the reason it is not the kill count ----------

# Five models of 3 wounds, a D4 weapon and a D1 one. The KILLS are the
# same whichever fires first, and that is not this case being unlucky:
# the chain's state is the unit's total remaining wounds and an event
# never spills past the model it lands on, so the count of models
# destroyed does not depend on the order. The waste does, and it shows
# up in the wounds actually taken off.
heavy = (gun("Heavy", a="3", d="4"), mech())
light = (gun("Light", a="6", d="1"), mech())
PAIR_HL = [light, heavy]
first = ac._order_score([1, 0], PAIR_HL, REF_W3, {}, 3, 5)
last = ac._order_score([0, 1], PAIR_HL, REF_W3, {}, 3, 5)
assert abs(first[0] - last[0]) < 1e-9, (first, last)   # kills: a tie
assert first[1] > last[1] + 0.5, (first, last)         # removed: not
order = ac.suggested_firing_order(PAIR_HL, REF_W3)
assert order == [1, 0], order
print("the heavy weapon goes first on the waste, which the kills cannot see")


# --- 3. blast first, which the chain alone cannot see -----------------

blast = (gun("Blast", a="1"), mech(blast=2))
killer = (gun("Killer", a="5"), mech())
PAIRS = [killer, blast]

# The trap, spelled out: analysed once at ten models, the two orders
# are indistinguishable to kill_chain - the blast weapon carries its
# ten-model attack count into a position where it would meet five.
fixed = [am.analyze_weapon(w, REF10, {}, m.copy(), alloc=True)["alloc"]
         for w, m in PAIRS]


def chain_mean(allocs):
    r = kc.resolve(allocs, 1, 10)
    return sum(k * p for k, p in enumerate(r["kills"]))


assert abs(chain_mean(fixed) - chain_mean(list(reversed(fixed)))) < 1e-9, \
    "kill_chain was expected to be blind to BLAST with fixed allocations"

# Scored properly - each weapon re-analysed at the count it would meet -
# the blast weapon has to go first, and here it is the KILLS that move.
order = ac.suggested_firing_order(PAIRS, REF10)
assert order == [1, 0], order
first = ac._order_score([1, 0], PAIRS, REF10, {}, 1, 10)
last = ac._order_score([0, 1], PAIRS, REF10, {}, 1, 10)
assert first[0] > last[0] + 0.5, (first, last)
print("BLAST is put first, and the scoring can actually tell the two apart")


# --- 4. no blast weapon: the blast candidate changes nothing ----------

plain = [(gun("A", a="2"), mech()), (gun("B", a="2"), mech())]
assert not ac._counts_models(plain[0][1])
assert ac._counts_models(blast[1]) and ac._counts_models(
    (gun("C"), mech(cleave=1))[1])
order = ac.suggested_firing_order(plain, REF10)
assert sorted(order) == [0, 1], order
print("CLEAVE counts like BLAST, and neither invents an order")


# --- 4b. the ranking contract, stated directly ------------------------

# Kills decide; wounds removed only break a tie. Asserting it on a
# scenario would need one where the two disagree in direction, and with
# the kill count invariant to order that scenario may not exist - so
# the contract is pinned where it is written.
assert ac._better((2.0, 5.0), (1.0, 9.0)) is True
assert ac._better((1.0, 9.0), (2.0, 5.0)) is False
assert ac._better((2.0, 9.0), (2.0, 5.0)) is True
assert ac._better((2.0, 5.0), (2.0, 5.0)) is False


# --- 4c. all three candidates are really offered ----------------------

# With three weapons the candidates stop coinciding, which is what makes
# this check bite: with two, blast-first is often just heavy-first
# reversed and dropping either changes nothing.
mid_blast = [(gun("Heavy", a="1", d="6"), mech()),
             (gun("Blast", a="2", d="2"), mech(blast=2)),
             (gun("Light", a="6", d="1"), mech())]
order = ac.suggested_firing_order(mid_blast, REF10)
assert order == [1, 0, 2], order        # the blast weapon leads
scores = {tuple(o): ac._order_score(list(o), mid_blast, REF10, {}, 1, 10)
          for o in ([0, 1, 2], [0, 1, 2][::-1], [1, 0, 2], [2, 1, 0])}
assert scores[(1, 0, 2)][0] > scores[(0, 1, 2)][0] + 1e-9, scores
assert scores[(1, 0, 2)][0] > scores[(2, 1, 0)][0] + 1e-9, scores

# The mirror case: a LIGHT blast weapon, where putting it first costs
# more waste than the extra attacks are worth, so heavy-first wins and
# is the only candidate that offers that order.
REF8 = {"T": 4, "Sv": None, "W": 3, "invuln": None, "fnp": None,
        "models": 8, "keywords": set()}
light_blast = [(gun("Mid", a="3", d="3"), mech()),
               (gun("Blast", a="4", d="1"), mech(blast=1)),
               (gun("Heavy", a="2", d="D6+1"), mech())]
assert ac.suggested_firing_order(light_blast, REF8) == [0, 2, 1]
by = {tuple(o): ac._order_score(list(o), light_blast, REF8, {}, 3, 8)
      for o in ([0, 2, 1], [1, 0, 2], [0, 1, 2], [1, 2, 0])}
assert ac._better(by[(0, 2, 1)], by[(1, 0, 2)])   # beats blast-first
assert ac._better(by[(0, 2, 1)], by[(0, 1, 2)])   # beats the order given
print("with three weapons the candidates differ, and the best one wins")


# --- 5. the result is always a permutation of the weapons -------------

many = [(gun("A", a="4"), mech()), (gun("B", a="1", d="6"), mech()),
        (gun("C", a="2"), mech(blast=1)), (gun("D", a="3", d="2"),
                                           mech())]
order = ac.suggested_firing_order(many, REF_W3)
assert sorted(order) == [0, 1, 2, 3], order
print("every weapon is offered exactly once")

print("firing order: all checks passed")
