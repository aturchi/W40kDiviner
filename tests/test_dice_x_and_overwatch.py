"""Dice X values (11th ed.) and Overwatch.

Dice X: Rapid Fire, Sustained Hits, Melta, Blast and Cleave may carry a
dice expression instead of a number ("RAPID FIRE D3"). The value stops
being a constant and becomes a distribution, so the exact engine mixes
over it instead of adding it.

Overwatch: an attack-setup tick with the unmodified roll it needs (2..6,
6 by default). The hit lands ONLY on that unmodified result - every hit
modifier and every re-roll is discarded - while the wound roll and
everything after it are resolved normally. Torrent still hits
automatically, because it makes no hit roll at all.

Expected values are in closed form; every case is cross-checked against
the dice resolver. No tkinter needed.
"""
import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
import mc_support as mcs
from characteristics import Characteristic
from unit_model import Weapon

TOL = 1e-9


def close(a, b, what):
    assert abs(a - b) < TOL, f"{what}: got={a!r} expected={b!r}"


def mech(kws=(), **kw):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(list(kws), m)
    for k, v in kw.items():
        setattr(m, k, v)
    assert not m.warnings, m.warnings
    return m


# Always hits (BS2+ is still 5/6 because of the unmodified 1), always
# wounds, no save: the attack count and the hit stage are what move.
W = Weapon(name="w", wtype="Ranged", A="2", skill=2, S=10, AP=-6, D="1",
           count=1)
REF = {"T": 2, "Sv": 6, "W": 9, "invuln": None, "fnp": None, "models": 10,
       "keywords": set()}
# BS2+ and S10 vs T2 both come down to "the unmodified 1 always fails".
P_HIT = 5 / 6
Q_W = 5 / 6


def dmg(m, ctx=None, weapon=None):
    return am.analyze_weapon(weapon or W, REF, ctx or {},
                             m.copy())["damage"]["mean"]


# --- parsing: flat stays an int, dice become a Characteristic ---------
m = mech(["RAPID FIRE D3", "SUSTAINED HITS D3", "MELTA D6", "BLAST 2"])
assert isinstance(m.rapid_fire, Characteristic) and m.rapid_fire.is_dice()
assert isinstance(m.blast, int) and m.blast == 2, m.blast
assert am.x_text(m.rapid_fire) == "1D3", am.x_text(m.rapid_fire)
assert am.x_pmf(m.rapid_fire) == [0.0, 1 / 3, 1 / 3, 1 / 3]
# a bare keyword still means 1, and nonsense is reported not swallowed
assert mech(["RAPID FIRE"]).rapid_fire == 1
bad = am.WeaponMechanics()
am.parse_weapon_keywords(["MELTA X"], bad)
assert bad.warnings and "MELTA X" in bad.warnings[0], bad.warnings
print("dice X parses; flat X stays a plain int")

# --- RAPID FIRE D3: mean 2 extra attacks at half range ----------------
close(dmg(mech(), {"half_range": True}), 2 * P_HIT * Q_W, "no rapid fire")
close(dmg(mech(["RAPID FIRE D3"]), {"half_range": True}),
      (2 + 2) * P_HIT * Q_W, "rapid fire D3 at half range")
close(dmg(mech(["RAPID FIRE D3"]), {}), 2 * P_HIT * Q_W,
      "...only at half range")
# the whole distribution moves, not just the mean: 2+D3 attacks
pmf = am.analyze_weapon(W, REF, {"half_range": True},
                        mech(["RAPID FIRE D3"]))["attacks_pmf"]
assert [round(p, 6) for p in pmf[3:6]] == [round(1 / 3, 6)] * 3, pmf
assert sum(pmf[:3]) == 0.0, pmf
print("RAPID FIRE D3 adds a die, not its average")

# --- BLAST D3 against 10 models: one roll per group of five -----------
# 10 models = 2 groups, so 2D3 extra attacks (mean 4), not 1D3 x 2.
blast = am.analyze_weapon(W, REF, {}, mech(["BLAST D3"]))["attacks_pmf"]
close(sum(i * p for i, p in enumerate(blast)), 2 + 4, "blast D3, 2 groups")
assert len(blast) - 1 == 2 + 6, "2D3 tops out at 6 extra attacks"
print("BLAST D3 rolls once per group of five models")

