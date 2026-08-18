#!/usr/bin/env python3
"""Generate the synthetic roster used by the data-dependent tests when no
real ArmyFetcher tree is present.

The tests look units up by a fixed set of REAL role names (Captain,
Bladeguard Ancient, Bladeguard Veteran Squad, Assault Intercessor Squad,
Intercessor Squad, Ancient, and the attacker/defender names regress.py
uses) and rely on the leader/support relationships between them. Those
names and relationships are reproduced faithfully. Everything else --
ability names, weapon names, keywords, stat lines -- is invented
("Ability 01", "Weapon 01", ...). This is NOT real game data, only a
structurally valid, deliberately VARIED stand-in.

Coverage goal (regress.py exercises these): the roster spans light
infantry vs anti-infantry volume fire, armoured targets where AP matters,
a Feel-No-Pain target, multi-damage weapons against multi-wound models,
and high-Toughness vehicles/monsters taking single big hits -- plus at
least one weapon carrying each commonly-used weapon keyword (Sustained
Hits, Lethal Hits, Devastating Wounds, Blast, Torrent, Rapid Fire, Melta,
Twin-linked, Indirect Fire, Pistol, Hazardous). Every representative
attacker has both a ranged and a melee weapon so neither phase is left
untested.

ABILITIES: the roster also carries WORKING abilities -- one per delicate
effect type (see regress_probes.CRITICAL_EFFECTS) and spanning the
condition kinds the real rosters use (role, attack type, keywords,
charged, stationary, crit, psychic, objective, leader attached). Without
them the synthetic digest could not exercise the ability interpreter at
all, which is most of what the curated rosters put under test. The
inert "Ability NN" placeholders are kept alongside: a disabled ability
must stay disabled, and that is worth pinning too.

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
import condition_specs as cs
import effect_specs as es


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


def _cond(ctype, **data):
    """A condition of the given type with its spec defaults, overridden
    by *data*. CHOICE fields take a bare key here and are expanded to the
    {'title', 'key'} pair the format uses."""
    cond = cs.new_condition(ctype)
    for key, value in data.items():
        current = cond["data"].get(key)
        if isinstance(current, dict) and not isinstance(value, dict):
            cond["data"][key] = {"title": str(value), "key": value}
        else:
            cond["data"][key] = value
    return cond


def _effect(etype, **data):
    """An effect of the given type with its spec defaults, overridden by
    *data* (same CHOICE expansion as _cond)."""
    eff = es.new_effect(etype)
    for key, value in data.items():
        current = eff["data"].get(key)
        if isinstance(current, dict) and not isinstance(value, dict):
            eff["data"][key] = {"title": str(value), "key": value}
        else:
            eff["data"][key] = value
    return eff


def _live(name, effect, conditions, share=False):
    """An ENABLED ability: this is what the regression digest probes."""
    return {"name": name, "description": "", "enabled": True,
            "share_with_unit": share, "conditions": list(conditions),
            "effect": effect}


# Conditions used often enough to deserve a shorthand.
def _attacker():
    return _cond("profileRole", profileRole="Attacker")


def _defender():
    return _cond("profileRole", profileRole="Defender")


def _ranged():
    return _cond("attackType", attackType="Ranged")


def _melee():
    return _cond("attackType", attackType="Melee")


def _weapon(wtype, A, skill, S, AP, D, count=1, rng=None, kws=None,
            name=None):
    """A minimal valid weapon with a running invented name. skill is BS for
    Ranged, WS for Melee. 'name' overrides the running name, which the
    two-profile weapons (standard / supercharge) need: test_hazardous
    asserts every HAZARDOUS weapon has a non-HAZARDOUS twin sharing its
    base name."""
    _weapon_ctr[0] += 1
    w = {"name": name or f"Weapon {_weapon_ctr[0]:02d}", "type": wtype,
         "RNG": rng,
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
          leadership=None, support=None, leader_effects=None):
    """A unit dict. The unit name is also stored as a keyword so
    leadership/support lists can target it by whole-name match (the
    Space-Marine datasheet convention, see unit_model)."""
    u = {"name": name, "profile_name": name, "points": points,
         "keywords": list(keywords or []) + [name],
         "abilities": abilities or [],
         "leader_effects": leader_effects or [], "models": models}
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
    #     Ability: a wound re-roll gated on the CHARGE, i.e. a melee-only
    #     ability that must stay off in the ranged phase.
    units.append(_unit(
        AIS, 75,
        [_model("Body A", 5, 4, 3, 2,
                [_weapon("Ranged", 2, 3, 4, -1, 1, count=5, rng=24,
                         kws=["Rapid Fire 1"]),
                 _weapon("Melee", 3, 3, 4, -1, 1, count=5)],
                kws=[])],
        abilities=_abilities(2) + [
            _live("Charge Fury",
                  _effect("reRoll", application="woundRoll",
                          resultToReRoll="allPossibleFailures",
                          limit="none"),
                  [_attacker(), _melee(), _cond("attackerCharged")])]))

    # (2) Elite multi-wound infantry with an invuln + a multi-damage
    #     Cleave weapon. Base unit for leader/support tests.
    #     Ability: extra WOUNDS in melee (the other count branch of
    #     generateExtras; the bonus wounds are normal, never critical).
    #     Deliberately ATTACKER-side only: this is the defender
    #     test_manual_modifiers uses, and a granted invulnerable save
    #     better than the modified armour save would make a save
    #     modifier a no-op there. invulnSave is covered elsewhere.
    units.append(_unit(
        BVS, 90,
        [_model("Body B", 3, 4, 3, 3,
                [_weapon("Ranged", 1, 3, 4, 0, 1, count=3, rng=12),
                 _weapon("Melee", 4, 3, 5, -2, 2, count=3,
                         kws=["Cleave 1"])],
                invuln=4)],
        abilities=_abilities(2) + [
            _live("Precision Strikes",
                  _effect("generateExtras", option="extraWounds",
                          extrasValue="1"),
                  [_attacker(), _melee()])]))

    # (3) Objective infantry with Sustained Hits ranged fire. Defender in
    #     several regress pairs; also a lead target. Second ranged weapon
    #     carries INDIRECT FIRE so the weapon-selection rules have
    #     something to keep and something to grey out.
    #     Ability: +1 to hit when stationary (roll modifier + context).
    units.append(_unit(
        ISQ, 80,
        [_model("Body C", 5, 4, 3, 2,
                [_weapon("Ranged", 2, 3, 4, -1, 1, count=5, rng=30,
                         kws=["Sustained Hits 1"]),
                 _weapon("Ranged", 3, 4, 5, -1, 1, count=1, rng=48,
                         kws=["Indirect Fire", "Blast"]),
                 _weapon("Melee", 2, 3, 4, 0, 1, count=5)],
                kws=[])],
        abilities=_abilities(1) + [
            _live("Steady Aim",
                  _effect("modifyRelative", application="hitRoll",
                          operator="add", relativeValue="1"),
                  [_attacker(), _ranged(), _cond("remainedStationary")]),
            # Gated on a leader being attached: this one belongs to the
            # LED unit, so it can only be measured once the Captain has
            # joined (the mirror of a leader_effects ability).
            _live("Squad Discipline",
                  _effect("modifyRelative", application="woundRoll",
                          operator="add", relativeValue="1"),
                  [_attacker(), _cond("leaderAttached", who="attacker")])]))

    # (4) Heavily armoured, Feel-No-Pain, multi-wound elites -- a hard
    #     target where AP, multi-damage and FNP all bite (regress
    #     defender). The model already has FNP 5+; the ability grants a
    #     BETTER one, so the no-stacking "best wins" rule is observable.
    units.append(_unit(
        "Terminator Squad", 185,
        [_model("Body D", 5, 5, 2, 3,
                [_weapon("Ranged", 2, 3, 4, -1, 2, count=5, rng=24,
                         kws=["Devastating Wounds"]),
                 _weapon("Melee", 3, 3, 8, -2, 2, count=5)],
                invuln=4, fnp=5)],
        abilities=_abilities(2) + [
            _live("Grim Resolve",
                  _effect("feelNoPain", operator="grant", value="4"),
                  [_defender()]),
            # Bonus wounds on a CRITICAL wound only: the wound-stage
            # counterpart of Sustained Hits. Attacker-side, so it leaves
            # the unit's defensive profile alone.
            _live("Storm of Fire",
                  _effect("generateExtras", option="extraWounds",
                          extrasValue="1"),
                  [_attacker(), _ranged(),
                   _cond("crit", crit="woundRoll")]),
            # A BETTER invulnerable save than the model's own 4+: the
            # "best value wins" rule of invulnSave. NOTE it carries no
            # psychicAttack condition -- invulnSave is a model-scope
            # effect while psychicAttack is a property of the attacking
            # WEAPON, so the pair could never fire (see
            # modifier_engine._c_psychic_attack).
            _live("Warded Plate", _effect("invulnSave", invulnValue="3"),
                  [_defender()])]))

    # (5) Walker with a big Lethal-Hits ranged gun and a melee fist, plus
    #     a HAZARDOUS overcharge profile (self-damage path).
    #     Abilities: damage reduction when defending (the damage chain)
    #     and a lowered critical-hit threshold when attacking.
    units.append(_unit(
        "Redemptor Dreadnought", 210,
        [_model("Redemptor Hull", 1, 9, 2, 12,
                [_weapon("Ranged", 6, 3, 8, -3, 3, count=1, rng=48,
                         kws=["Lethal Hits"]),
                 _weapon("Ranged", 3, 3, 7, -2, 2, count=1, rng=24,
                         name="Weapon 09 – standard"),
                 _weapon("Ranged", 3, 3, 9, -3, 4, count=1, rng=24,
                         kws=["Hazardous"],
                         name="Weapon 09 – supercharge"),
                 _weapon("Melee", 5, 3, 12, -2, 3, count=1)],
                invuln=5)],
        abilities=_abilities(1) + [
            _live("Duty Eternal",
                  _effect("damageReduction", operator="add", value="-1"),
                  [_defender()]),
            _live("Focused Fire",
                  _effect("criticalThreshold", application="hit",
                          value="5"),
                  [_attacker(), _ranged()]),
            _live("Warding Rune", _effect("invulnSave", invulnValue="3"),
                  [_defender(), _cond("psychicAttack")])]))

    # (6) Anti-armour walker: Melta ranged gun (bonus at half range) plus a
    #     Twin-linked backup and a melee.
    #     Abilities: ignore negative hit-roll modifiers (which is NOT the
    #     same group as the BS modifiers -- cover stays), and +1 to wound
    #     against VEHICLE only (keyword-gated condition).
    units.append(_unit(
        "Ballistus Dreadnought", 150,
        [_model("Ballistus Hull", 1, 9, 2, 10,
                [_weapon("Ranged", 3, 3, 12, -4, 6, count=1, rng=48,
                         kws=["Melta 2"]),
                 _weapon("Ranged", 6, 3, 5, -1, 1, count=1, rng=36,
                         kws=["Twin-linked"]),
                 _weapon("Melee", 3, 3, 6, -1, 2, count=1)],
                invuln=5)],
        keywords=["VEHICLE"],
        abilities=_abilities(1) + [
            _live("Target Lock", _effect("ignoreMalus", roll="Hit"),
                  [_attacker(), _ranged()]),
            _live("Armour Hunter",
                  _effect("modifyRelative", application="woundRoll",
                          operator="add", relativeValue="1"),
                  [_attacker(),
                   _cond("keywordsOnly", keywords=["VEHICLE"],
                         who="target")])]))

    # --- Leader: leads AIS, BVS and ISQ. ---
    #     'Rites of Battle' is SHARED with the unit it leads, so the
    #     leader/attachment path changes the unit's numbers; the
    #     leader_effects entry covers the separate list and the crit
    #     condition.
    units.append(_unit(
        "Captain", 80,
        [_model("Captain Model", 1, 4, 3, 5,
                [_weapon("Ranged", 4, 2, 4, -1, 1, count=1, rng=18),
                 _weapon("Ranged", 2, 2, 4, -1, 1, count=1, rng=12,
                         kws=["Pistol"]),
                 _weapon("Melee", 6, 2, 6, -2, 2, count=1,
                         kws=["Psychic"])],
                invuln=4)],
        abilities=_abilities(2) + [
            _live("Psychic Smite",
                  _effect("modifyRelative", application="woundRoll",
                          operator="add", relativeValue="1"),
                  [_attacker(), _cond("psychicAttack")]),
            _live("Rites of Battle",
                  _effect("reRoll", application="hitRoll",
                          resultToReRoll="single", valueSingle="1",
                          limit="none"),
                  [_attacker()], share=True)],
        leader_effects=[
            _live("Chapter Master's Wrath",
                  _effect("generateExtras", option="extraHits",
                          extrasValue="1"),
                  [_attacker(), _cond("crit", crit="hitRoll")])],
        leadership=[AIS, BVS, ISQ]))

    # --- Support: Bladeguard Ancient supports BVS and AIS. One model group
    #     only (test_leadercore masks the support group by its index). ---
    #     Ability: an extra Attack on its melee weapon.
    units.append(_unit(
        "Bladeguard Ancient", 65,
        [_model("Ancient Model", 1, 4, 3, 4,
                [_weapon("Melee", 4, 3, 5, -2, 2, count=1)],
                invuln=4)],
        abilities=_abilities(1) + [
            _live("Standard Bearer",
                  _effect("increaseWeaponAttacks",
                          increaseWeaponAttacksValue="1"),
                  [_attacker(), _melee()])],
        support=[BVS, AIS]))

    # --- A second support named exactly "Ancient" (test_dialog_logic looks
    #     it up by that name). Supports BVS and AIS. ---
    #     Ability: a Feel No Pain that applies to MORTAL WOUNDS only,
    #     which is the conditional (attack-scoped) branch of the effect.
    units.append(_unit(
        "Ancient", 60,
        [_model("Ancient Base", 1, 4, 3, 4,
                [_weapon("Melee", 3, 3, 4, -1, 1, count=1)])],
        abilities=_abilities(1) + [
            _live("Sacred Standard",
                  _effect("feelNoPain", operator="override", value="4"),
                  [_defender(),
                   _cond("woundType", woundType="mortalWounds")])],
        support=[BVS, AIS]))

    return {"format": "w40k-sim/6",
            "armies": [{"name": "Test Marines", "units": units}]}


def build_tau():
    units = []

    # Monster with an invuln and Blast ranged fire; melee backup.
    # Abilities: extra ATTACKS while stationary (the count branch of
    # generateExtras) and an automatic wound on every hit (overrideReqs).
    units.append(_unit(
        "Riptide Battlesuit", 180,
        [_model("Riptide Chassis", 1, 6, 2, 14,
                [_weapon("Ranged", 6, 4, 8, -2, 3, count=1, rng=36,
                         kws=["Blast"]),
                 _weapon("Melee", 3, 4, 6, -1, 2, count=1)],
                invuln=4)],
        keywords=["MONSTER"],
        abilities=_abilities(1) + [
            _live("Nova Reactor",
                  _effect("generateExtras", option="extraAttacks",
                          extrasValue="1"),
                  [_attacker(), _ranged(), _cond("remainedStationary")]),
            _live("Guided Strike",
                  _effect("overrideReqs", outcome="wound", type="always"),
                  [_attacker(), _ranged(),
                   _cond("objectiveRange", who="defender")])]))

    # Anti-armour vehicle: one big high-Damage shot + a Torrent secondary.
    # Abilities: an ABSOLUTE Damage set, and the close-quarters hit
    # penalty disabled (a VEHICLE-only mechanic).
    units.append(_unit(
        "Hammerhead Gunship", 160,
        [_model("Hammerhead Hull", 1, 9, 3, 13,
                [_weapon("Ranged", 1, 4, 10, -4, 6, count=1, rng=48),
                 _weapon("Ranged", 6, 4, 5, 0, 1, count=1, rng=18,
                         kws=["Torrent"]),
                 _weapon("Melee", 3, 4, 6, 0, 1, count=1)],
                invuln=5)],
        keywords=["VEHICLE"],
        abilities=_abilities(1) + [
            _live("Railgun Overcharge",
                  _effect("modifyAbsolute", application="damage",
                          absoluteValue="8"),
                  [_attacker(), _ranged()]),
            _live("Siege Shield",
                  _effect("disableMechanic",
                          mechanic="closeQuartersPenalty"),
                  [_attacker()])]))

    # Battlesuit: high-Strength melta-like ranged gun + melee.
    # Abilities: mortal wounds on a critical wound -- the mortal-wound
    # stream, which has its own save/FNP handling -- and Stealth, whose
    # effect type is NOT in CRITICAL_EFFECTS, so it shows up only under
    # test_regress.py --complete (which is the point of that flag).
    units.append(_unit(
        "Crisis Sunforge", 150,
        [_model("Crisis Chassis", 3, 5, 3, 5,
                [_weapon("Ranged", 2, 4, 9, -3, 2, count=3, rng=18,
                         kws=["Melta 1"]),
                 _weapon("Melee", 2, 4, 5, 0, 1, count=3)],
                invuln=4)],
        abilities=_abilities(1) + [
            _live("Fusion Overload",
                  _effect("mortalWounds", mortalWoundsValue="1"),
                  [_attacker(), _ranged(),
                   _cond("crit", crit="woundRoll")]),
            _live("Stealth",
                  _effect("special", option="benefitOfCover"),
                  [_defender()])]))

    return {"format": "w40k-sim/6",
            "armies": [{"name": "Test Tau", "units": units}]}


# --- Validation: assert the structural constraints the tests rely on -----

def validate(sm_data, tau_data):
    """Rebuild the rosters through the real engine and assert every
    relationship the data-dependent tests depend on. Raises AssertionError
    on any mismatch so a broken roster fails loudly at generation time."""
    import analyzer_core as ac
    import regress_probes as rp

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

    # regress.py pairs must resolve to >0 mean damage on at least one weapon
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

    # --- Ability coverage --------------------------------------------
    # Every delicate effect type the regression digest curates must be
    # represented by at least one ENABLED ability, otherwise the
    # synthetic digest silently stops testing the ability interpreter.
    # damageSetZero is deliberately absent: no roster uses it.
    natives = (sm_data["armies"][0]["units"] + tau_data["armies"][0]["units"])
    present = set()
    for unit in natives:
        for _lst, _idx, ab in rp.enabled_abilities(unit):
            present.add(str((ab.get("effect") or {}).get("type")))
    missing = (rp.CRITICAL_EFFECTS - present) - {"damageSetZero"}
    assert not missing, f"no enabled ability for effect types {sorted(missing)}"

    # And each of them must actually MOVE a number against the probe
    # matrix -- an ability that changes nothing tests nothing.
    # Leaders, supports and led units are resolved exactly as the digest
    # does it, so an ability that only works on a COMBINED unit
    # (leader_effects, shared, or gated on leaderAttached) is probed
    # there instead of being written off as dead.
    maps = {"join": {}, "led": {}}
    for engine_units, data in ((sm, sm_data), (tau, tau_data)):
        got = rp.attachment_targets(engine_units,
                                    data["armies"][0]["units"])
        maps["join"].update(got["join"])
        maps["led"].update(got["led"])

    inert = []
    for unit in natives:
        for _lst, idx, ab in rp.enabled_abilities(unit):
            if str((ab.get("effect") or {}).get("type")) \
                    not in rp.CRITICAL_EFFECTS:
                continue
            keep = (_lst, idx)
            role = rp.ability_role(ab)
            attach = rp.resolve_attach(unit, ab, _lst, maps)
            if _lst == "leader_effects" and attach is None:
                continue        # nothing in this roster it can join
            moved = False
            for _fname, flags in rp.FLAGSETS:
                if attach is not None:
                    off = rp.combined_unit(unit, None, attach[1], attach[0])
                    on = rp.combined_unit(unit, keep, attach[1], attach[0])
                else:
                    off = rp.as_unit(rp.variant(unit, None))
                    on = rp.as_unit(rp.variant(unit, keep))
                probes = (rp.PROBE_DEFENDERS if role != "defender"
                          else rp.PROBE_ATTACKERS)
                for probe in probes:
                    other = rp.as_unit(probe)
                    for mode in rp.PROBE_MODES:
                        if role == "defender":
                            a, b = (rp.total_damage(other, off, flags, mode),
                                    rp.total_damage(other, on, flags, mode))
                        else:
                            a, b = (rp.total_damage(off, other, flags, mode),
                                    rp.total_damage(on, other, flags, mode))
                        if a is not None and b is not None \
                                and abs(a - b) > 1e-9:
                            moved = True
                            break
                    if moved:
                        break
                if moved:
                    break
            if not moved:
                inert.append(f"{unit['name']}/{ab.get('name')}")
    assert not inert, f"enabled abilities with no observable effect: {inert}"

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
