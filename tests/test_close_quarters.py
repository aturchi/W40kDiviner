"""Close-quarters shooting (11th ed.): firing at the enemy unit you are
engaged with.

  * a MONSTER or VEHICLE attacker fires everything, but takes -1 to hit
    with every weapon that is NOT a CLOSE-QUARTERS one, and may never
    fire a BLAST weapon at an engaged unit;
  * any other attacker may only fire its CLOSE-QUARTERS weapons, and
    takes no penalty (PISTOL, the 10th-ed. name of the same keyword, is
    accepted as a synonym so older rosters behave identically);
  * the same restriction runs the other way: a non-MONSTER/VEHICLE model
    must choose between its CLOSE-QUARTERS weapons and its other ranged
    weapons, so in the plain 'ranged' mode its CLOSE-QUARTERS weapons
    stay silent - MONSTER/VEHICLE models fire everything;
  * keyword matching is case-insensitive everywhere, because rosters
    spell the same keyword in different cases;
  * weapons that cannot fire are reported with a reason (the GUI greys
    them out) rather than silently dropped.

Whether the unit is actually engaged is the user's call - the program
cannot see the table - so the mode is simply selected in the attack
setup. No tkinter needed.
"""
import testpaths                      # sets up sys.path to the engine src/
from viewstub import View as _View     # the shared attacker-view stub
import analyzer_core as ac
import attack_math as am
import mc_support as mcs
from unit_model import Weapon

TOL = 1e-9
REF = {"T": 4, "Sv": 6, "W": 9, "invuln": None, "fnp": None, "models": 1,
       "keywords": set()}


def close(a, b, what):
    assert abs(a - b) < TOL, f"{what}: got={a!r} expected={b!r}"


def weapon(name, kws=()):
    w = Weapon(name=name, wtype="Ranged", A="6", skill=3, S=8, AP=-6, D="1",
               count=1)
    w.keywords = list(kws)
    return w


bolter = weapon("bolter")
pistol = weapon("plasma pistol", ["CLOSE-QUARTERS"])
mortar = weapon("heavy mortar", ["BLAST"])
cq_blast = weapon("close blast", ["CLOSE-QUARTERS", "BLAST"])

# --- the keyword is parsed (all spellings, PISTOL included) -----------
for spelling in ("CLOSE-QUARTERS", "CLOSE QUARTERS", "PISTOL"):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords([spelling], m)
    assert m.close_quarters and not m.warnings, (spelling, m.warnings)
assert not am.WeaponMechanics().close_quarters
print("CLOSE-QUARTERS is parsed into the mechanics")

# --- who counts as a big model ----------------------------------------
assert ac.close_quarters_attacker(_View([], ["INFANTRY", "VEHICLE"]))
assert ac.close_quarters_attacker(_View([], ["MONSTER"]))
assert not ac.close_quarters_attacker(_View([], ["INFANTRY", "CHARACTER"]))
print("MONSTER and VEHICLE attackers take the permissive branch")

# --- weapon selection, MONSTER/VEHICLE --------------------------------
big = _View([bolter, pistol, mortar, cq_blast], ["VEHICLE"])
kept, skipped = ac.select_weapons_split(big, "close_quarters")
assert [w.name for w in kept] == ["bolter", "plasma pistol"], kept
assert [(w.name, why) for w, why in skipped] == \
    [("heavy mortar", ac.CQ_BLAST_SKIP),
     ("close blast", ac.CQ_BLAST_SKIP)], skipped
print("a VEHICLE fires everything but BLAST at an engaged unit")

# --- weapon selection, everyone else ----------------------------------
small = _View([bolter, pistol, mortar, cq_blast], ["INFANTRY"])
kept, skipped = ac.select_weapons_split(small, "close_quarters")
assert [w.name for w in kept] == ["plasma pistol", "close blast"], kept
assert [(w.name, why) for w, why in skipped] == \
    [("bolter", ac.CQ_NOT_CQ_SKIP),
     ("heavy mortar", ac.CQ_NOT_CQ_SKIP)], skipped
print("everyone else fires CLOSE-QUARTERS weapons only")

