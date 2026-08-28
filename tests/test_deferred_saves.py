"""The deferred save stage: attack_resolve.resolve_weapon(defer_save=True)
plus resolve_saves() against an alloc_groups.Allocation.

Two kinds of check, because they prove different things.

PARITY. Against a HOMOGENEOUS target the split must change nothing: one
group, one save profile, so the two-phase path has to reproduce the
exact PMF of attack_math just as the one-pass resolver does. This is
what catches a die drawn in the wrong order, a re-roll budget spent on
the wrong roll, or a branch that quietly stopped emitting.

PER-MODEL. Parity cannot see the point of the exercise: it uses one
profile, so it would pass just as happily if the save were still taken
from a single reference. Those checks therefore build the pending list
by hand and drive resolve_saves with a SCRIPTED die, so the outcome is
arithmetic rather than statistics -- with a flat damage and no Feel No
Pain, a wounding attack consumes exactly one die, the save roll.
"""
import random

import testpaths                      # sets up sys.path to the engine src/
import mc_support as mcs
import alloc_groups as ag
import attack_math as am
import attack_resolve as ar
from unit_model import Weapon


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def homogeneous(ref, n=40, cap=100000):
    """An Allocation deep enough that nothing is ever wasted and nothing
    ever runs out of targets, so the damage that lands equals the damage
    that was rolled -- which is what analyze_weapon's PMF counts."""
    models = [{"key": i, "label": f"m{i}", "wounds": cap, "max": cap,
               "sv": ref["Sv"], "invuln": ref["invuln"],
               "fnp": ref["fnp"], "character": False,
               "entry": 0, "scarcity": n}
              for i in range(n)]
    return ag.Allocation(models)


def sample_deferred(weapon, ref, ctx, mech_, trials=None, seed=None):
    """Total damage per activation, resolved in two phases."""
    trials = mcs.TRIALS if trials is None else trials
    rng = random.Random(mcs.SEED if seed is None else seed)
    out = []
    for _ in range(trials):
        m = mcs.clone_mech(mech_)
        first = ar.resolve_weapon(weapon, ref, ctx, m, rng, 1,
                                  defer_save=True)
        assert not first["events"], "defer_save must emit no events"
        alloc = homogeneous(ref)
        second = ar.resolve_saves(first["pending"], weapon, m, rng,
                                  alloc, ctx)
        assert second["no_target"] == 0, second
        # The damage that landed and the damage that was rolled must be
        # the same number here: a deep enough target wastes nothing.
        landed = sum(n for e in second["events"] for _k, n in e["hits"])
        total = sum(e["amount"] for e in second["events"])
        assert landed == total, (landed, total)
        out.append(total)
    return out


# --- 1. parity with the exact engine, homogeneous target --------------

WEAPON = Weapon(name="A", wtype="Ranged", A="D6+2", skill=3, S=6, AP=-2,
                D="D3+1", count=3)
REF = {"T": 5, "Sv": 3, "W": 3, "invuln": 5, "fnp": None, "models": 11,
       "keywords": {"VEHICLE"}}
FLAT = Weapon(name="F", wtype="Melee", A="4", skill=3, S=8, AP=-1, D="2",
              count=2)
REF_FNP = {"T": 6, "Sv": 4, "W": 4, "invuln": None, "fnp": 5, "models": 5,
           "keywords": {"MONSTER"}}

CASES = [
    ("plain", WEAPON, REF, mech(), {}),
    ("sustained 2", WEAPON, REF, mech(sustained=2), {}),
    ("lethal hits", WEAPON, REF, mech(lethal=True), {}),
    ("devastating", WEAPON, REF, mech(devastating=True), {}),
    ("dev + anti", WEAPON, REF,
     mech(devastating=True, anti=[("VEHICLE", 4)]), {}),
    ("crit mw, sequence goes on", WEAPON, REF,
     mech(crit_mw={"value": 1, "match": False, "end": False,
                   "spill": True}), {}),
    ("mortal on the hit roll", WEAPON, REF,
     mech(hitroll_mw={"thr": 6, "match": True, "value": None,
                      "spill": True}), {}),
    # No invulnerable here on purpose: with Sv3+ and AP-2 the armour is
    # already a 5+, so an invuln 5+ would tie it and sharpening the AP
    # on the critical branch would change nothing at all.
    ("crit AP", WEAPON, dict(REF, invuln=None),
     mech(crit_ap_delta=2), {}),
    ("invuln vs mortals", WEAPON, REF,
     mech(devastating=True, invuln_mw=5), {}),
    ("one damage re-roll", WEAPON, REF, mech(single_reroll="damage"), {}),
    ("one hit re-roll", WEAPON, REF, mech(single_reroll="hit"), {}),
    ("melta at half range", WEAPON, REF, mech(melta=2),
     {"half_range": True}),
    ("feel no pain", FLAT, REF_FNP, mech(), {}),
    ("fnp + devastating", FLAT, REF_FNP, mech(devastating=True), {}),
    ("re-roll saves", FLAT, REF_FNP, mech(reroll_save="fails"), {}),
]

