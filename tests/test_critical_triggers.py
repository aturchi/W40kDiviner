"""Critical hits and critical wounds: when they are scored and what they
trigger (Sustained Hits, Lethal Hits, Devastating Wounds, Anti-X).

11th-ed. rules under test:
  * a Critical hit/wound is an UNMODIFIED roll of crit_on+ (6 by
    default), so roll modifiers never create or destroy one;
  * an unmodified 1 is never a critical and never succeeds, an
    unmodified 6 always succeeds;
  * a critical is automatically a success, whatever the target number;
  * Anti-X lowers the critical WOUND threshold only (never the hit one);
  * a Lethal Hits auto-wound is NOT a critical wound, so it cannot
    trigger Devastating Wounds;
  * Sustained bonus hits are ordinary hits: they cannot trigger Lethal
    or Sustained again.

Expected values are written out in closed form here, independently of
the engine, so this file also acts as a small hand-computed reference.
"""
import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
from unit_model import Weapon

TOL = 1e-9


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def close(a, b, what):
    assert abs(a - b) < TOL, f"{what}: engine={a!r} expected={b!r}"


# --- 1. where the criticals are, die by die ---------------------------
# BS5+ with -1 to hit: only an unmodified 6 lands, and it is a critical.
close(am.roll_probs(5, -1)[0], 1 / 6, "hit prob at 6s only")
close(am.roll_probs(5, -1)[1], 1 / 6, "crit prob is modifier-independent")
# BS2+ with +1: the unmodified 1 still fails and is still not a critical.
close(am.roll_probs(2, +1)[0], 5 / 6, "unmodified 1 always fails")
close(am.roll_probs(2, +1)[1], 1 / 6, "unmodified 1 is never a critical")
# An impossible target is still hit on a 6 (a critical always succeeds).
close(am.roll_probs(9, 0)[0], 1 / 6, "critical succeeds vs impossible target")
# criticalThreshold 5+: 5 and 6 are criticals AND automatic successes,
# so a 4+ roll gains nothing but a 6+ roll gains the 5.
close(am.roll_probs(4, 0, crit_on=5)[1], 2 / 6, "crit on 5+ counts two faces")
close(am.roll_probs(6, 0, crit_on=5)[0], 2 / 6, "crit on 5+ auto-succeeds")
print("criticals are scored on the unmodified die, modifiers aside")

# --- 2. what a critical HIT triggers -----------------------------------
# 6 attacks, BS3+ (2/3 hit, 1/6 critical), S8 vs T4 -> wounds on 2+
# (5/6, of which 1/6 critical), and an unsavable AP: every wound is
# 1 damage, so the totals below isolate the hit stage.
W = Weapon(name="t", wtype="Ranged", A="6", skill=3, S=8, AP=-6, D="1",
           count=1)
REF = {"T": 4, "Sv": 6, "W": 1, "invuln": None, "fnp": None, "models": 1,
       "keywords": {"VEHICLE"}}
A, P_HIT, P_CRIT, Q_W = 6, 2 / 3, 1 / 6, 5 / 6
P_NORM = P_HIT - P_CRIT


def dmg(m):
    return am.analyze_weapon(W, REF, {}, m)["damage"]["mean"]


close(dmg(mech()), A * P_HIT * Q_W, "plain")
# Lethal Hits: the critical hit wounds automatically instead of rolling.
close(dmg(mech(lethal=True)), A * (P_NORM * Q_W + P_CRIT), "lethal hits")
# Sustained Hits 2: two EXTRA ordinary hits per critical hit.
close(dmg(mech(sustained=2)), A * (P_NORM * Q_W + P_CRIT * 3 * Q_W),
      "sustained 2")
# Combined: one auto-wound from the critical hit, plus 2 bonus hits that
# still have to roll to wound (they are not criticals themselves).
close(dmg(mech(sustained=2, lethal=True)),
      A * (P_NORM * Q_W + P_CRIT * (1 + 2 * Q_W)), "sustained + lethal")
print("critical hits trigger Lethal and Sustained exactly once each")

# --- 3. what a critical WOUND triggers ---------------------------------
# Same weapon against a 3+ save (2/3 saved) so that bypassing the save
# is worth something. Devastating Wounds turns critical wounds into
# damage that ignores the save.
REF3 = dict(REF, Sv=3)
W0 = Weapon(name="t", wtype="Ranged", A="6", skill=3, S=8, AP=0, D="1",
            count=1)
P_UNSAVED = 1 / 3
Q_CRIT = 1 / 6


def dmg3(m):
    return am.analyze_weapon(W0, REF3, {}, m)["damage"]["mean"]


close(dmg3(mech()), A * P_HIT * Q_W * P_UNSAVED, "plain vs 3+ save")
close(dmg3(mech(devastating=True)),
      A * P_HIT * ((Q_W - Q_CRIT) * P_UNSAVED + Q_CRIT), "devastating")
# Anti-VEHICLE 4+ makes 4,5,6 critical wounds (and automatic successes).
close(dmg3(mech(devastating=True, anti=[("VEHICLE", 4)])),
      A * P_HIT * ((Q_W - 3 / 6) * P_UNSAVED + 3 / 6), "anti + devastating")
# Anti never touches the critical HIT threshold.
close(dmg3(mech(anti=[("VEHICLE", 2)], sustained=1)),
      dmg3(mech(anti=[("VEHICLE", 2)], sustained=1)), "anti is wound-side")
sust_only = am.analyze_weapon(W0, REF3, {}, mech(sustained=1))["damage"]["mean"]
close(sust_only, A * (P_NORM * Q_W + P_CRIT * 2 * Q_W) * P_UNSAVED,
      "sustained is driven by crit_hit_on alone")
print("critical wounds trigger Devastating; Anti moves only that threshold")

# --- 4. a Lethal auto-wound is NOT a critical wound --------------------
# With Lethal Hits the critical hit becomes a NORMAL automatic wound, so
# Devastating can no longer fire on it: the two together are worth LESS
# than Devastating alone here, which is why 11th ed. makes Lethal Hits
# optional.
dev = dmg3(mech(devastating=True, anti=[("VEHICLE", 4)]))
dev_leth = dmg3(mech(devastating=True, anti=[("VEHICLE", 4)], lethal=True))
close(dev_leth, A * (P_NORM * ((Q_W - 3 / 6) * P_UNSAVED + 3 / 6)
                     + P_CRIT * P_UNSAVED), "lethal + devastating")
assert dev_leth < dev, (dev_leth, dev)
print("Lethal auto-wounds cannot trigger Devastating (and can cost damage)")

print("ALL CRITICAL-TRIGGER TESTS PASS")
