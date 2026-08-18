"""Dice-based attack resolution (program 1).

Resolves one attack sequence with REAL dice rolls, using the same
WeaponMechanics extracted by attack_math, so the two programs cannot
diverge on rules interpretation: the test suite checks that the mean
outcome of many resolutions converges to the exact analytic value.

Output is a per-weapon list of damage events ('damage' = unsaved wound,
'mortal' = mortal wounds), each already reduced by Feel No Pain, so the
player allocates wounds to models manually. Masked models/weapons are
filtered out before the views are built (see filter_native_unit)."""

import copy
import random

import rules_config
import attack_math as am


def filter_native_unit(unit_dict: dict, masked_copies: dict = None,
                       masked_weapons=(), weapon_counts: dict = None) \
        -> dict:
    """Copy of a native unit dict adjusted for the table state:
    masked_copies = {model_index: n} reduces each model_count by n
    (the model entry is dropped when nothing is left); masked_weapons
    is a set of (model_index, weapon_index) removed entirely;
    weapon_counts = {(model_index, weapon_index): n} overrides a weapon
    count (e.g. ONE SHOT copies already fired), dropping it at <= 0.

    Weapon counts are stored per UNIT, so when copies are masked the
    counts of the entry's weapons are scaled proportionally to the
    effective model count (exactly when divisible, rounded otherwise),
    UNLESS an explicit weapon_counts override is present - a manual
    edit always wins."""
    masked_copies = masked_copies or {}
    weapon_counts = weapon_counts or {}
    out = copy.deepcopy(unit_dict)
    models = []
    for mi, m in enumerate(out.get("models", [])):
        orig = m.get("model_count") or 1
        eff = orig - masked_copies.get(mi, 0)
        if eff <= 0:
            continue
        m["model_count"] = eff
        weapons = []
        for wi, w in enumerate(m.get("weapons", [])):
            if (mi, wi) in masked_weapons:
                continue
            if (mi, wi) in weapon_counts:
                w["count"] = weapon_counts[(mi, wi)]
            elif eff != orig:
                c = w.get("count", 1)
                w["count"] = (c // orig) * eff if c % orig == 0 \
                    else round(c * eff / orig)
            if w.get("count", 1) > 0:
                weapons.append(w)
        m["weapons"] = weapons
        models.append(m)
    out["models"] = models
    return out


# ---------------- dice helpers ----------------


def _d6(rng):
    return rng.randint(1, 6)


def _roll_success(rng, success_fn, reroll):
    """Roll a d6; re-roll failures up to CAP_REROLLS times when allowed
    ('fails' re-rolls any failure, '1' only a natural 1). Returns the
    final die value."""
    r = _d6(rng)
    t = rules_config.CAP_REROLLS
    while (t > 0 and not success_fn(r)
           and (reroll == "fails" or (reroll == "1" and r == 1))):
        r = _d6(rng)
        t -= 1
    return r


def _roll_damage(rng, d_char, mech, half: bool) -> int:
    """Damage roll: per-die re-roll range, flat bonus, MELTA, then the
    defender's Damage modifiers (set / multiply / add / floor, in that
    fixed order - see attack_math.apply_damage_modifiers), keeping this
    dice resolver in step with the exact maths."""
    total = max(d_char.flat, 0)
    lo, hi = (mech.dmg_reroll
              or (mech.dmg_reroll_any
                  and am.damage_reroll_range(d_char))
              or (0, -1))
    for _ in range(d_char.count):
        v = _d6(rng) if d_char.sides == 6 else rng.randint(1, d_char.sides)
        if lo <= v <= hi and rules_config.CAP_REROLLS > 0:
            v = (_d6(rng) if d_char.sides == 6
                 else rng.randint(1, d_char.sides))
        total += v
    if half and am.x_active(mech.melta):
        total += am.x_value(mech.melta, rng)
    if am.has_damage_modifiers(mech):
        total = am.apply_damage_modifiers(total, mech)
    return total


def _mw_save_keep(rng, dmg: int, mech) -> int:
    """Mortal wounds surviving an invulnerable save that applies to them
    (11th ed.: mortal wounds ignore armour, so only such an ability - or
    Feel No Pain - can stop them). Rolled per mortal wound, the way they
    are allocated; the invulnerable modifiers and re-rolls apply."""
    if mech.invuln_mw is None or dmg <= 0:
        return dmg
    target = rules_config.clamp_characteristic("invuln", mech.invuln_mw)
    mod = (max(0, mech.invuln_mod) if "invuln" in mech.ignore_malus
           else mech.invuln_mod)
    kept = 0
    for _ in range(dmg):
        r = _roll_success(rng, lambda x: x > 1 and x + mod >= target,
                          mech.reroll_invuln)
        if not (r > 1 and r + mod >= target):
            kept += 1
    return kept


def _fnp_keep(rng, dmg: int, fnp, mech, mw: bool) -> int:
    """Points kept after Feel No Pain (with modifier and re-roll)."""
    fnp, fnp_mod = am.effective_fnp({"fnp": fnp}, mech, mw)
    if not fnp:
        return dmg
    eff = fnp - fnp_mod                   # FNP: no cap (like saves, 11th)
    kept = 0
    for _ in range(dmg):
        r = _roll_success(rng, lambda x: x >= eff, mech.reroll_fnp)
        if r < eff:
            kept += 1
    return kept


def _save_made(rng, ref, ap_eff, mech) -> bool:
    """Defender rolls the better save (armour vs invuln), each with its
    own modifiers and re-rolls; unmodified 1 always fails. Mirrors
    attack_math.save_fail_prob, limits included: the Sv and invulnerable
    characteristics are clamped at 2+ BEFORE AP applies, and save-roll
    modifiers are NOT capped (only hit and wound are). Cover no longer
    affects the save in 11th ed. - it is a -1 BS penalty at the hit
    stage."""
    sv = ref.get("Sv")
    arm_t = None
    if sv is not None:
        arm_t = rules_config.clamp_characteristic("Sv", sv) + abs(ap_eff)
    inv_t = am.effective_invuln(ref, mech)
    if inv_t is not None:
        inv_t = rules_config.clamp_characteristic("invuln", inv_t)
    smod, imod = mech.save_mod, mech.invuln_mod
    if "save" in mech.ignore_malus:
        smod = max(0, smod)
    if "invuln" in mech.ignore_malus:
        imod = max(0, imod)
    times = rules_config.CAP_REROLLS
    p_arm = am._p_save_roll(arm_t, smod, mech.reroll_save, times)
    p_inv = am._p_save_roll(inv_t, imod, mech.reroll_invuln, times)
    if max(p_arm, p_inv) == 0.0:
        return False
    if p_arm >= p_inv:
        target, mod, rr = arm_t, smod, mech.reroll_save
    else:
        target, mod, rr = inv_t, imod, mech.reroll_invuln
    r = _roll_success(rng, lambda x: x > 1 and x + mod >= target, rr)
    return r > 1 and r + mod >= target


# ---------------- single-weapon resolution ----------------


def resolve_weapon(weapon, defender_ref: dict, ctx: dict,
                   mech: am.WeaponMechanics, rng: random.Random,
                   haz_damage: int = 1) -> dict:
    """Resolve every attack of one weapon (all its copies). Returns
    {'attacks': n, 'events': [{'kind': 'damage'|'mortal',
    'amount': k}, ...], 'self_damage': int, 'warnings': [...]}.
    Events with amount 0 after FNP are dropped.

    A HAZARDOUS weapon is resolved exactly as the roster lists it and
    rolls one Hazardous test per copy (11th ed.: a 1-2 deals haz_damage
    self-damage). It does NOT get a boosted profile: datasheets list the
    supercharged version as its own weapon, and that is the one carrying
    the keyword."""
    half = bool(ctx.get("half_range"))

    # number of attacks. X may be a dice expression (11th ed.), so every
    # extra is rolled; BLAST/CLEAVE roll once per group of five models,
    # mirroring analyze_weapon.
    groups = max(0, defender_ref.get("models", 1) // 5)
    n_att = 0
    for _ in range(max(1, weapon.count)):
        extra_a = (am.x_value(mech.rapid_fire, rng)
                   if half and am.x_active(mech.rapid_fire) else 0)
        # BLAST (ranged) and CLEAVE (melee): +X attacks per 5 target models.
        for src in (mech.blast, mech.cleave):
            if groups and am.x_active(src):
                extra_a += sum(am.x_value(src, rng) for _ in range(groups))
        # generateExtras "extra attacks": X further attacks per copy.
        if am.x_active(mech.extra_attacks):
            extra_a += am.x_value(mech.extra_attacks, rng)
        a_char = rules_config.clamp_characteristic(
            "A", (weapon.A.value(rng) or 0) + mech.attacks_mod)
        n_att += a_char + extra_a

    # static roll parameters (mirror analyze_weapon)
    # 11th ed.: BS/WS CHARACTERISTIC modifiers (cover, plunging fire) and
    # HIT ROLL modifiers (Heavy, damaged bracket, abilities) are capped
    # separately - see analyze_weapon, which this mirrors.
    hit_mod = mech.hit_mod + (1 if (mech.heavy and ctx.get("stationary"))
                              else 0)
    if ctx.get("damaged"):
        hit_mod -= 1
    # Close-quarters shooting: -1 to hit for a MONSTER/VEHICLE attacker
    # with everything except its CLOSE-QUARTERS weapons (see
    # analyze_weapon).
    if ctx.get("close_quarters_penalty") and not mech.close_quarters \
            and not mech.ignore_cq_penalty:
        hit_mod -= 1
    # INDIRECT FIRE, mirroring analyze_weapon: target always in Cover,
    # no hit re-rolls, and an unmodified die below unmod_min always
    # fails (6, or 4 with a spotter while stationary).
    indirect = bool(ctx.get("indirect")) and mech.indirect
    unmod_min = 1
    reroll_hit = mech.reroll_hit
    if indirect:
        unmod_min = 4 if ctx.get("spotter") else 6
        reroll_hit = None
    skill_mod = 0
    if weapon.type == "Ranged":
        if (ctx.get("cover") or mech.cover or indirect) \
                and not mech.ignores_cover:
            skill_mod -= 1
        if ctx.get("plunging"):
            skill_mod += 1
    # Defender ability on the attack's BS/WS: characteristic convention
    # (+1 = worse), so it enters with the opposite sign (see
    # analyze_weapon).
    skill_mod -= mech.skill_mod
    # The hit ROLL and the BS/WS CHARACTERISTIC are two separate groups
    # in 11th ed. and are ignored separately (see analyze_weapon).
    if "hit" in mech.ignore_malus:
        hit_mod = max(0, hit_mod)
    if "skill" in mech.ignore_malus:
        skill_mod = max(0, skill_mod)
    hit_mod = am._cap(hit_mod)          # the ROLL modifier is capped,
    skill = weapon.WS if weapon.type == "Melee" else weapon.BS
    # the CHARACTERISTIC modifier is not: uncapped, only bounded by its
    # absolute limits (BS/WS between 2+ and 6+), clamped before hit_mod.
    skill_target = rules_config.clamp_characteristic(
        "BS", (skill.value() or 0) - skill_mod)
    # CONVERSION, mirroring analyze_weapon: beyond half range the
    # critical-hit threshold drops to 4+.
    crit_hit_on = mech.crit_hit_on
    if mech.conversion and not ctx.get("half_range"):
        crit_hit_on = min(crit_hit_on, am.CONVERSION_CRIT_HIT)
    # OVERWATCH, mirroring analyze_weapon: hits only on an unmodified N+,
    # no hit modifiers and no re-rolls; the wound roll is normal.
    ow = am.overwatch_target(ctx)
    if ow is not None:
        hit_mod, skill_target, reroll_hit = 0, ow, None
        unmod_min = max(unmod_min, ow)
    auto = mech.torrent or mech.auto_hit or skill.is_none()
    s_val = rules_config.clamp_characteristic(
        "S", (weapon.S.value() or 0) + mech.str_mod)
    wt = am.wound_target(s_val, defender_ref["T"])
    wound_mod = mech.wound_mod + (1 if (mech.lance and ctx.get("charged"))
                                  else 0)
    if "wound" in mech.ignore_malus:
        wound_mod = max(0, wound_mod)
    wound_mod = am._cap(wound_mod)
    crit_on = mech.crit_wound_on
    dkw = {str(k).strip().upper()
           for k in (defender_ref.get("keywords") or ())}
    for kw, x in mech.anti:                # case-insensitive, as the maths
        if str(kw).strip().upper() in dkw:
            crit_on = min(crit_on, x)
    reroll_wound = am.combine_reroll("fails" if mech.twin_linked else None,
                                     mech.reroll_wound)
    crit_mw = mech.crit_mw
    if mech.devastating and crit_mw is None:
        crit_mw = {"value": None, "match": True, "end": True}
    ap = am._effective_ap(weapon.AP.value() or 0, mech)
    fnp = defender_ref.get("fnp")

    events = []

    fails = {"hit": False, "wound": False}

    def resolve_hit_chain(hit_is_crit: bool):
        # wound stage
        if hit_is_crit and mech.lethal_crit:
            wounded, wound_crit = True, True
        elif hit_is_crit and mech.lethal:
            wounded, wound_crit = True, False
        elif mech.auto_wound:
            wounded, wound_crit = True, False    # OVERRIDE WOUND ALWAYS
        else:
            ok = lambda r: (r >= crit_on or r == 6
                            or (r > 1 and r + wound_mod >= wt))
            r = _roll_success(rng, ok, reroll_wound)
            wounded, wound_crit = ok(r), r >= crit_on
        if not wounded:
            fails["wound"] = True
            return
        resolve_wound(wound_crit)
        # EXTRA WOUNDS: a scored wound yields X more - extra_wounds on
        # any wound, extra_wounds_crit on a critical one, and a critical
        # wound collects both. They are not rolled, so they are always
        # NORMAL wounds; mirrors nw_branch / cw_branch of analyze_weapon.
        extras = 0
        if am.x_active(mech.extra_wounds):
            extras += am.x_value(mech.extra_wounds, rng)
        if wound_crit and am.x_active(mech.extra_wounds_crit):
            extras += am.x_value(mech.extra_wounds_crit, rng)
        for _ in range(extras):
            resolve_wound(False)

    def resolve_wound(wound_crit: bool):
        """Everything after a wound has been scored: the critical
        mortal-wound branch, the save, the damage."""
        ap_eff, go_on = ap, True
        if wound_crit and crit_mw:
            raw = (_roll_damage(rng, weapon.D, mech, half)
                   if crit_mw["match"] else (crit_mw["value"] or 1))
            kept = _fnp_keep(rng, _mw_save_keep(rng, raw, mech), fnp,
                             mech, mw=True)
            if kept > 0:
                events.append({"kind": "mortal", "amount": kept})
            go_on = not crit_mw["end"]
        if wound_crit and (mech.crit_ap_delta or mech.crit_ap_set is not None):
            ap_eff = am._crit_ap(weapon.AP.value() or 0, mech)
        if not go_on:
            return
        if _save_made(rng, defender_ref, ap_eff, mech):
            return
        raw = _roll_damage(rng, weapon.D, mech, half)
        kept = _fnp_keep(rng, raw, fnp, mech, mw=False)
        if kept > 0:
            events.append({"kind": "damage", "amount": kept})

    # Did any hit / wound roll fail? A "one re-roll per activation"
    # ability (mech.single_reroll) spends its re-roll on one of them.
    def resolve_hit(hit_is_crit: bool):
        """One scored hit and the bonus hits it generates. SUSTAINED HITS
        fire on a CRITICAL hit, EXTRA HITS on ANY hit. Bonus hits are
        hits, not hit rolls: never critical, and they generate no extras
        of their own - mirrors the crit_branch / norm_branch split of
        analyze_weapon."""
        resolve_hit_chain(hit_is_crit)
        if hit_is_crit:
            for _ in range(am.x_value(mech.sustained, rng)):
                resolve_hit_chain(False)
        if am.x_active(mech.extra_hits):
            for _ in range(am.x_value(mech.extra_hits, rng)):
                resolve_hit_chain(False)

    def one_attack():
        if auto:
            resolve_hit(False)
            return
        # +1 BS makes the target easier; a characteristic never beats 1+.
        tgt = skill_target
        if mech.hitroll_mw:
            thr = mech.hitroll_mw["thr"]
            ok = lambda r: (r >= thr
                            or (r > 1 and r < thr and r + hit_mod >= tgt))
            r = _roll_success(rng, ok, reroll_hit)
            if r >= thr:
                raw = (_roll_damage(rng, weapon.D, mech, half)
                       if mech.hitroll_mw["match"]
                       else (mech.hitroll_mw["value"] or 1))
                kept = _fnp_keep(rng, _mw_save_keep(rng, raw, mech), fnp,
                                 mech, mw=True)
                if kept > 0:
                    events.append({"kind": "mortal", "amount": kept})
                return
            if not ok(r):
                fails["hit"] = True
                return
            resolve_hit(False)
            return
        if mech.hit_unmod_only:
            x = max(mech.hit_unmod_only, unmod_min)
            ok = lambda r: r >= x and (r == 6 or r >= crit_hit_on
                                       or r >= x)
        else:
            ok = lambda r: (r >= unmod_min
                            and (r == 6 or r >= crit_hit_on
                                 or (r > 1 and r + hit_mod >= tgt)))
        r = _roll_success(rng, ok, reroll_hit)
        if not ok(r):
            fails["hit"] = True
            return
        crit = (r >= crit_hit_on and r >= unmod_min)
        resolve_hit(crit)

    for _ in range(n_att):
        one_attack()
    # The single re-roll: one failed die of the chosen kind is re-rolled,
    # which is one fresh attack (hit) or one fresh wound roll onwards
    # (wound). Mirrors the q_n term of analyze_weapon.
    if mech.single_reroll == "hit" and fails["hit"]:
        one_attack()
    elif mech.single_reroll == "wound" and fails["wound"]:
        resolve_hit_chain(False)

    self_damage = 0
    if mech.hazardous:
        for _ in range(max(1, weapon.count)):
            if _d6(rng) <= 2:
                self_damage += haz_damage
    return {"attacks": n_att, "events": events,
            "self_damage": self_damage, "warnings": list(mech.warnings)}
