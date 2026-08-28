"""The unmodified-roll FLOOR on the hit roll, and what a critical
threshold may and may not do to it.

Two mechanics put a floor under the hit roll:

  * "hits only on an unmodified X+, irrespective of any modifiers"
    (mech.hit_unmod_only, from an OVERRIDE HIT ONLY IRRESPECTIVE
    ability);
  * 11th-ed. INDIRECT FIRE (unmodified 6, or 4 with a spotter) and
    Overwatch / Snap Shooting (unmodified 6 by default).

11th-ed. rules under test:

  * a Critical hit is automatically successful, but it is still a HIT
    ROLL: a floor that says "nothing below X+ hits" is not a modifier
    and a lowered critical threshold cannot lift a die past it;
  * the floor and the critical threshold combine as the STRICTER of the
    two - a die must clear the floor to hit at all, and clear the
    critical threshold to be critical;
  * the two engines must agree exactly, since the dice resolver reads
    the same WeaponMechanics.

Expected values are written out in closed form here, independently of
the engine.

Regression: with hit_unmod_only=5 and a critical threshold of 4+ the
exact chain used to score 3/6 hits (faces 4, 5, 6 - the 4 sneaking in
as an "automatic" critical) where the dice resolver scored 2/6. See the
handoff for the measurement.
"""
import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
from unit_model import Weapon

TOL = 1e-12


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def close(a, b, what):
    assert abs(a - b) < TOL, f"{what}: engine={a!r} expected={b!r}"


# --- 1. roll_probs: the floor gates the critical faces ----------------
# Floor 5+, criticals on 6: faces 5 and 6 hit, only the 6 is critical.
p, pc = am.roll_probs(5, 0, None, crit_on=6, unmod_min=5)
close(p, 2 / 6, "floor 5+, crit 6+: hits")
close(pc, 1 / 6, "floor 5+, crit 6+: criticals")

# Floor 5+, criticals on 4+: the 4 is BELOW the floor and cannot hit,
# so both remaining faces hit and both are critical.
p, pc = am.roll_probs(5, 0, None, crit_on=4, unmod_min=5)
close(p, 2 / 6, "floor 5+, crit 4+: the 4 does not hit")
close(pc, 2 / 6, "floor 5+, crit 4+: 5 and 6 are both critical")

# Without the floor the same critical threshold DOES let the 4 through:
# that is the behaviour the floor has to suppress, kept here so the
# check above cannot pass for the wrong reason.
p, _pc = am.roll_probs(5, 0, None, crit_on=4)
close(p, 3 / 6, "no floor: a critical 4 is an automatic hit")

# Floor 4+ (a spotter), criticals on 6: three faces hit, one critical.
p, pc = am.roll_probs(4, 0, None, crit_on=6, unmod_min=4)
close(p, 3 / 6, "floor 4+: hits")
close(pc, 1 / 6, "floor 4+: criticals")
print("roll_probs: the unmodified floor gates the critical faces")


# --- 2. the whole chain, hit_unmod_only + a lowered critical ----------
# 6 attacks, one copy. S8 vs T4 wounds on 2+ (5/6); AP-6 against a 6+
# save with no invuln is unsaveable, and Damage is flat 1, so the total
# damage is exactly attacks x p_hit x 5/6.
W = Weapon(name="t", wtype="Ranged", A="6", skill=3, S=8, AP=-6, D="1",
           count=1)
REF = {"T": 4, "Sv": 6, "W": 1, "invuln": None, "fnp": None, "models": 1,
       "keywords": {"INFANTRY"}}
A, Q_W = 6, 5 / 6


def damage_mean(m, ctx=None):
    return am.analyze_weapon(W, REF, ctx or {}, m)["damage"]["mean"]


# Plain "hits only on an unmodified 5+": 2/6 of the attacks land.
close(damage_mean(mech(hit_unmod_only=5)), A * (2 / 6) * Q_W,
      "hit_unmod_only 5+")

# Same, with criticals on 4+ (a criticalThreshold ability). The 4 is
# below the floor, so the hit rate does NOT move.
close(damage_mean(mech(hit_unmod_only=5, crit_hit_on=4)),
      A * (2 / 6) * Q_W,
      "hit_unmod_only 5+ with criticals on 4+")

# CONVERSION grants criticals on 4+ beyond half range: same story, and
# this is the combination a real datasheet can produce.
close(damage_mean(mech(hit_unmod_only=5, conversion=True)),
      A * (2 / 6) * Q_W,
      "hit_unmod_only 5+ with CONVERSION beyond half range")