failures = []
for name, weapon, ref, m, ctx in CASES:
    exact = am.analyze_weapon(weapon, ref, ctx, mcs.clone_mech(m))
    samples = sample_deferred(weapon, ref, ctx, m)
    ok, msg = mcs.parity_report(name, exact["damage_pmf"], samples)
    print("  " + msg)
    if not ok:
        failures.append(name)
assert not failures, failures
print("deferred path matches the exact PMF on a homogeneous target")


# --- the scripted die -------------------------------------------------

class Dice:
    """A d6 that returns a written sequence, then repeats its last value.
    Only randint is needed: with a flat Damage and no Feel No Pain the
    save roll is the only die resolve_saves draws."""

    def __init__(self, seq):
        self.seq = list(seq)
        self.drawn = 0

    def randint(self, _a, _b):
        v = self.seq[min(self.drawn, len(self.seq) - 1)]
        self.drawn += 1
        return v


FLAT1 = Weapon(name="D1", wtype="Ranged", A="1", skill=3, S=4, AP=0,
               D="1", count=1)


def two_groups(body_sv=6, body_w=1, bodies=1, char_sv=2, char_inv=2,
               char_w=5):
    """One bodyguard group and one CHARACTER, with saves far enough
    apart that a single die tells which model was used."""
    models = [{"key": f"b{i}", "label": f"Body {i}", "wounds": body_w,
               "max": body_w, "sv": body_sv, "invuln": None, "fnp": None,
               "character": False, "entry": 0, "scarcity": bodies}
              for i in range(bodies)]
    models.append({"key": "cpt", "label": "Captain", "wounds": char_w,
                   "max": char_w, "sv": char_sv, "invuln": char_inv,
                   "fnp": None, "character": True, "entry": 1,
                   "scarcity": 1})
    return models


def wounds(n, ap=0):
    return [{"kind": "wound", "ap": ap} for _ in range(n)]


# --- 2. the save follows the MODEL, not one reference profile ---------

# Six wounding attacks, every save roll a 3. The bodyguard saves on 6+
# and dies to the first; the Captain saves on 2+ and shrugs the other
# five off. Under the old single-reference behaviour the same six dice
# would have killed the Captain outright.
alloc = ag.Allocation(two_groups())
res = ar.resolve_saves(wounds(6), FLAT1, mech(), Dice([3]), alloc)
rows = {r["key"]: r for r in alloc.result()}
assert rows["b0"]["dead"] is True, rows
assert rows["cpt"]["after"] == 5, rows
assert res["saves_made"] == 5, res

# The same six attacks with every save roll a 1 (an unmodified 1 always
# fails) reach the Captain, which is what makes the check above mean
# something: he was reachable, and the SAVE is what stopped the damage.
alloc = ag.Allocation(two_groups())
res = ar.resolve_saves(wounds(6), FLAT1, mech(), Dice([1]), alloc)
rows = {r["key"]: r for r in alloc.result()}
assert rows["b0"]["dead"] is True and rows["cpt"]["after"] == 0, rows
assert res["saves_made"] == 0, res
print("the save roll uses the profile of the model it was allocated to")


# --- 3. AP is carried per pending attack ------------------------------

# Sv2+ Captain alone, AP-3 makes it a 5+: a roll of 4 fails where it
# would have saved at AP0.
solo = [{"key": "cpt", "label": "Captain", "wounds": 5, "max": 5,
         "sv": 2, "invuln": None, "fnp": None, "character": True,
         "entry": 0, "scarcity": 1}]
alloc = ag.Allocation(solo)
ar.resolve_saves(wounds(2, ap=-3), FLAT1, mech(), Dice([4]), alloc)
assert alloc.result()[0]["after"] == 3, alloc.result()
alloc = ag.Allocation(solo)
ar.resolve_saves(wounds(2, ap=0), FLAT1, mech(), Dice([4]), alloc)
assert alloc.result()[0]["after"] == 5, alloc.result()
print("the AP settled at the wound stage travels with the attack")


# --- 4. mortal wounds: devastating wastes, real ones spill ------------

