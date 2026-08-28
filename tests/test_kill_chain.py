"""Models destroyed (src/kill_chain.py).

The previous version of this test validated the chain against a
simulator that drew from the SAME per-attack law the chain consumed.
Both shared the assumption that an attack's damage could be aggregated
into one number before being capped - and both were wrong for weapons
whose single attack produces several damaging hits. A check that
replicates the hypothesis under test proves nothing.

So the reference here is attack_resolve, the dice engine: it rolls the
whole sequence and emits one event per damaging attack, sharing no code
with the chain. The events are then allocated by a plain loop written
below. Four checks:

1. HAND CASES: allocation arithmetic worked out on paper.
2. EVENTS vs SUM: many small hits waste less than one big one.
3. DICE: the chain against attack_resolve, with the statistical bounds
   the rest of the parity suite uses.
4. MORTAL WOUNDS: the pool is spent at the END of the activation and
   spills, unlike ordinary damage.
"""
import random

import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
import attack_resolve as ar
import dist_stats as ds
import kill_chain as kc
import mc_support as mc
from unit_model import Weapon


def close(a, b, eps=1e-9):
    assert abs(a - b) < eps, f"{a} != {b}"


def hand(events, damage, n_attacks=1):
    """A hand-made allocation law: a fixed number of damage events per
    attack, each of a fixed size."""
    return {"per_attack": am.delta(events), "joint": False,
            "event_damage": am.delta(damage),
            "attacks_pmf": am.delta(n_attacks), "single": None}


# ---- 1. hand cases -----------------------------------------------------

# W=3, 2 models, three damage events of 2.
# Model A: 2 -> 1 left; 2 -> destroyed, 1 damage WASTED; model B: 2.
# One model dies. Dividing the damage (6/3) would have claimed two.
assert kc.kills_pmf([hand(3, 2)], 3, 2) == [0.0, 1.0, 0.0]

# Overkill cannot destroy more models than the unit owns.
assert kc.kills_pmf([hand(20, 9)], 3, 2) == [0.0, 0.0, 1.0]

# Chaining: two weapons of one event each land on the same models as
# one weapon making two events.
assert kc.kills_pmf([hand(1, 2)] * 2, 3, 2) == kc.kills_pmf([hand(2, 2)],
                                                            3, 2)

# State bookkeeping used by the chain.
assert kc.front_wounds(6, 3) == 3 and kc.front_wounds(4, 3) == 1
assert kc.front_wounds(0, 3) == 0
assert kc.kills_from_total(6, 3, 2) == 0
assert kc.kills_from_total(3, 3, 2) == 1
assert kc.kills_from_total(0, 3, 2) == 2


# ---- 2. the same damage, delivered differently -------------------------
# Ten damage into three models of W3: five hits of 2 destroy two models,
# a single hit of 10 destroys one and wastes seven. Aggregating an
# attack's damage before capping it - the bug this rewrite fixes - would
# have made the two identical.
assert kc.kills_pmf([hand(5, 2)], 3, 3) == [0.0, 0.0, 1.0, 0.0]
assert kc.kills_pmf([hand(1, 10)], 3, 3) == [0.0, 1.0, 0.0, 0.0]


# ---- 3. against the dice engine ---------------------------------------

def allocate(events, w, n, want="kills"):
    """Allocate one activation's events the way the rules say: damage
    one model at a time, capped by the wounds left; mortal wounds that
    SPILL pooled to the end and spent one point at a time. Devastating
    Wounds are mortal wounds that do not spill, so the resolver marks
    them and they are allocated like ordinary damage."""
    wounds, pool = [w] * n, 0
    for e in events:
        if e["kind"] == "mortal" and e.get("spills", True):
            pool += e["amount"]
            continue
        i = next((j for j, x in enumerate(wounds) if x > 0), None)
        if i is None:
            break
        wounds[i] -= min(e["amount"], wounds[i])
    for _ in range(pool):
        i = next((j for j, x in enumerate(wounds) if x > 0), None)
        if i is None:
            break
        wounds[i] -= 1
    if want == "removed":
        return sum(w - max(0, x) for x in wounds)
    return sum(1 for x in wounds if x <= 0)