# The floor does not suppress what the criticals TRIGGER, though: with
# SUSTAINED HITS 1 the two faces that clear the floor are both critical
# when the threshold is 4+, so every hit brings a second one.
close(damage_mean(mech(hit_unmod_only=5, crit_hit_on=4, sustained=1)),
      A * (2 / 6) * 2 * Q_W,
      "floor 5+, criticals 4+, SUSTAINED HITS 1")
# ...while with criticals on 6 only half of them do.
close(damage_mean(mech(hit_unmod_only=5, sustained=1)),
      A * ((1 / 6) * 2 + (1 / 6)) * Q_W,
      "floor 5+, criticals 6+, SUSTAINED HITS 1")
print("analyze_weapon: a critical below the floor is not a hit")


# --- 3. the floors that come from the CONTEXT -------------------------
# INDIRECT FIRE: unmodified 6, or 4 with a spotter. A lowered critical
# threshold must not lift the die past either.
for spotter, floor in ((False, 6), (True, 4)):
    ctx = {"indirect": True, "spotter": spotter}
    want = A * ((7 - floor) / 6) * Q_W
    close(damage_mean(mech(indirect=True), ctx), want,
          f"indirect fire, spotter={spotter}")
    close(damage_mean(mech(indirect=True, conversion=True), ctx), want,
          f"indirect fire + CONVERSION, spotter={spotter}")

# Overwatch: unmodified 6 only, and the same again.
close(damage_mean(mech(), {"overwatch": True}), A * (1 / 6) * Q_W,
      "overwatch")
close(damage_mean(mech(crit_hit_on=4), {"overwatch": True}),
      A * (1 / 6) * Q_W, "overwatch with criticals on 4+")
# The ABILITY threshold and the CONTEXT floor are two different
# thresholds on the same die and the stricter one wins. The Hunter's
# skyspear missile launcher ("scores a hit on an unmodified 2+") firing
# Overwatch is the real case: Snap Shooting still only lets a 6 through.
close(damage_mean(mech(hit_unmod_only=2), {"overwatch": True}),
      A * (1 / 6) * Q_W,
      "hits on an unmodified 2+, but Snap Shooting floors it at 6")
close(damage_mean(mech(hit_unmod_only=2, indirect=True),
                  {"indirect": True}),
      A * (1 / 6) * Q_W,
      "hits on an unmodified 2+, floored at 6 by indirect fire")
close(damage_mean(mech(hit_unmod_only=2, indirect=True),
                  {"indirect": True, "spotter": True}),
      A * (3 / 6) * Q_W,
      "hits on an unmodified 2+, floored at 4 by a spotter")
# ...and the ability threshold still wins when it is the stricter one.
close(damage_mean(mech(hit_unmod_only=5, indirect=True),
                  {"indirect": True, "spotter": True}),
      A * (2 / 6) * Q_W,
      "unmodified 5+ beats the spotter's floor of 4")
print("context floors (indirect fire, overwatch) gate criticals too")


# --- 4. the two engines agree, die by die -----------------------------
# The dice resolver decides the same question with a predicate rather
# than a probability, so the check is on the FACES it accepts: a
# disagreement here is what the parity sweep would only see as a mean.
import attack_resolve as ar                                  # noqa: E402
import random                                                # noqa: E402


def dice_hit_rate(m, ctx=None, trials=60000, seed=7):
    """Fraction of attacks that produced a wound event, with the wound
    and save stages made deterministic (auto-wound, no save)."""
    m = m.copy()
    m.auto_wound = True
    rng = random.Random(seed)
    hits = att = 0
    for _ in range(trials):
        r = ar.resolve_weapon(W, REF, ctx or {}, m.copy(), rng)
        att += r["attacks"]
        hits += len(r["events"])
    return hits / att


for name, m, ctx in (
        ("floor 5+, crit 6+", mech(hit_unmod_only=5), {}),
        ("floor 5+, crit 4+", mech(hit_unmod_only=5, crit_hit_on=4), {}),
        ("floor 5+, CONVERSION", mech(hit_unmod_only=5, conversion=True),
         {}),
        ("indirect, crit 4+", mech(indirect=True, crit_hit_on=4),
         {"indirect": True})):
    exact = am.analyze_weapon(W, REF, ctx, m.copy())
    p_exact = exact["audit"]["hit"]["p"]
    p_dice = dice_hit_rate(m, ctx)
    assert abs(p_exact - p_dice) < 0.01, \
        f"{name}: exact p_hit={p_exact:.4f} dice={p_dice:.4f}"
print("exact and dice engines accept the same faces")


# --- 5. the same die, shared with a mortal-wound threshold ------------
# "On an unmodified Hit roll of thr+ the target suffers mortal wounds
# and the attack sequence ends" (mech.hitroll_mw). The threshold shares
# the die with the hit roll, so the floor and the critical threshold
# both reach it.
def mw(thr, **kw):
    d = {"thr": thr, "value": None, "match": True, "end": True}
    d.update(kw)
    return d


