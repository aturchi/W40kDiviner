#!/usr/bin/env python3
"""Generate the synthetic roster used by the data-dependent tests when no
real ArmyFetcher tree is present.

The tests look units up by a fixed set of REAL role names (Captain,
Bladeguard Ancient, Bladeguard Veteran Squad, Assault Intercessor Squad,
Intercessor Squad, Ancient, and the attacker/defender names test_regress.py
uses) and rely on the leader/support relationships between them. Those
names and relationships are reproduced faithfully. Everything else --
ability names, weapon names, keywords, stat lines -- is invented
("Ability 01", "Weapon 01", ...). This is NOT real game data, only a
structurally valid, deliberately VARIED stand-in.

Coverage goal (test_regress.py exercises these): the roster spans light
infantry vs anti-infantry volume fire, armoured targets where AP matters,
a Feel-No-Pain target, multi-damage weapons against multi-wound models,
and high-Toughness vehicles/monsters taking single big hits -- plus at
least one weapon carrying each commonly-used weapon keyword (Sustained
Hits, Lethal Hits, Devastating Wounds, Blast, Torrent, Rapid Fire, Melta,
Twin-linked). Every representative attacker has both a ranged and a melee
weapon so neither phase is left untested.

Writing this as a generator (rather than hand-writing JSON) lets us
ASSERT the structural constraints the tests depend on, so the roster can
never silently drift out of spec. Run it directly to (re)write the files:

    python3 tests/make_synthetic.py

It writes tests/synthetic/{space-marines,tau-empire}.json (flat, no
ArmyFetcher subdirectory) and validates them before saving.
"""
import json
import os
import sys

import testpaths                       # puts src/ on sys.path
import unit_model as um


# --- Small builders ------------------------------------------------------

_ability_ctr = [0]
_weapon_ctr = [0]


def _ability():
    """A disabled, no-op ability with a running invented name. Disabled so
    it never perturbs the damage maths."""
    _ability_ctr[0] += 1
    return {"name": f"Ability {_ability_ctr[0]:02d}", "description": "",
            "enabled": False, "share_with_unit": False,
            "conditions": [], "effect": {"type": "special", "data": {}}}


def _abilities(n):
    return [_ability() for _ in range(n)]


def _weapon(wtype, A, skill, S, AP, D, count=1, rng=None, kws=None):
    """A minimal valid weapon with a running invented name. skill is BS for
    Ranged, WS for Melee."""
    _weapon_ctr[0] += 1
    w = {"name": f"Weapon {_weapon_ctr[0]:02d}", "type": wtype, "RNG": rng,
         "A": A, "S": S, "AP": AP, "D": D, "count": count,
         "keywords": list(kws or []), "abilities": []}
    w["BS" if wtype == "Ranged" else "WS"] = skill
    return w


def _model(name, count, T, Sv, W, weapons, invuln=None, fnp=None,
           abilities=None, kws=None):
    return {"name": name, "model_count": count,
            "M": 6, "T": T, "Sv": Sv, "W": W, "LD": 6, "OC": 1,
            "invuln": invuln, "fnp": fnp,
            "keywords": list(kws or []), "abilities": abilities or [],
            "weapons": weapons}


def _unit(name, points, models, *, keywords=None, abilities=None,
          leadership=None, support=None):
    """A unit dict. The unit name is also stored as a keyword so
    leadership/support lists can target it by whole-name match (the
    Space-Marine datasheet convention, see unit_model)."""
    u = {"name": name, "profile_name": name, "points": points,
         "keywords": list(keywords or []) + [name],
         "abilities": abilities or [],
         "leader_effects": [], "models": models}
    if leadership is not None:
        u["leadership"] = leadership
    if support is not None:
        u["support"] = support
    return u


# Names referenced in leadership/support lists.
AIS = "Assault Intercessor Squad"
BVS = "Bladeguard Veteran Squad"
ISQ = "Intercessor Squad"