def dice_kills(weapon, ref, ctx, mech, w, n, want="kills", trials=None,
               seed=None):
    """Roll the weapon and allocate, 'trials' times."""
    trials = mc.TRIALS if trials is None else trials
    rng = random.Random(mc.SEED if seed is None else seed)
    out = []
    for _ in range(trials):
        res = ar.resolve_weapon(weapon, ref, ctx, mc.clone_mech(mech), rng)
        out.append(allocate(res["events"], w, n, want))
    return out


def check(name, weapon, ref, mech, ctx=None):
    """Both outputs of the chain against the dice: the models destroyed
    and the wounds actually taken off the unit."""
    ctx = ctx or {}
    exact = am.analyze_weapon(weapon, ref, ctx, mc.clone_mech(mech),
                              alloc=True)
    res = kc.resolve([exact["alloc"]], ref["W"], ref["models"])
    close(sum(res["kills"]), 1.0, 1e-9)
    close(sum(res["removed"]), 1.0, 1e-9)
    out = []
    for want, pmf in (("kills", res["kills"]), ("removed", res["removed"])):
        samples = dice_kills(weapon, ref, ctx, mech, ref["W"],
                             ref["models"], want)
        ok, msg = mc.parity_report(f"{want[:7]:7s} {name}", pmf, samples)
        print("  " + msg)
        out.append((ok, msg))
    return (all(ok for ok, _m in out),
            "; ".join(m for ok, m in out if not ok))


TARGET = {"T": 4, "Sv": 4, "W": 3, "invuln": None, "fnp": None,
          "models": 6, "keywords": set()}
WEAPON = Weapon(name="w", wtype="Ranged", A="D3+2", skill=3, S=6, AP=-1,
                D="D3", count=3)
failures = []
CASES = (
    ([], "plain"),
    (["DEVASTATING WOUNDS"], "devastating"),
    # The case the old aggregation got wrong: one attack, several hits.
    (["SUSTAINED HITS 2"], "sustained 2"),
    (["SUSTAINED HITS 2", "LETHAL HITS"], "sustained+lethal"),
    (["TWIN-LINKED", "DEVASTATING WOUNDS"], "twin+devastating"),
)
for kws, name in CASES:
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(list(kws), m)
    ok, msg = check(f"kills {name:18s}", WEAPON, TARGET, m)
    if not ok:
        failures.append(msg)

# A big-damage weapon into small models: most of every hit is wasted,
# which is where a damage-based estimate goes furthest wrong.
BIG = Weapon(name="big", wtype="Ranged", A="2", skill=3, S=10, AP=-3,
             D="6", count=2)
ok, msg = check("kills big damage      ", BIG, TARGET, am.WeaponMechanics())
if not ok:
    failures.append(msg)

# Two weapons chained: the second finds the models the first left hurt,
# so the pair kills MORE than twice what one alone kills on a fresh
# unit. Analysing weapons in isolation and adding up would miss it.
a1 = am.analyze_weapon(WEAPON, TARGET, {}, am.WeaponMechanics(),
                       alloc=True)["alloc"]
together = kc.kills_pmf([a1, a1], TARGET["W"], TARGET["models"])
apart = ds.stats(kc.kills_pmf([a1], TARGET["W"], TARGET["models"]))["mean"]
assert ds.stats(together)["mean"] > 2 * apart, (ds.stats(together)["mean"],
                                                2 * apart)

# Flooring the damage by W overstates the kills: that error is exactly
# the wasted damage this module exists to account for.
res = am.analyze_weapon(WEAPON, TARGET, {}, am.WeaponMechanics(),
                        alloc=True)
naive = res["damage_net"]["mean"] / TARGET["W"]
assert ds.stats(kc.kills_pmf([res["alloc"]], TARGET["W"],
                             TARGET["models"]))["mean"] < naive


# ---- 4. mortal wounds: pooled, spent last, spilling --------------------

# Devastating Wounds ARE mortal wounds: an invulnerable save or a Feel
# No Pain granted "against mortal wounds" thins them, which is what
# gives their events a different damage law from the ordinary ones and
# forces the joint path even though nothing spills.
dev = am.WeaponMechanics()
am.parse_weapon_keywords(["DEVASTATING WOUNDS"], dev)
am.parse_effect_strings(["IF MW_ONLY: SETFNP 4"], "Ranged", dev, WEAPON)
assert dev.fnp_mw == 4
res = am.analyze_weapon(WEAPON, TARGET, {}, dev.copy(), alloc=True)
assert res["alloc"]["joint"], "different event laws must force the joint path"
ok, msg = check("kills devastating+mwfnp", WEAPON, TARGET, dev)
if not ok:
    failures.append(msg)