# --- the mirror rule in the plain ranged mode -------------------------
# A non-MONSTER/VEHICLE unit picks one group or the other, so its
# CLOSE-QUARTERS weapons do not fire in the ranged mode...
kept, skipped = ac.select_weapons_split(small, "ranged")
assert [w.name for w in kept] == ["bolter", "heavy mortar"], kept
assert [(w.name, why) for w, why in skipped] == \
    [("plasma pistol", ac.CQ_ONLY_SKIP),
     ("close blast", ac.CQ_ONLY_SKIP)], skipped
# ...while a MONSTER/VEHICLE fires the lot
kept, skipped = ac.select_weapons_split(big, "ranged")
assert len(kept) == 4 and not skipped, (kept, skipped)
print("CLOSE-QUARTERS weapons fire in the ranged mode only for big models")

# --- a model with NOTHING but CLOSE-QUARTERS weapons ------------------
# The pistol rule is a choice - "either its CLOSE-QUARTERS weapons or
# all of its other ranged weapons" - and a model that has no other
# ranged weapon has no choice to make. Holding its pistol back in the
# plain ranged mode silenced it altogether, which is not a reading the
# rule supports.
only_cq = _View([pistol], ["INFANTRY"])
kept, skipped = ac.select_weapons_split(only_cq, "ranged")
assert [w.name for w in kept] == ["plasma pistol"], [w.name for w in kept]
assert not skipped, skipped
# ...and it still fires in close quarters, as it always did.
kept, skipped = ac.select_weapons_split(only_cq, "close_quarters")
assert [w.name for w in kept] == ["plasma pistol"] and not skipped
# A MELEE weapon is not an alternative ranged weapon, so it does not
# restore the choice and the pistol still fires.
blade = Weapon(name="blade", wtype="Melee", A="3", skill=3, S=5, AP=-1,
               D="1", count=1)
blade.keywords = []
kept, skipped = ac.select_weapons_split(_View([pistol, blade],
                                              ["INFANTRY"]), "ranged")
assert [w.name for w in kept] == ["plasma pistol"], [w.name for w in kept]
assert not skipped, skipped
# INVERSE: give the same model ONE other ranged weapon and the choice
# is back, so the pistol is held out again. This is the pair that shows
# the new branch is doing work rather than switching the rule off.
kept, skipped = ac.select_weapons_split(_View([pistol, bolter],
                                              ["INFANTRY"]), "ranged")
assert [w.name for w in kept] == ["bolter"], [w.name for w in kept]
assert [(w.name, why) for w, why in skipped] == \
    [("plasma pistol", ac.CQ_ONLY_SKIP)], skipped
# The choice is per MODEL, not per unit: a trooper with only a pistol
# fires it while the one beside it, which also carries a bolter, does
# not.
split = _View([], ["INFANTRY"], per_model=[
    ([pistol], ["INFANTRY"]),
    ([weapon("bolter b"), weapon("pistol b", ["PISTOL"])], ["INFANTRY"])])
kept, skipped = ac.select_weapons_split(split, "ranged")
assert [w.name for w in kept] == ["plasma pistol", "bolter b"], \
    [w.name for w in kept]
assert [(w.name, why) for w, why in skipped] == \
    [("pistol b", ac.CQ_ONLY_SKIP)], skipped
print("a model armed only with CLOSE-QUARTERS weapons still shoots")

# --- an attached unit is not one big model ----------------------------
# 10.06 is written per MODEL, and an attached unit carries the UNION of
# its parts' keywords (Unit._attach). A MONSTER Leader must therefore
# NOT license the INFANTRY troopers beside it to fire their bolters at
# the unit they are engaged with. Reading aview.keywords cannot tell
# this apart from a unit that is MONSTER throughout.
trooper_gun, trooper_pistol = weapon("bolter"), weapon("bolt pistol",
                                                       ["PISTOL"])
boss_gun, boss_blast = weapon("boss gun"), weapon("boss blast", ["BLAST"])
attached = _View([], ["INFANTRY", "MONSTER", "CHARACTER"], per_model=[
    ([trooper_gun, trooper_pistol], ["INFANTRY"]),
    ([boss_gun, boss_blast], ["MONSTER", "CHARACTER"])])