def build_space_marines():
    units = []

    # (1) Light infantry with ranged + melee. Target of Captain lead.
    #     Rapid Fire exercises the extra-attacks-at-half-range path.
    units.append(_unit(
        AIS, 75,
        [_model("Body A", 5, 4, 3, 2,
                [_weapon("Ranged", 2, 3, 4, -1, 1, count=5, rng=24,
                         kws=["Rapid Fire 1"]),
                 _weapon("Melee", 3, 3, 4, -1, 1, count=5)],
                kws=[])],
        abilities=_abilities(2)))

    # (2) Elite multi-wound infantry with an invuln + a multi-damage
    #     Cleave weapon. Base unit for leader/support tests.
    units.append(_unit(
        BVS, 90,
        [_model("Body B", 3, 4, 3, 3,
                [_weapon("Ranged", 1, 3, 4, 0, 1, count=3, rng=12),
                 _weapon("Melee", 4, 3, 5, -2, 2, count=3,
                         kws=["Cleave 1"])],
                invuln=4)],
        abilities=_abilities(2)))

    # (3) Objective infantry with Sustained Hits ranged fire. Defender in
    #     several regress pairs; also a lead target.
    units.append(_unit(
        ISQ, 80,
        [_model("Body C", 5, 4, 3, 2,
                [_weapon("Ranged", 2, 3, 4, -1, 1, count=5, rng=30,
                         kws=["Sustained Hits 1"]),
                 _weapon("Melee", 2, 3, 4, 0, 1, count=5)],
                kws=[])],
        abilities=_abilities(1)))

    # (4) Heavily armoured, Feel-No-Pain, multi-wound elites -- a hard
    #     target where AP, multi-damage and FNP all bite (regress
    #     defender).
    units.append(_unit(
        "Terminator Squad", 185,
        [_model("Body D", 5, 5, 2, 3,
                [_weapon("Ranged", 2, 3, 4, -1, 2, count=5, rng=24,
                         kws=["Devastating Wounds"]),
                 _weapon("Melee", 3, 3, 8, -2, 2, count=5)],
                invuln=4, fnp=5)],
        abilities=_abilities(2)))

    # (5) Walker with a big Lethal-Hits ranged gun and a melee fist.
    units.append(_unit(
        "Redemptor Dreadnought", 210,
        [_model("Redemptor Hull", 1, 9, 2, 12,
                [_weapon("Ranged", 6, 3, 8, -3, 3, count=1, rng=48,
                         kws=["Lethal Hits"]),
                 _weapon("Melee", 5, 3, 12, -2, 3, count=1)],
                invuln=5)],
        abilities=_abilities(1)))

    # (6) Anti-armour walker: Melta ranged gun (bonus at half range) plus a
    #     Twin-linked backup and a melee.
    units.append(_unit(
        "Ballistus Dreadnought", 150,
        [_model("Ballistus Hull", 1, 9, 2, 10,
                [_weapon("Ranged", 3, 3, 12, -4, 6, count=1, rng=48,
                         kws=["Melta 2"]),
                 _weapon("Ranged", 6, 3, 5, -1, 1, count=1, rng=36,
                         kws=["Twin-linked"]),
                 _weapon("Melee", 3, 3, 6, -1, 2, count=1)],
                invuln=5)],
        abilities=_abilities(1)))

    # --- Leader: leads AIS, BVS and ISQ. ---
    units.append(_unit(
        "Captain", 80,
        [_model("Captain Model", 1, 4, 3, 5,
                [_weapon("Ranged", 4, 2, 4, -1, 1, count=1, rng=18),
                 _weapon("Melee", 6, 2, 6, -2, 2, count=1)],
                invuln=4)],
        abilities=_abilities(2),
        leadership=[AIS, BVS, ISQ]))

    # --- Support: Bladeguard Ancient supports BVS and AIS. One model group
    #     only (test_leadercore masks the support group by its index). ---
    units.append(_unit(
        "Bladeguard Ancient", 65,
        [_model("Ancient Model", 1, 4, 3, 4,
                [_weapon("Melee", 4, 3, 5, -2, 2, count=1)],
                invuln=4)],
        abilities=_abilities(1),
        support=[BVS, AIS]))

    # --- A second support named exactly "Ancient" (test_dialog_logic looks
    #     it up by that name). Supports BVS and AIS. ---
    units.append(_unit(
        "Ancient", 60,
        [_model("Ancient Base", 1, 4, 3, 4,
                [_weapon("Melee", 3, 3, 4, -1, 1, count=1)])],
        abilities=_abilities(1),
        support=[BVS, AIS]))

    return {"format": "w40k-sim/6",
            "armies": [{"name": "Test Marines", "units": units}]}


def build_tau():
    units = []

    # Monster with an invuln and Blast ranged fire; melee backup.
    units.append(_unit(
        "Riptide Battlesuit", 180,
        [_model("Riptide Chassis", 1, 6, 2, 14,
                [_weapon("Ranged", 6, 4, 8, -2, 3, count=1, rng=36,
                         kws=["Blast"]),
                 _weapon("Melee", 3, 4, 6, -1, 2, count=1)],
                invuln=4)],
        abilities=_abilities(1)))

    # Anti-armour vehicle: one big high-Damage shot + a Torrent secondary.
    units.append(_unit(
        "Hammerhead Gunship", 160,
        [_model("Hammerhead Hull", 1, 9, 3, 13,
                [_weapon("Ranged", 1, 4, 10, -4, 6, count=1, rng=48),
                 _weapon("Ranged", 6, 4, 5, 0, 1, count=1, rng=18,
                         kws=["Torrent"]),
                 _weapon("Melee", 3, 4, 6, 0, 1, count=1)],
                invuln=5)],
        abilities=_abilities(1)))

    # Battlesuit: high-Strength melta-like ranged gun + melee.
    units.append(_unit(
        "Crisis Sunforge", 150,
        [_model("Crisis Chassis", 3, 5, 3, 5,
                [_weapon("Ranged", 2, 4, 9, -3, 2, count=3, rng=18,
                         kws=["Melta 1"]),
                 _weapon("Melee", 2, 4, 5, 0, 1, count=3)],
                invuln=4)],
        abilities=_abilities(1)))

    return {"format": "w40k-sim/6",
            "armies": [{"name": "Test Tau", "units": units}]}