# DEVASTATING: 3 mortal wounds onto a one-wound body. Two are wasted and
# nothing reaches the Captain (no spill), and no save is rolled.
alloc = ag.Allocation(two_groups())
dev = [{"kind": "mortal", "value": 3, "match": False, "spills": False}]
res = ar.resolve_saves(dev, FLAT1, mech(), Dice([6]), alloc)
rows = {r["key"]: r for r in alloc.result()}
assert rows["b0"]["dead"] is True and rows["cpt"]["after"] == 5, rows
assert alloc.wasted == 2 and res["saves_made"] == 0, (alloc.wasted, res)

# A real mortal wound of the same size spills: one point kills the body,
# the other two pass to the Captain.
alloc = ag.Allocation(two_groups())
spill = [{"kind": "mortal", "value": 3, "match": False, "spills": True}]
ar.resolve_saves(spill, FLAT1, mech(), Dice([6]), alloc)
rows = {r["key"]: r for r in alloc.result()}
assert rows["b0"]["dead"] is True and rows["cpt"]["after"] == 3, rows
assert alloc.wasted == 0, alloc.wasted
# And they are applied LAST, after every point of normal damage
# (06.02). Order matters here because the two waste differently: a
# 3-damage attack onto a one-wound body throws two away, and the
# spilling mortal wound that follows finds the Captain at full health.
# Applied the other way round the mortal would kill the body for one
# point, spill the second onto the Captain, and the 3-damage attack
# would then reach him with nothing wasted at all.
FLAT3 = Weapon(name="D3", wtype="Ranged", A="1", skill=3, S=4, AP=0,
               D="3", count=1)
alloc = ag.Allocation(two_groups(body_sv=None, bodies=1, body_w=1,
                                 char_sv=None, char_inv=None, char_w=5))
mix = wounds(1) + [{"kind": "mortal", "value": 2, "match": False,
                    "spills": True}]
ar.resolve_saves(mix, FLAT3, mech(), Dice([6]), alloc)
rows = {r["key"]: r for r in alloc.result()}
assert rows["b0"]["dead"] is True and rows["cpt"]["after"] == 3, rows
assert alloc.wasted == 2, alloc.wasted
print("devastating wounds waste the excess, real mortal wounds spill")


# --- 5. Feel No Pain is the target's, not the unit's ------------------

# The bodyguard shrugs on 4+, the Captain does not. With every die a 5:
# no save is made (Sv6+ and Sv2+ both... the body fails on 5, the
# captain saves), so drive it with a body that cannot save at all.
mixed = two_groups(body_sv=None, bodies=2, body_w=1, char_sv=None,
                   char_inv=None, char_w=3)
mixed[0]["fnp"] = 4
mixed[1]["fnp"] = 4
alloc = ag.Allocation(mixed)
# Save roll (auto-fail, no save characteristic at all -> no die drawn),
# then one FNP die per damage point: a 5 shrugs it, a 3 does not.
res = ar.resolve_saves(wounds(4), FLAT1, mech(), Dice([5]), alloc)
rows = {r["key"]: r for r in alloc.result()}
assert rows["b0"]["after"] == 1 and rows["b1"]["after"] == 1, rows
assert res["shrugged"] == 4, res
# The Captain has no Feel No Pain, so the same dice go straight through.
alloc = ag.Allocation(mixed)
alloc.set_precision(alloc.character_groups()[0])
res = ar.resolve_saves(wounds(3), FLAT1, mech(), Dice([5]), alloc)
assert {r["key"]: r["after"] for r in alloc.result()}["cpt"] == 0
assert res["shrugged"] == 0, res
print("Feel No Pain is rolled with the target model's own value")


# --- 5b. and so is the Feel No Pain of a wound that SPILLS ------------

# The body has none and the Captain shrugs on 4+. One point kills the
# body; the three that spill over must be rolled against the CAPTAIN's
# value, not against the value of whoever was hit first.
fnp_mix = two_groups(body_sv=None, bodies=1, body_w=1, char_sv=None,
                     char_inv=None, char_w=3)
fnp_mix[1]["fnp"] = 4
alloc = ag.Allocation(fnp_mix)
res = ar.resolve_saves([{"kind": "mortal", "value": 4, "match": False,
                         "spills": True}], FLAT1, mech(), Dice([5]),
                       alloc)
rows = {r["key"]: r for r in alloc.result()}
assert rows["b0"]["dead"] is True and rows["cpt"]["after"] == 3, rows
assert res["shrugged"] == 3, res

# And the model a spilling mortal wound picks follows 06.02, which is
# NOT the allocation order: with PRECISION pointing every ATTACK at the
# Captain, the mortal wound still goes to the bodyguard first.
alloc = ag.Allocation(two_groups(body_sv=None, bodies=1, body_w=1,
                                 char_sv=None, char_inv=None, char_w=5))