# ...and without such an ability the two laws coincide, so the cheap
# path is taken.
plain_dev = am.WeaponMechanics()
am.parse_weapon_keywords(["DEVASTATING WOUNDS"], plain_dev)
assert not am.analyze_weapon(WEAPON, TARGET, {}, plain_dev,
                             alloc=True)["alloc"]["joint"]

MW = ["IF CRIT_WOUND: MORTAL_WOUNDS 1 END_SEQUENCE"]
m = am.WeaponMechanics()
am.parse_effect_strings(MW, "Ranged", m, WEAPON)
assert m.crit_mw is not None, "the mortal-wound ability did not parse"
res = am.analyze_weapon(WEAPON, TARGET, {}, m.copy(), alloc=True)
assert res["alloc"]["joint"], "a real mortal wound must use the joint law"
ok, msg = check("kills crit mortal     ", WEAPON, TARGET, m)
if not ok:
    failures.append(msg)

# Spilling is what separates the pool from ordinary damage: six mortal
# points wipe two W3 models, six ordinary points delivered one at a time
# do too, but delivered as three hits of 2 they only kill one.
pool = {"per_attack": {(0, 0, 6): 1.0}, "joint": True,
        "event_damage": am.delta(1), "attacks_pmf": am.delta(1),
        "single": None}
assert kc.kills_pmf([pool], 3, 2) == [0.0, 0.0, 1.0]
assert kc.kills_pmf([hand(3, 2)], 3, 2) == [0.0, 1.0, 0.0]

# The pool is spent AFTER the ordinary damage, so a mortal wound never
# wastes itself on a model ordinary damage was going to kill anyway.
mixed = {"per_attack": {(1, 0, 1): 1.0}, "joint": True,
         "event_damage": am.delta(2), "attacks_pmf": am.delta(2),
         "single": None}
# Two attacks, each 2 ordinary damage + 1 mortal, into 2 models of W3:
# ordinary first -> A takes 2, then 2 (destroyed, 1 wasted): T = 3.
# Pool of 2 then takes B to 1 wound. One model dies.
assert kc.kills_pmf([mixed], 3, 2) == [0.0, 1.0, 0.0]

# ---- 5. wounds inflicted vs the old 'net damage' estimate -------------
# Capping every event at W (what damage_net does) cannot see that the
# unit runs out of models, nor that a model dies with wounds to spare,
# so it never UNDERstates what was really taken off the unit.
SMALL = {"T": 4, "Sv": 5, "W": 1, "invuln": None, "fnp": None,
         "models": 4, "keywords": set()}
res = am.analyze_weapon(WEAPON, SMALL, {}, am.WeaponMechanics(), alloc=True)
chain = kc.resolve([res["alloc"]], SMALL["W"], SMALL["models"])
assert ds.stats(chain["removed"])["mean"] <= res["damage_net"]["mean"] + 1e-9
assert ds.stats(chain["removed"])["mean"] < res["damage_net"]["mean"]
# It can never exceed the wounds the unit owns, either.
assert len(chain["removed"]) == SMALL["W"] * SMALL["models"] + 1
# ... and wounds inflicted and models killed agree, one wound per model.
close(ds.stats(chain["removed"])["mean"], ds.stats(chain["kills"])["mean"])


# ---- 6. firing order ---------------------------------------------------
# Order matters because a big event wastes its excess on a model that a
# smaller one already wounded. best_order only tries a few candidates,
# so all that is asserted is that it never returns something worse than
# the order it was given.
ORDER_REF = {"T": 4, "Sv": 4, "W": 3, "invuln": None, "fnp": None,
             "models": 5, "keywords": set()}
heavy = Weapon(name="heavy", wtype="Ranged", A="3", skill=3, S=8, AP=-2,
               D="4", count=1)
light = Weapon(name="light", wtype="Ranged", A="6", skill=3, S=5, AP=-1,
               D="1", count=1)
pair = [am.analyze_weapon(x, ORDER_REF, {}, am.WeaponMechanics(),
                          alloc=True)["alloc"] for x in (light, heavy)]
