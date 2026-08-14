"""CONVERSION and HUNTER X (11th ed.), from the datasheet keyword and
from an ability alike.

  * CONVERSION: at least half the weapon's range away, critical HITS
    come on 4+ instead of 6. Within half range nothing changes. Since a
    critical hit is also an automatic hit, the 4+ threshold raises the
    hit rate too, and it feeds Sustained/Lethal exactly like a natural 6.
  * HUNTER X: the weapon may only be fired at units carrying keyword X.
    That is a TARGETING rule, not maths: the weapon is reported as
    skipped (the GUI greys it out) instead of being resolved.

Both must work whether they come from the weapon's own keywords or from
an ability (the criticalThreshold / hunterTarget effects), and the dice
resolver must agree with the exact maths. No tkinter needed.
"""
import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import attack_math as am
import mc_support as mcs
import modifier_engine as me
from unit_model import Weapon

TOL = 1e-9


def close(a, b, what):
    assert abs(a - b) < TOL, f"{what}: got={a!r} expected={b!r}"


def weapon(name, kws=()):
    w = Weapon(name=name, wtype="Ranged", A="6", skill=3, S=8, AP=-6, D="1",
               count=1)
    w.keywords = list(kws)
    return w


def mech_for(w, effects=()):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(w.keywords, m)
    am.parse_effect_strings(list(effects), "Ranged", m, w)
    assert not m.warnings, m.warnings
    return m


REF = {"T": 4, "Sv": 6, "W": 1, "invuln": None, "fnp": None, "models": 1,
       "keywords": {"VEHICLE"}}
A, P_HIT, Q_W = 6, 2 / 3, 5 / 6      # BS3+, S8 vs T4 wounds on 2+

# --- CONVERSION: parsing, from keyword and from ability ---------------
conv = weapon("conversion beamer", ["CONVERSION"])
assert mech_for(conv).conversion
assert not mech_for(weapon("bolter")).conversion
# an ability lowering the critical HIT threshold is the same mechanic
# expressed the long way round, and was already supported
crit_ability = mech_for(weapon("bolter"), ["CRITON HIT 4"])
assert crit_ability.crit_hit_on == 4
print("CONVERSION is parsed; the generic critical-threshold ability too")


def dmg(w, ctx, effects=()):
    return am.analyze_weapon(w, REF, ctx, mech_for(w, effects))["damage"]["mean"]


# --- CONVERSION: the numbers ------------------------------------------
# Beyond half range (the flag says "within half range", so unticked =
# beyond) the critical threshold is 4+, and a critical hit is also an
# automatic hit: BS3+ already hits on 3+, so the hit rate is unchanged
# and only the CRITICAL rate moves - from 1/6 to 3/6.
close(dmg(conv, {}), A * P_HIT * Q_W, "conversion alone changes no hits")
close(dmg(conv, {"half_range": True}), A * P_HIT * Q_W, "within half range")
# ...which is visible as soon as something keys off criticals.
sust = weapon("conversion beamer", ["CONVERSION", "SUSTAINED HITS 1"])
close(dmg(sust, {}), A * ((P_HIT - 3 / 6) * Q_W + (3 / 6) * 2 * Q_W),
      "conversion feeds Sustained beyond half range")
close(dmg(sust, {"half_range": True}),
      A * ((P_HIT - 1 / 6) * Q_W + (1 / 6) * 2 * Q_W),
      "...and stops within half range")
# With a bad shooter the 4+ auto-hit does raise the hit rate itself.
bad = Weapon(name="bad", wtype="Ranged", A="6", skill=5, S=8, AP=-6, D="1",
             count=1)
bad.keywords = ["CONVERSION"]
close(am.analyze_weapon(bad, REF, {}, mech_for(bad))["damage"]["mean"],
      A * (3 / 6) * Q_W, "BS5+ hits on 4+ thanks to the critical")
print("CONVERSION: 4+ criticals beyond half range, nothing within it")

# --- HUNTER X: parsing, both spellings and from an ability ------------
for spelling in ("HUNTER-VEHICLE", "HUNTER VEHICLE", "hunter-vehicle"):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords([spelling], m)
    assert m.hunter == ["VEHICLE"] and not m.warnings, (spelling, m.hunter)
m = mech_for(weapon("krak hunter", ["HUNTER-VEHICLE"]), ["HUNTER MONSTER"])
assert m.hunter == ["VEHICLE", "MONSTER"], m.hunter
# the ability effect emits the same string the keyword parses into
ops = me._e_hunter_target({"keyword": "Vehicle"}, None)
assert ops == [("weffect", "HUNTER VEHICLE")], ops
print("HUNTER X is parsed from the keyword and from the ability alike")


# --- HUNTER X: the targeting restriction ------------------------------
class _View:
    def __init__(self, keywords=()):
        self.keywords = list(keywords)


hunter_m = mech_for(weapon("krak hunter", ["HUNTER-VEHICLE"]))
assert ac.hunter_skip_reason(hunter_m, _View(["Vehicle"])) is None, \
    "casing must not matter"
assert ac.hunter_skip_reason(hunter_m, _View(["INFANTRY"])), "must be blocked"
assert "VEHICLE" in ac.hunter_skip_reason(hunter_m, _View(["INFANTRY"]))
# several HUNTER keywords are alternatives, not a conjunction
two = mech_for(weapon("w", ["HUNTER-VEHICLE", "HUNTER-MONSTER"]))
assert ac.hunter_skip_reason(two, _View(["MONSTER"])) is None
assert ac.hunter_skip_reason(two, _View(["INFANTRY"]))
# a weapon without the keyword is never restricted
assert ac.hunter_skip_reason(mech_for(weapon("bolter")), _View([])) is None
print("HUNTER X blocks the weapon unless the target carries the keyword")

# --- both can be switched off from the attack setup -------------------
off = mech_for(weapon("w", ["CONVERSION", "HUNTER-VEHICLE"]))
am.disable_abilities(off, ["CONVERSION", "HUNTER"],
                     lambda msg: off.warnings.append(msg))
assert not off.conversion and off.hunter == [] and not off.warnings
# ...and handed out to every attack
extra = am.WeaponMechanics()
am.add_abilities(extra, ["CONVERSION"])
assert extra.conversion
print("both appear in the attack-setup ability lists")

# --- the dice resolver agrees -----------------------------------------
for w, ctx, name in ((sust, {}, "conversion beyond half"),
                     (sust, {"half_range": True}, "conversion within half"),
                     (bad, {}, "conversion on a BS5+ shooter")):
    ok, msg = mcs.check_weapon(name, w, REF, ctx, mech_for(w))
    assert ok, msg
print("exact and Monte-Carlo agree on CONVERSION")

print("ALL HUNTER / CONVERSION TESTS PASS")