# --- Validation: assert the structural constraints the tests rely on -----

def validate(sm_data, tau_data):
    """Rebuild the rosters through the real engine and assert every
    relationship the data-dependent tests depend on. Raises AssertionError
    on any mismatch so a broken roster fails loudly at generation time."""
    import analyzer_core as ac

    sm = um.units_from_native(sm_data)
    by = {u.name: u for u in sm}

    for nm in ["Captain", "Bladeguard Ancient", "Ancient", BVS, AIS, ISQ,
               "Terminator Squad", "Redemptor Dreadnought",
               "Ballistus Dreadnought"]:
        assert nm in by, f"missing SM unit {nm!r}"

    cap, anc, anc2 = by["Captain"], by["Bladeguard Ancient"], by["Ancient"]
    bvs, ais, isq = by[BVS], by[AIS], by[ISQ]

    # Leadership: Captain leads AIS, BVS, ISQ.
    assert ais.can_attach(cap), "Captain must lead Assault Intercessor Squad"
    assert bvs.can_attach(cap), "Captain must lead Bladeguard Veteran Squad"
    assert isq.can_attach(cap), "Captain must lead Intercessor Squad"

    # Support: Bladeguard Ancient supports BVS; 'Ancient' supports something.
    assert bvs.can_support(anc), "Ancient must support Bladeguard Veterans"
    assert any(t.can_support(anc2) for t in sm), \
        "'Ancient' must support some unit"

    # test_leadercore masks the support model group by GLOBAL index n_unit;
    # the support must have exactly one model group (checked on the native
    # dict, as the test does).
    anc_native = next(u for u in sm_data["armies"][0]["units"]
                      if u["name"] == "Bladeguard Ancient")
    assert len(anc_native["models"]) == 1, \
        "support needs exactly one model group"

    # test_regress.py pairs must resolve to >0 mean damage on at least one weapon
    # (sanity that the varied weapons/keywords are all valid), across the
    # ranged and melee phases.
    tau = um.units_from_native(tau_data)
    tby = {u.name: u for u in tau}
    for nm in ["Riptide Battlesuit", "Hammerhead Gunship", "Crisis Sunforge"]:
        assert nm in tby, f"missing tau unit {nm!r}"

    def _phase_damage(att, dfn, mode):
        aview, dview = ac.build_views(att, dfn, {}, {})
        ref = ac.reference_options(dview)[0][1]
        # Melee needs an explicit main melee weapon name (run_analysis
        # selects none otherwise); pick the first available.
        mname = None
        if mode == "melee":
            choices = ac.melee_choices(aview)
            mname = choices[0] if choices else None
        res = ac.run_analysis(aview, dview, ref, {}, mode, melee_name=mname)
        return sum(r["damage"]["mean"] for r in res["weapons"])

    pairs = [(by["Intercessor Squad"], by["Terminator Squad"]),
             (by["Redemptor Dreadnought"], tby["Riptide Battlesuit"]),
             (tby["Hammerhead Gunship"], by["Intercessor Squad"]),
             (by["Ballistus Dreadnought"], tby["Crisis Sunforge"])]
    for att, dfn in pairs:
        r = _phase_damage(att, dfn, "ranged")
        m = _phase_damage(att, dfn, "melee")
        assert r > 0, f"{att.name} vs {dfn.name}: zero ranged damage"
        assert m > 0, f"{att.name} vs {dfn.name}: zero melee damage"

    # No weapon keyword should be flagged unsupported by the engine.
    import attack_math as am
    for u in sm + tau:
        for model in u.models():
            for w in model.weapons:
                mech = am.WeaponMechanics()
                am.parse_weapon_keywords(w.keywords, mech)
                assert not mech.warnings, \
                    f"{u.name}/{w.name}: {mech.warnings}"

    return True


def main():
    sm = build_space_marines()
    tau = build_tau()
    validate(sm, tau)

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "synthetic")
    os.makedirs(out_dir, exist_ok=True)
    for fname, data in [("space-marines.json", sm),
                        ("tau-empire.json", tau)]:
        path = os.path.join(out_dir, fname)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        print(f"wrote {path}")
    print("synthetic roster validated OK")


if __name__ == "__main__":
    sys.exit(main())
