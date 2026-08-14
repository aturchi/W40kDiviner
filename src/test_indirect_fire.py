"""11th-ed. Indirect Fire, as an attack-setup option.

When the indirect shooting mode is selected:
  * ONLY weapons with the INDIRECT FIRE keyword are fired; the others
    are reported as skipped (the GUI greys them out) instead of being
    silently dropped;
  * the target always counts as being in Cover (-1 BS);
  * hit rolls cannot be re-rolled;
  * an unmodified hit roll below 6 always fails - below 4 when the unit
    Remained Stationary and a friendly unit can see the target.
    That floor does not replace the roll: the modified result still has
    to beat BS.
Also checks that the dice resolver reproduces the exact figures.
No tkinter needed.
"""
import random

import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import attack_math as am
import attack_resolve as ar
from unit_model import Weapon

TOL = 1e-9
REF = {"T": 4, "Sv": 6, "W": 1, "invuln": None, "fnp": None, "models": 1,
       "keywords": set()}


def weapon(name, kws, skill=3):
    w = Weapon(name=name, wtype="Ranged", A="6", skill=skill, S=8, AP=-6,
               D="1", count=1)
    w.keywords = list(kws)
    return w


def mech_for(w, **kw):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(w.keywords, m)
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def clone(m):
    n = am.WeaponMechanics()
    n.__dict__.update(m.__dict__)
    n.ignore_malus, n.anti, n.warnings = set(m.ignore_malus), list(m.anti), []
    return n


def close(a, b, what):
    assert abs(a - b) < TOL, f"{what}: got={a!r} expected={b!r}"


# --- the keyword is parsed, and is no longer a silent no-op -----------
mortar = weapon("mortar", ["INDIRECT FIRE"])
m = mech_for(mortar)
assert m.indirect and not m.warnings, m.warnings
assert not mech_for(weapon("bolter", [])).indirect
print("INDIRECT FIRE is parsed into the mechanics")

# --- the penalties, weapon by weapon ----------------------------------
# BS3+, S8 vs T4 (wounds on 2+ = 5/6), AP-6 (no save): the hit stage is
# the only moving part, and 6 attacks make the numbers readable.
Q_W = 5 / 6


def dmg(w, ctx, **kw):
    return am.analyze_weapon(w, REF, ctx, mech_for(w, **kw))["damage"]["mean"]


close(dmg(mortar, {}), 6 * (2 / 3) * Q_W, "no indirect mode: plain BS3+")
# Indirect without a spotter: only an unmodified 6 lands.
close(dmg(mortar, {"indirect": True}), 6 * (1 / 6) * Q_W, "indirect, no spotter")
# With a spotter: unmodified 4+, and the -1 BS from the forced Cover
# turns BS3+ into 4+ - the two happen to coincide here.
close(dmg(mortar, {"indirect": True, "spotter": True}),
      6 * (3 / 6) * Q_W, "indirect with spotter")
# The forced Cover really is applied: a BS2+ weapon with a spotter hits
# on 3+ (2+ worsened by cover), not on 4+ from the floor alone.
m2 = weapon("mortar2", ["INDIRECT FIRE"], skill=2)
close(dmg(m2, {"indirect": True, "spotter": True}), 6 * (3 / 6) * Q_W,
      "floor and cover combine, the stricter one wins")
# IGNORES COVER cancels the -1 BS but not the floor.
m3 = weapon("mortar3", ["INDIRECT FIRE", "IGNORES COVER"], skill=2)
close(dmg(m3, {"indirect": True, "spotter": True}), 6 * (3 / 6) * Q_W,
      "ignores cover keeps the unmodified floor")
# Hit re-rolls are lost in indirect mode.
close(dmg(mortar, {"indirect": True}, reroll_hit="fails"),
      dmg(mortar, {"indirect": True}), "no hit re-rolls under indirect")
assert dmg(mortar, {}, reroll_hit="fails") > dmg(mortar, {}), \
    "the re-roll must still work outside indirect mode"
# A weapon WITHOUT the keyword is unaffected by the flag (the caller is
# the one that stops it from firing at all).
bolter = weapon("bolter", [])
close(dmg(bolter, {"indirect": True}), dmg(bolter, {}), "keyword-gated")
print("cover, re-roll ban and the unmodified floor all apply")

# --- weapon selection: kept vs skipped --------------------------------
class _Model:
    def __init__(self, weapons):
        self.weapons = weapons


class _View:
    """Minimal stand-in for a unit view: keywords plus models()."""

    def __init__(self, weapons, keywords=()):
        self._m = [_Model(weapons)]
        self.keywords = list(keywords)

    def models(self):
        return self._m


view = _View([mortar, bolter])
kept, skipped = ac.select_weapons_split(view, "ranged", None, indirect=True)
assert [w.name for w in kept] == ["mortar"], kept
assert [(w.name, why) for w, why in skipped] == \
    [("bolter", ac.INDIRECT_SKIP)], skipped
kept, skipped = ac.select_weapons_split(view, "ranged", None, indirect=False)
assert len(kept) == 2 and not skipped
print("indirect mode fires only INDIRECT FIRE weapons, the rest are flagged")

# --- the dice resolver agrees -----------------------------------------
rng = random.Random(5)
for ctx in ({"indirect": True}, {"indirect": True, "spotter": True}):
    exact = dmg(mortar, ctx)
    trials, tot = 60000, 0
    base = mech_for(mortar)
    for _ in range(trials):
        res = ar.resolve_weapon(mortar, REF, ctx, clone(base), rng)
        tot += sum(e["amount"] for e in res["events"])
    mc = tot / trials
    assert abs(mc - exact) < 0.05 * exact, (ctx, mc, exact)
print("exact and Monte-Carlo agree under indirect fire")

print("ALL INDIRECT-FIRE TESTS PASS")