# --- SUSTAINED HITS D3: mix over the number of bonus hits -------------
# BS2+ -> 1/6 of the attacks are critical (an unmodified 6), each adding
# D3 ordinary hits (mean 2).
close(dmg(mech(["SUSTAINED HITS D3"])), 2 * (P_HIT + (1 / 6) * 2) * Q_W,
      "sustained D3")
close(dmg(mech(["SUSTAINED HITS 2"])), 2 * (P_HIT + (1 / 6) * 2) * Q_W,
      "...same mean as a flat 2")
# same mean, different shape - which is the point of mixing over the die
pmf_d3 = am.analyze_weapon(W, REF, {},
                           mech(["SUSTAINED HITS D3"]))["damage_pmf"]
pmf_2 = am.analyze_weapon(W, REF, {},
                          mech(["SUSTAINED HITS 2"]))["damage_pmf"]
assert pmf_d3 != pmf_2, "a die must not collapse to its average"
print("SUSTAINED HITS D3 mixes over the die instead of averaging it")

# --- MELTA D6 at half range -------------------------------------------
close(dmg(mech(["MELTA D6"]), {"half_range": True}),
      2 * P_HIT * Q_W * (1 + 3.5), "melta D6")
close(dmg(mech(["MELTA D6"]), {}), 2 * P_HIT * Q_W, "...only at half range")
print("MELTA D6 adds a die to the damage")

# --- OVERWATCH ---------------------------------------------------------
assert am.overwatch_target({}) is None
assert am.overwatch_target({"overwatch": True}) == 6
assert am.overwatch_target({"overwatch": True, "overwatch_value": 4}) == 4
assert am.overwatch_target({"overwatch": True, "overwatch_value": 9}) == 6
assert am.overwatch_target({"overwatch": True, "overwatch_value": 1}) == 2
assert am.overwatch_target({"overwatch": True, "overwatch_value": ""}) == 6
OW = {"overwatch": True}
close(dmg(mech(), OW), 2 * (1 / 6) * Q_W, "overwatch 6+ beats BS2+")
close(dmg(mech(), {"overwatch": True, "overwatch_value": 4}),
      2 * (3 / 6) * Q_W, "overwatch 4+")
# no modifiers, no re-rolls, whatever their source
for extra, name in ((dict(hit_mod=2), "hit modifier"),
                    (dict(reroll_hit="fails"), "re-roll"),
                    (dict(twin_linked=False, reroll_hit="1"), "re-roll 1s")):
    close(dmg(mech(**extra), OW), 2 * (1 / 6) * Q_W,
          f"overwatch ignores the {name}")
close(dmg(mech(), dict(OW, cover=True)), 2 * (1 / 6) * Q_W,
      "overwatch ignores cover too (a BS modifier)")
# ...but the wound roll is untouched: S3 vs T6 wounds on 6+ (2S is not
# greater than T), and a re-roll there still works.
weak = Weapon(name="weak", wtype="Ranged", A="2", skill=2, S=3, AP=-6, D="1",
              count=1)
close(am.analyze_weapon(weak, dict(REF, T=6), OW,
                        mech())["damage"]["mean"], 2 * (1 / 6) * (1 / 6),
      "the wound roll is normal under Overwatch")
close(am.analyze_weapon(weak, dict(REF, T=6), OW,
                        mech(reroll_wound="fails"))["damage"]["mean"],
      2 * (1 / 6) * (1 / 6 + (5 / 6) * (1 / 6)),
      "...re-rolls to wound still work")
# TORRENT makes no hit roll, so it hits anyway - which is exactly what
# makes it good in Overwatch.
close(dmg(mech(["TORRENT"]), OW), 2 * Q_W, "torrent auto-hits in Overwatch")
print("Overwatch: unmodified N+ only, no modifiers, no re-rolls")

# --- the dice resolver agrees on all of it -----------------------------
for kws, ctx, name in ((["RAPID FIRE D3"], {"half_range": True}, "rapid D3"),
                       (["BLAST D3"], {}, "blast D3"),
                       (["SUSTAINED HITS D3"], {}, "sustained D3"),
                       (["MELTA D6"], {"half_range": True}, "melta D6"),
                       ([], OW, "overwatch 6"),
                       ([], {"overwatch": True, "overwatch_value": 3},
                        "overwatch 3"),
                       (["TORRENT"], OW, "torrent in overwatch")):
    ok, msg = mcs.check_weapon(name, W, REF, ctx, mech(kws))
    assert ok, msg
print("exact and Monte-Carlo agree on dice X and Overwatch")

print("ALL DICE-X / OVERWATCH TESTS PASS")