alloc.set_precision(alloc.character_groups()[0])
ar.resolve_saves([{"kind": "mortal", "value": 1, "match": False,
                   "spills": True}], FLAT1, mech(), Dice([6]), alloc)
rows = {r["key"]: r for r in alloc.result()}
assert rows["b0"]["dead"] is True and rows["cpt"]["after"] == 5, rows
print("a spilling wound picks its model, and its shrug, one point at a time")


# --- 6. nothing left to allocate to -----------------------------------

alloc = ag.Allocation(two_groups(body_sv=None, bodies=1, char_sv=None,
                                 char_inv=None, char_w=1))
res = ar.resolve_saves(wounds(5), FLAT1, mech(), Dice([1]), alloc)
assert alloc.wiped() and res["no_target"] == 3, res
print("attacks with no model left are counted, not silently dropped")


# --- 7. the first half really is unit-only ----------------------------

# Same seed, same weapon, two DIFFERENT save profiles: the pending list
# must be identical, because nothing before the save depends on which
# model the attack lands on.
def pending_for(ref):
    return ar.resolve_weapon(WEAPON, ref, {}, mech(devastating=True),
                             random.Random(99), 1, defer_save=True)


soft = dict(REF, Sv=6, invuln=None, fnp=None)
hard = dict(REF, Sv=2, invuln=3, fnp=4)
assert pending_for(soft)["pending"] == pending_for(hard)["pending"]
assert pending_for(soft)["attacks"] == pending_for(hard)["attacks"]
print("the first half depends on the unit only, never on the save")


# --- 8. the deferred mortal wound carries the right spill flag --------

def mortals_of(m):
    out = []
    for seed in range(12):
        res = ar.resolve_weapon(WEAPON, REF, {}, m, random.Random(seed),
                                1, defer_save=True)
        out += [p for p in res["pending"] if p["kind"] == "mortal"]
    return out


# DEVASTATING WOUNDS do not spill; an explicit mortalWounds ability does
# unless it says otherwise. The flag is decided in the first half and
# read in the second, so it has to survive the trip.
dev = mortals_of(mech(devastating=True))
assert dev and all(p["spills"] is False for p in dev), dev[:3]
real = mortals_of(mech(crit_mw={"value": 1, "match": False, "end": True,
                                "spill": True}))
assert real and all(p["spills"] is True for p in real), real[:3]
print("the spill flag survives the split")

# --- the pool is resolved in three phases, not attack by attack -------

# 06.02 resolves every ordinary wound first, then the mortal wounds that
# do not spill, then the ones that do. The queue is built in ATTACK
# order, so a critical wound rolled on the second attack used to be
# allocated before the ordinary damage of the third - same dice,
# different model, and so a different amount of damage wasted.

# Both kinds of mortal wound at once, so the order BETWEEN them is
# checked and not only their order against the ordinary wounds: a
# DEVASTATING critical does not spill, an ability-driven one does.
_dev = Weapon(name="dev", wtype="Ranged", A="8", skill=2, S=5, AP=-2,
              D="2", count=3, keywords=["DEVASTATING WOUNDS"])
_m = mech()
_m.devastating = True
_m.crit_wound = 5
_m.hitroll_mw = {"thr": 5, "value": 1, "match": False, "spill": True}

_mixed = 0
for _seed in range(40):
    _r = ar.resolve_weapon(_dev, dict(REF), {}, mcs.clone_mech(_m),
                           random.Random(_seed), 1, defer_save=True)
    _k = [it["kind"] for it in _r["pending"]]
    _runs, _last = 0, None
    for _x in _k:
        if _x != _last:
            _runs += 1
            _last = _x
    _mixed += 1 if _runs > 2 else 0
assert _mixed > 5, f"only {_mixed} of 40 queues interleave: weak sample"

# However the queue was built, the wounds are TAKEN in phases.
for _seed in range(12):
    _r = ar.resolve_weapon(_dev, dict(REF), {}, mcs.clone_mech(_m),
                           random.Random(_seed), 1, defer_save=True)
    _out = ar.resolve_saves(_r["pending"], _dev, mcs.clone_mech(_m),
                            random.Random(_seed), homogeneous(REF), {})
    _phase = [0 if e["kind"] == "damage" else
              (2 if e.get("spills") else 1) for e in _out["events"]]
    assert _phase == sorted(_phase), (_seed, _phase)
print("the pool is taken in phases: wounds, then mortals, then spills")

print("deferred saves: all checks passed")