# INVERSE: the union DOES say MONSTER, so a union reading would keep
# the trooper's bolter here. That is the answer this section rules out.
assert {k.upper() for k in attached.keywords} & ac.CQ_KEYWORDS, \
    "the fixture must carry MONSTER at unit level"
kept, skipped = ac.select_weapons_split(attached, "close_quarters")
assert [w.name for w in kept] == ["bolt pistol", "boss gun"], \
    [w.name for w in kept]
assert [(w.name, why) for w, why in skipped] == \
    [("bolter", ac.CQ_NOT_CQ_SKIP),
     ("boss blast", ac.CQ_BLAST_SKIP)], skipped
# ...and in the plain ranged mode the trooper still holds its pistol
# back while the MONSTER Leader fires everything it has.
kept, skipped = ac.select_weapons_split(attached, "ranged")
assert [w.name for w in kept] == ["bolter", "boss gun", "boss blast"], \
    [w.name for w in kept]
assert [(w.name, why) for w, why in skipped] == \
    [("bolt pistol", ac.CQ_ONLY_SKIP)], skipped
# The unit-wide flag stays true - it is only the -1 on the hit roll,
# and a weapon that is not CLOSE-QUARTERS can now only have survived
# the selection if its own model is a MONSTER/VEHICLE.
assert ac.close_quarters_attacker(attached)
# The mirror case: an INFANTRY Leader on a MONSTER squad. The Leader
# fires its pistol only, the monsters fire everything.
mirror = _View([], ["INFANTRY", "MONSTER", "CHARACTER"], per_model=[
    ([boss_gun], ["MONSTER"]),
    ([trooper_gun, trooper_pistol], ["INFANTRY", "CHARACTER"])])
kept, skipped = ac.select_weapons_split(mirror, "close_quarters")
assert [w.name for w in kept] == ["boss gun", "bolt pistol"], \
    [w.name for w in kept]
assert [(w.name, why) for w, why in skipped] == \
    [("bolter", ac.CQ_NOT_CQ_SKIP)], skipped
print("close quarters is decided per model, not on the merged unit")

# --- PISTOL is the same keyword under its old name --------------------
old_pistol = weapon("bolt pistol", ["PISTOL"])
legacy = _View([bolter, old_pistol], ["INFANTRY"])
kept, skipped = ac.select_weapons_split(legacy, "close_quarters")
assert [w.name for w in kept] == ["bolt pistol"], kept
assert [(w.name, why) for w, why in skipped] == \
    [("bolter", ac.CQ_NOT_CQ_SKIP)], skipped
# ...and in the ranged mode it is held back exactly like one
kept, skipped = ac.select_weapons_split(legacy, "ranged")
assert [w.name for w in kept] == ["bolter"], kept
assert [(w.name, why) for w, why in skipped] == \
    [("bolt pistol", ac.CQ_ONLY_SKIP)], skipped
print("PISTOL behaves exactly like CLOSE-QUARTERS")

# --- casing never matters ---------------------------------------------
mixed = _View([weapon("bolter"), weapon("hand cannon", ["pistol"]),
               weapon("shell", ["Blast"])], ["Vehicle"])
assert ac.close_quarters_attacker(mixed), "lower/mixed-case VEHICLE"
kept, skipped = ac.select_weapons_split(mixed, "close_quarters")
assert [w.name for w in kept] == ["bolter", "hand cannon"], kept
assert [(w.name, why) for w, why in skipped] == \
    [("shell", ac.CQ_BLAST_SKIP)], skipped
m = am.WeaponMechanics()
am.parse_weapon_keywords(["Lethal Hits", "sustained hits 2", "Anti-Vehicle 4+"],
                         m)
assert m.lethal and m.sustained == 2 and not m.warnings, m.warnings
# ...including the ANTI target keyword against the defender's own casing
# ...including the ANTI target keyword against the defender's own casing.
# A weak weapon into a tough target wounds on 6s, so Anti-Vehicle 3+ has
# something to show: it must fire on {'Vehicle'} just as on {'VEHICLE'}.
w_anti = Weapon(name="pea shooter", wtype="Ranged", A="6", skill=3, S=3,
                AP=-6, D="1", count=1)
