"""The audit trail (attack_math audit + src/audit.py).

An audit is only worth reading if it reports what the chain DID. So the
checks here are all of the same shape: change something, and verify the
audit changed with it - and, where the number is also available from
the analysis itself, that the two agree exactly.
"""
import testpaths                      # sets up sys.path to the engine src/
import attack_math as am
import audit as ad
from unit_model import Weapon

REF = {"T": 5, "Sv": 3, "W": 3, "invuln": None, "fnp": None,
       "models": 5, "keywords": {"VEHICLE"}}
W = Weapon(name="gun", wtype="Ranged", A="D6+3", skill=3, S=8, AP=-2,
           D="D6", count=2)


def run(kws=(), ctx=None, ref=None, effects=()):
    mech = am.WeaponMechanics()
    am.parse_weapon_keywords(list(kws), mech)
    if effects:
        am.parse_effect_strings(list(effects), "Ranged", mech, W)
    res = am.analyze_weapon(W, ref or REF, ctx or {}, mech)
    return res, res["audit"]


res, a = run()
assert a["weapon"] == "gun" and a["count"] == 2

# ---- the audit numbers ARE the chain's numbers -------------------------
assert abs(a["attacks"]["mean"] - res["attacks"]["mean"]) < 1e-12
assert a["hit"]["target"] == 3 and abs(a["hit"]["p"] - 4 / 6) < 1e-12
assert a["wound"]["target"] == 3, a["wound"]      # S8 vs T5 -> 3+
assert abs(a["wound"]["p"] - 4 / 6) < 1e-12
# Sv3+ against AP-2 saves on 5+, so it fails four times in six.
assert abs(a["save"]["p_unsaved"] - 4 / 6) < 1e-12
assert a["save"]["ap"] == -2 and a["save"]["Sv"] == 3
assert abs(a["damage"]["mean"] - 3.5) < 1e-12

# ---- cover shows up as the -1 it is ------------------------------------
_r, cov = run(ctx={"cover": True})
assert cov["hit"]["cover"] is True and cov["hit"]["target"] == 4
assert "-1 cover" in ad.text(cov)
assert "-1 cover" not in ad.text(a)
# ...and IGNORES COVER takes it away again.
_r, ic = run(["IGNORES COVER"], ctx={"cover": True})
assert ic["hit"]["target"] == 3 and ic["hit"]["cover"] is False

# ---- ANTI-X is reported where it acts: the critical wound threshold ----
_r, anti = run(["ANTI-VEHICLE 3+"])
assert anti["wound"]["crit_on"] == 3, anti["wound"]
assert "critical on 3+ (ANTI)" in ad.text(anti)
assert "ANTI-VEHICLE 3+" in anti["mechanics"]
# The same weapon against a target without the keyword: no ANTI.
_r, no_anti = run(["ANTI-VEHICLE 3+"], ref=dict(REF, keywords=set()))
assert no_anti["wound"]["crit_on"] == 6
assert "ANTI" not in ad.text(no_anti).split("Abilities")[0]

# ---- only the abilities actually in play are named ---------------------
_r, plain = run()
assert plain["mechanics"] == [], plain["mechanics"]
assert "none" in ad.text(plain).split("Abilities in play")[1]
_r, many = run(["SUSTAINED HITS 2", "LETHAL HITS", "DEVASTATING WOUNDS",
                "TWIN-LINKED"])
for name in ("SUSTAINED HITS 2", "LETHAL HITS", "DEVASTATING WOUNDS",
             "TWIN-LINKED"):
    assert name in many["mechanics"], (name, many["mechanics"])

# ---- auto-hit and auto-wound say so instead of printing a target ------
_r, torrent = run(["TORRENT"])
assert torrent["hit"]["auto"] and torrent["hit"]["p"] == 1.0
assert "automatic" in ad.text(torrent)

# ---- the invulnerable save is shown alongside the armour --------------
_r, inv = run(ref=dict(REF, invuln=4))
line = [v for k, v in ad.lines(inv) if k == "Save"][0]
assert "armour 5+" in line and "invulnerable 4+" in line
assert "best of the two" in line
# 4+ invuln beats a 5+ armour save, so failure drops to 50%.
assert abs(inv["save"]["p_unsaved"] - 0.5) < 1e-12

# ---- Feel No Pain, granted or native ----------------------------------
_r, fnp = run(ref=dict(REF, fnp=5))
assert fnp["fnp"]["value"] == 5 and "5+" in dict(ad.lines(fnp))["Feel No Pain"]
assert dict(ad.lines(a))["Feel No Pain"] == "none"

# ---- a flat characteristic is not dressed up as a roll ----------------
flat = Weapon(name="flat", wtype="Ranged", A="4", skill=3, S=8, AP=0,
              D="1", count=1)
mech = am.WeaponMechanics()
fa = am.analyze_weapon(flat, REF, {}, mech)["audit"]
assert dict(ad.lines(fa))["Attacks"] == "4 attacks", ad.lines(fa)

# ---- indirect fire: the unmodified floor is stated, not implied -------
mort = Weapon(name="mortar", wtype="Ranged", A="D6", skill=4, S=5, AP=-1,
              D="1", count=1)
mech = am.WeaponMechanics()
am.parse_weapon_keywords(["INDIRECT FIRE"], mech)
ind = am.analyze_weapon(mort, REF, {"indirect": True}, mech)["audit"]
assert ind["hit"]["unmod_min"] == 6, ind["hit"]
hit_line = dict(ad.lines(ind))["Hit"]
assert "unmodified 6+ floor" in hit_line, hit_line
assert "-1 cover" in hit_line, "indirect fire also carries the cover penalty"
# A spotter softens the floor to 4+.
mech2 = am.WeaponMechanics()
am.parse_weapon_keywords(["INDIRECT FIRE"], mech2)
spot = am.analyze_weapon(mort, REF, {"indirect": True, "spotter": True},
                         mech2)["audit"]
assert spot["hit"]["unmod_min"] == 4
assert spot["hit"]["p"] > ind["hit"]["p"]


# ---- what could not be modelled still gets through --------------------
mech = am.WeaponMechanics()
mech.warnings.append("something exotic")
warned = am.analyze_weapon(W, REF, {}, mech)["audit"]
assert "Not modelled" in dict(ad.lines(warned))

# ---- every line is one label plus one value, no stray formatting ------
for label, value in ad.lines(many):
    assert label and value and "\n" not in value, (label, value)
block = ad.text(many)
assert len(block.split("\n")) == len(ad.lines(many))

print("audit: OK")