# Faces of the die, with no floor and no lowered critical: 5 and 6 feed
# the mortal branch, nothing is critical (the natural 6 went to the
# mortal branch), and 2..4 hit on their modified value.
p_mw, p_hit, p_crit = am.hit_threshold_mw_probs(4, 0, None, 5)
close(p_mw, 2 / 6, "thr 5+: mortal faces")
close(p_hit, 1 / 6, "thr 5+ vs a 4+ target: only the 4 hits")
close(p_crit, 0.0, "thr 5+: the natural 6 leaves no critical hit")

# Criticals on 4+: the 4 is now a critical hit, automatically
# successful, so it hits even against a target it could never beat.
p_mw, p_hit, p_crit = am.hit_threshold_mw_probs(9, 0, None, 5, crit_on=4)
close(p_mw, 2 / 6, "thr 5+ crit 4+: mortal faces unchanged")
close(p_hit, 1 / 6, "thr 5+ crit 4+: the critical 4 hits regardless")
close(p_crit, 1 / 6, "thr 5+ crit 4+: and it is critical")

# The floor wins over both. Snap Shooting: "each attack only hits on an
# unmodified 6, irrespective of the weapon's BS characteristic or any
# modifiers" - a threshold on the same die that the roll never reached.
p_mw, p_hit, p_crit = am.hit_threshold_mw_probs(4, 0, None, 5,
                                                crit_on=4, unmod_min=6)
close(p_mw, 1 / 6, "floor 6: only the 6 reaches the mortal branch")
close(p_hit, 0.0, "floor 6: nothing below it hits")
close(p_crit, 0.0, "floor 6: and nothing below it is critical")

# A floor BELOW the threshold leaves the band between them alone.
p_mw, p_hit, p_crit = am.hit_threshold_mw_probs(4, 0, None, 5,
                                                unmod_min=4)
close(p_mw, 2 / 6, "floor 4, thr 5+: mortal faces")
close(p_hit, 1 / 6, "floor 4, thr 5+: the 4 still hits")

# An unmodified 1 always fails, even when the modifier would carry it
# past the target: BS2+ with +1 to hit still misses on a 1.
p_mw, p_hit, p_crit = am.hit_threshold_mw_probs(2, +1, None, 5)
close(p_hit, 3 / 6, "thr 5+, BS2+ and +1: the natural 1 still misses")

# Re-rolls carry all three regions, criticals included: with a failed
# die re-rolled once the critical band is entered on the second die too.
p_mw0, p_hit0, p_crit0 = am.hit_threshold_mw_probs(9, 0, None, 5,
                                                   crit_on=4)
p_fail0 = 1 - p_mw0 - p_hit0
p_mw, p_hit, p_crit = am.hit_threshold_mw_probs(9, 0, "fails", 5,
                                                crit_on=4)
close(p_mw, p_mw0 * (1 + p_fail0), "re-roll fails: mortal faces")
close(p_hit, p_hit0 * (1 + p_fail0), "re-roll fails: hits")
close(p_crit, p_crit0 * (1 + p_fail0), "re-roll fails: criticals")

# Whole chain. Same weapon as above but BS5+ with -1 to hit, so a bare
# roll needs a 6 and every hit below the threshold can only be a
# critical one. Damage is flat 1 and unsaveable; the mortal stream
# matches the Damage characteristic, so it is 1 point too.
WM = Weapon(name="m", wtype="Ranged", A="6", skill=5, S=8, AP=-6, D="1",
            count=1)


def mw_damage(m, ctx=None):
    return am.analyze_weapon(WM, REF, ctx or {}, m)["damage"]["mean"]


close(mw_damage(mech(hitroll_mw=mw(5), hit_mod=-1)), A * (2 / 6),
      "thr 5+: the mortal branch alone")
close(mw_damage(mech(hitroll_mw=mw(5), hit_mod=-1, crit_hit_on=4)),
      A * (2 / 6 + 1 / 6 * Q_W),
      "thr 5+ crit 4+: the critical 4 is an automatic hit")
close(mw_damage(mech(hitroll_mw=mw(5), hit_mod=-1, conversion=True)),
      A * (2 / 6 + 1 / 6 * Q_W),
      "thr 5+ with CONVERSION beyond half range")
close(mw_damage(mech(hitroll_mw=mw(5), hit_mod=-1, crit_hit_on=4,
                     sustained=1)),
      A * (2 / 6 + 1 / 6 * 2 * Q_W),
      "thr 5+ crit 4+ SUSTAINED HITS 1: the critical brings a second hit")