given = ds.stats(kc.resolve(pair, 3, 5)["kills"])["mean"]
order, best, given_res = kc.best_order(pair, 3, 5)
close(ds.stats(given_res["kills"])["mean"], given)
assert sorted(order) == [0, 1], order
assert ds.stats(best["kills"])["mean"] >= given - 1e-12
# Firing the heavy weapon first wastes less: same kills here, but the
# wounds actually inflicted differ, and that IS order-dependent.
first_light = ds.stats(kc.resolve(pair, 3, 5)["removed"])["mean"]
first_heavy = ds.stats(kc.resolve(pair[::-1], 3, 5)["removed"])["mean"]
assert first_heavy > first_light, (first_heavy, first_light)

# The check above is satisfied by a best_order that never looks at a
# candidate at all, which is what it did until this triple was added:
# EVERY mutation of the search survived it. Three weapons whose table
# order is not the best one, so the function has to actually find the
# better one and say so.
TOUGH = {"T": 5, "Sv": 3, "W": 3, "invuln": 4, "fnp": None, "models": 5,
         "keywords": set()}


def order_law(name, A, S, AP, D, count):
    w = Weapon(name=name, wtype="Ranged", A=A, skill=3, S=S, AP=AP, D=D,
               count=count)
    return am.analyze_weapon(w, TOUGH, {}, am.WeaponMechanics(),
                             alloc=True)["alloc"]


# frag first is the roster order and the worst of the three; krak has
# twice the event damage and belongs at the front.
triple = [order_law("frag", "D6", 4, 0, "1", 2),
          order_law("krak", "1", 9, -2, "D6", 2),
          order_law("bolt", "2", 4, -1, "1", 5)]
t_order, t_best, t_given = kc.best_order(triple, 3, 5)
assert t_order == [1, 0, 2], t_order
assert sorted(t_order) == [0, 1, 2]
k_given = ds.stats(t_given["kills"])["mean"]
k_best = ds.stats(t_best["kills"])["mean"]
assert k_best > k_given + 1e-6, (k_best, k_given)
# 'given' must be the order the caller passed, not some rearrangement of
# it: the gain the analyser prints is the difference of the two. Kills
# alone will not say so - the reverse of this triple kills exactly as
# many - so the wounds taken off are compared as well.
close(k_given, ds.stats(kc.resolve(triple, 3, 5)["kills"])["mean"])
close(ds.stats(t_given["removed"])["mean"],
      ds.stats(kc.resolve(triple, 3, 5)["removed"])["mean"])
close(t_given["spent"], kc.resolve(triple, 3, 5)["spent"])
# ... and the result returned must belong to the order returned.
close(k_best, ds.stats(kc.resolve([triple[i] for i in t_order], 3,
                                  5)["kills"])["mean"])
# The two candidates tie on kills and differ on the wounds taken off, so
# a search that returns "a candidate" rather than "the best candidate"
# lands on the other one.
rev = [triple[i] for i in reversed(t_order)]
close(ds.stats(kc.resolve(rev, 3, 5)["kills"])["mean"], k_best)
assert (ds.stats(t_best["removed"])["mean"]
        > ds.stats(kc.resolve(rev, 3, 5)["removed"])["mean"])


# ---- 6b. the criterion: weapons freed, not models killed -------------

# The two disagree, and this is a case where they do. Firing the melta
# first frees a weapon more often, and kills very slightly FEWER models
# doing it. The old criterion kept the table order for the sake of that
# fraction of a body; the new one takes the weapon, because the weapon
# can be pointed at the next unit and the body cannot.
HARD = {"T": 5, "Sv": 3, "W": 3, "invuln": 4, "fnp": None, "models": 5,
        "keywords": set()}


def hard_law(name, A, S, AP, D, count):
    w = Weapon(name=name, wtype="Ranged", A=A, skill=3, S=S, AP=AP, D=D,
               count=count)
    return am.analyze_weapon(w, HARD, {}, am.WeaponMechanics(),
                             alloc=True)["alloc"]


trade = [hard_law("plasma", "2", 9, -3, "2", 3),
         hard_law("bolter", "6", 5, -1, "1", 3),
         hard_law("melta", "3", 10, -4, "D6", 2)]