w_anti.keywords = ["Anti-Vehicle 3+"]
tough = dict(REF, T=8)
m2 = am.WeaponMechanics()
am.parse_weapon_keywords(w_anti.keywords, m2)
assert m2.anti == [("VEHICLE", 3)], m2.anti
plain = am.analyze_weapon(w_anti, tough, {}, m2.copy())["damage"]["mean"]
for spelling in ("Vehicle", "VEHICLE", "vehicle"):
    hit = am.analyze_weapon(w_anti, dict(tough, keywords={spelling}), {},
                            m2.copy())["damage"]["mean"]
    assert hit > plain, (spelling, hit, plain)
print("keyword matching is case-insensitive")

# a setKeyword ability granting the keyword must land on the spelling
# the maths looks for, under either name
import modifier_engine as me
for key in ("closeQuarters", "pistol", "lethalHits"):
    ops = me._e_set_keyword({"target": "weapon", "operation": "add",
                             "keyword": key}, None)
    added = ops[0][3]
    m = am.WeaponMechanics()
    am.parse_weapon_keywords([added], m)
    assert not m.warnings, (key, added, m.warnings)
print("setKeyword lands on the spelling the maths looks for")

# --- the -1 to hit, and who is exempt ---------------------------------
# 6 attacks, BS3+ (2/3), S8 vs T4 wounds on 2+ (5/6), no save.
A, Q_W = 6, 5 / 6


def dmg(w, ctx):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(w.keywords, m)
    return am.analyze_weapon(w, REF, ctx, m)["damage"]["mean"]


PEN = {"close_quarters_penalty": True}
close(dmg(bolter, {}), A * (2 / 3) * Q_W, "no penalty outside the mode")
close(dmg(bolter, PEN), A * (1 / 2) * Q_W, "-1 to hit on a normal weapon")
close(dmg(pistol, PEN), A * (2 / 3) * Q_W, "CLOSE-QUARTERS is exempt")
close(dmg(weapon("bolt pistol", ["PISTOL"]), PEN), A * (2 / 3) * Q_W,
      "PISTOL is exempt too")
close(dmg(weapon("hand cannon", ["close quarters"]), PEN), A * (2 / 3) * Q_W,
      "...whatever the casing or the spelling")
# and end to end: a VEHICLE in close quarters penalises the bolter but
# not its CLOSE-QUARTERS weapon, both in the same volley
vehicle = _View([bolter, pistol], ["Vehicle"])
kept, skipped = ac.select_weapons_split(vehicle, "close_quarters")
assert [w.name for w in kept] == ["bolter", "plasma pistol"] and not skipped
per_weapon = {}
for w in kept:
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(w.keywords, m)
    per_weapon[w.name] = am.analyze_weapon(w, REF, PEN, m)["damage"]["mean"]
close(per_weapon["bolter"], A * (1 / 2) * Q_W, "vehicle bolter takes -1")
close(per_weapon["plasma pistol"], A * (2 / 3) * Q_W,
      "vehicle CLOSE-QUARTERS weapon does not")
# it is a ROLL modifier, so it is capped together with the others
m = am.WeaponMechanics()
m.hit_mod = -1
close(am.analyze_weapon(bolter, REF, PEN, m.copy())["damage"]["mean"],
      A * (1 / 2) * Q_W, "the -1 is a roll modifier and caps with the rest")
print("the close-quarters -1 hits everything except CLOSE-QUARTERS weapons")

# --- the dice resolver agrees -----------------------------------------
# Statistical tolerance from mc_support (SIGMA standard errors on the
# mean and on the whole distribution), not a hand-picked percentage.
for w in (bolter, pistol):
    base = am.WeaponMechanics()
    am.parse_weapon_keywords(w.keywords, base)
    ok, msg = mcs.check_weapon(f"close quarters {w.name}", w, REF, PEN, base)
    assert ok, msg
print("exact and Monte-Carlo agree under close quarters")

print("ALL CLOSE-QUARTERS TESTS PASS")