close(mw_damage(mech(hitroll_mw=mw(5), hit_mod=-1, crit_hit_on=4,
                     lethal=True)),
      A * (2 / 6 + 1 / 6),
      "thr 5+ crit 4+ LETHAL HITS: the critical wounds automatically")

# The floors from the context reach it too: under Snap Shooting only the
# unmodified 6 does anything at all, threshold or no threshold.
close(mw_damage(mech(hitroll_mw=mw(5), hit_mod=-1), {"overwatch": True}),
      A * (1 / 6), "overwatch: the 5 no longer triggers the threshold")
close(mw_damage(mech(hitroll_mw=mw(5), hit_mod=-1, crit_hit_on=4),
                {"overwatch": True}),
      A * (1 / 6), "overwatch with criticals on 4+")
close(mw_damage(mech(hitroll_mw=mw(5), hit_mod=-1, indirect=True),
                {"indirect": True}),
      A * (1 / 6), "indirect fire without a spotter")
close(mw_damage(mech(hitroll_mw=mw(3), hit_mod=-1, indirect=True),
                {"indirect": True, "spotter": True}),
      A * (3 / 6), "indirect fire with a spotter, threshold 3+")

# TORRENT makes no hit roll at all, so no floor and no threshold can
# touch it: it still hits automatically in Overwatch. The threshold is
# reported as ignored rather than silently dropped.
res = am.analyze_weapon(WM, REF, {"overwatch": True},
                        mech(hitroll_mw=mw(5), torrent=True))
close(res["damage"]["mean"], A * Q_W, "TORRENT in overwatch auto-hits")
assert any("auto-hit" in x for x in res["warnings"]), res["warnings"]
print("hit-roll mortal-wound threshold: floor and criticals both apply")


# --- 6. the two engines agree on the mortal branch as well ------------
# WM3 is the same weapon at BS3+: with a skill good enough to hit on its
# own numbers, the band BELOW the threshold is populated, which is what
# makes "the floor gates the hits too" and "those hits are not critical"
# observable at all.
WM3 = Weapon(name="m3", wtype="Ranged", A="6", skill=3, S=8, AP=-6,
             D="1", count=1)

# Exact values for WM3, worked out here: under indirect fire the target
# counts as in cover (-1 BS -> 4+) and nothing below an unmodified 6
# gets through, so the whole result is the mortal branch.
close(am.analyze_weapon(WM3, REF, {"indirect": True},
                        mech(hitroll_mw=mw(5), indirect=True)
                        )["damage"]["mean"],
      A * (1 / 6),
      "BS3+, thr 5+, indirect: the floor closes the band below it")
# Without the floor, that band is open and its faces are ORDINARY hits:
# SUSTAINED HITS must not fire on them.
close(am.analyze_weapon(WM3, REF, {},
                        mech(hitroll_mw=mw(5), sustained=1)
                        )["damage"]["mean"],
      A * (2 / 6 + 2 / 6 * Q_W),
      "BS3+, thr 5+, SUSTAINED 1: the 3 and the 4 are not critical")

for name, m, ctx, wpn in (
        ("thr 5, crit 6+", mech(hitroll_mw=mw(5), hit_mod=-1), {}, WM),
        ("thr 5, crit 4+", mech(hitroll_mw=mw(5), hit_mod=-1,
                                crit_hit_on=4), {}, WM),
        ("thr 5, crit 4+, sustained 1",
         mech(hitroll_mw=mw(5), hit_mod=-1, crit_hit_on=4,
              sustained=1), {}, WM),
        ("thr 5, overwatch", mech(hitroll_mw=mw(5), hit_mod=-1),
         {"overwatch": True}, WM),
        ("thr 5, indirect", mech(hitroll_mw=mw(5), hit_mod=-1,
                                 indirect=True), {"indirect": True}, WM),
        ("BS3+, thr 5, indirect",
         mech(hitroll_mw=mw(5), indirect=True), {"indirect": True}, WM3),
        ("BS3+, thr 5, sustained 1 (no crits below thr)",
         mech(hitroll_mw=mw(5), sustained=1), {}, WM3),
        ("BS3+, thr 5, unmod 2+ ability floored by overwatch",
         mech(hit_unmod_only=2), {"overwatch": True}, WM3)):
    exact = am.analyze_weapon(wpn, REF, ctx, m.copy())["damage"]["mean"]
    rng = random.Random(11)
    tot = 0
    for _ in range(40000):
        r = ar.resolve_weapon(wpn, REF, ctx, m.copy(), rng)
        tot += sum(e["amount"] for e in r["events"])
    assert abs(exact - tot / 40000) < 0.06, \
        f"{name}: exact={exact:.4f} dice={tot / 40000:.4f}"
print("exact and dice engines agree on the mortal-wound threshold")

print("OK  test_unmod_floor")