tr_order, tr_best, tr_given = kc.best_order(trade, 3, 5)
assert tr_order == [2, 0, 1], tr_order
assert tr_best["spent"] < tr_given["spent"] - 1e-6, \
    (tr_best["spent"], tr_given["spent"])
assert (ds.stats(tr_best["kills"])["mean"]
        < ds.stats(tr_given["kills"])["mean"] - 1e-6), \
    "this case is only worth having because the two criteria conflict"
assert kc.order_score(tr_best) > kc.order_score(tr_given)

# The tie-break: when nothing separates two orders on weapons spent, the
# one that wastes less damage wins.
tied = [{"spent": 2.0, "removed": [0.0, 0.0, 1.0], "kills": [1.0]},
        {"spent": 2.0, "removed": [0.0, 1.0, 0.0], "kills": [1.0]}]
assert kc.order_score(tied[0]) > kc.order_score(tied[1])
# ... and weapons spent outranks it, however big the gap in wounds.
assert kc.order_score({"spent": 1.0, "removed": [1.0], "kills": [1.0]}) \
    > kc.order_score({"spent": 2.0, "removed": [0.0] * 99 + [1.0],
                      "kills": [1.0]})


# ---- 7. weapons spent: what a firing order is really chosen for -------

# 'spent' is the expected number of weapons the unit costs to destroy:
# the probability it is still standing before each weapon fires, summed.
# The weapons AFTER the one that finished it could have been pointed at
# something else, which is the thing the order is picked for and which
# neither 'kills' nor 'removed' can express.


def naive_spent(allocs, wounds, models):
    """The definition, computed the expensive way: re-run the chain on
    every prefix. resolve() reads the same figure off the intermediate
    states it walks through anyway, and the two must agree."""
    return sum(1.0 - kc.resolve(allocs[:k], wounds, models)["p_wipe"]
               for k in range(len(allocs)))


# A unit nothing can kill costs every weapon it has, by definition.
tough = {"T": 12, "Sv": 2, "W": 12, "invuln": 4, "fnp": 5, "models": 5,
         "keywords": set()}
weak = [am.analyze_weapon(light, tough, {}, am.WeaponMechanics(),
                          alloc=True)["alloc"]] * 3
close(kc.resolve(weak, 12, 5)["spent"], 3.0)

# A unit the first weapon always wipes costs exactly one, whatever else
# is queued behind it.
huge = Weapon(name="huge", wtype="Ranged", A="30", skill=2, S=20, AP=-4,
              D="12", count=1)
over = [am.analyze_weapon(huge, ORDER_REF, {}, am.WeaponMechanics(),
                          alloc=True)["alloc"],
        am.analyze_weapon(light, ORDER_REF, {}, am.WeaponMechanics(),
                          alloc=True)["alloc"]]
assert kc.resolve(over, 3, 5)["p_wipe"] > 0.999
close(kc.resolve(over, 3, 5)["spent"], 1.0, eps=1e-3)

# Order changes it where kills and removed cannot see anything: the two
# orders below destroy the same models and take off the same wounds, and
# still one of them frees a weapon more often than the other.
med = Weapon(name="med", wtype="Ranged", A="6", skill=2, S=10, AP=-3,
             D="4", count=1)
many = Weapon(name="many", wtype="Ranged", A="8", skill=2, S=10, AP=-3,
              D="1", count=1)
duo = [am.analyze_weapon(x, ORDER_REF, {}, am.WeaponMechanics(),
                         alloc=True)["alloc"] for x in (med, many)]
a, b = kc.resolve(duo, 3, 5), kc.resolve(duo[::-1], 3, 5)
close(ds.stats(a["kills"])["mean"], ds.stats(b["kills"])["mean"])
assert abs(a["spent"] - b["spent"]) > 1e-6, (a["spent"], b["spent"])

# And the cheap figure is the definition, on every shape above.
for allocs, W, m in ((weak, 12, 5), (over, 3, 5), (duo, 3, 5),
                     (duo[::-1], 3, 5), (pair, 3, 5), (pair[::-1], 3, 5)):
    close(kc.resolve(allocs, W, m)["spent"], naive_spent(allocs, W, m))

# An empty queue spends nothing; one weapon that cannot win spends one.
close(kc.resolve([], 3, 5)["spent"], 0.0)
close(kc.resolve(pair[:1], 3, 5)["spent"], 1.0)

assert not failures, failures
print("kill chain: OK")
