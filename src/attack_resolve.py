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


def _roll_damage(rng, d_char, mech, half: bool, budget=None) -> int:
    """Damage roll: per-die re-roll range, flat bonus, MELTA, then the
    defender's Damage modifiers (set / multiply / add / floor, in that
    fixed order - see attack_math.apply_damage_modifiers), keeping this
    dice resolver in step with the exact maths.

    'budget' is the ONE Damage re-roll some abilities grant for the
    whole activation (Aquilon Optics): a one-element list holding the
    range still to be spent, emptied by the first die it is spent on.
    The player re-rolls the first die worth re-rolling, which is the
    policy the exact chain resolves - see _damage_single_total."""
    total = max(d_char.flat, 0)
    lo, hi = (mech.dmg_reroll
              or (mech.dmg_reroll_any
                  and am.damage_reroll_range(d_char))
              or (0, -1))
    for _ in range(d_char.count):
        v = _d6(rng) if d_char.sides == 6 else rng.randint(1, d_char.sides)
        again = lo <= v <= hi
        if not again and budget and budget[0] and budget[0][0] <= v \
                <= budget[0][1]:
            # A die may be re-rolled once, so the once-per-activation
            # re-roll is only ever spent on a die the weapon's own
            # re-roll did not already take.
            again = True
            budget[0] = None
        if again and rules_config.CAP_REROLLS > 0:
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
                   haz_damage: int = 1, defer_save: bool = False) -> dict:
    """Resolve every attack of one weapon (all its copies). Returns
    {'attacks': n, 'events': [{'kind': 'damage'|'mortal',
    'amount': k}, ...], 'pending': [...], 'self_damage': int,
    'warnings': [...]}. Events with amount 0 after FNP are dropped.

    A HAZARDOUS weapon is resolved exactly as the roster lists it and
    rolls one Hazardous test per copy (11th ed.: a 1-2 deals haz_damage
    self-damage). It does NOT get a boosted profile: datasheets list the
    supercharged version as its own weapon, and that is the one carrying
    the keyword.

    DEFER_SAVE splits the sequence in two. The save, the damage roll and
    Feel No Pain are the only steps that depend on WHICH model the
    attack was allocated to, and 11th ed. settles that between the wound
    roll and the save (Core Rules 05.03: create the allocation groups,
    declare their order, then make one save roll per wounding attack).
    With defer_save the resolver therefore stops at the scored wound and
    reports what is still owed in 'pending'; 'events' comes back empty
    and :func:`resolve_saves` finishes the job against an
    :class:`alloc_groups.Allocation`. Everything up to that point - the
    number of attacks, the hit stage, the wound stage - is a property of
    the target UNIT and is unaffected.

    Without defer_save (the default) nothing changes: the whole sequence
    is resolved against 'defender_ref' as before, and 'pending' is
    empty. That is the path the exact-vs-dice parity sweep drives, so it
    must stay identical roll for roll.
    """
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
    # DEVASTATING WOUNDS inflicts MORTAL WOUNDS: every ability keyed on
    # mortal wounds triggers on them too (an invulnerable save or a Feel
    # No Pain "against mortal wounds"), so they are thinned like any
    # other mortal wound. What sets them apart is only how they are
    # ALLOCATED - they do not spill from a destroyed model to the next -
    # which changes no damage total and is recorded on the event for the
    # kill chain to read.
    crit_mw = mech.crit_mw
    mw_spills = crit_mw is not None and crit_mw.get("spill", True)
    if mech.devastating and crit_mw is None:
        crit_mw = {"value": None, "match": True, "end": True}
    ap = am._effective_ap(weapon.AP.value() or 0, mech)
    fnp = defender_ref.get("fnp")

    events = []
    # What the sequence still owes when the saves are deferred, in ROLL
    # order: resolve_saves walks it in the same order, so the damage
    # rolls - and the one re-roll some abilities grant for the whole
    # activation - are spent on exactly the dice they would have been.
    pending = []

    def pend_mortal(spec, spills):
        pending.append({"kind": "mortal", "value": spec.get("value"),
                        "match": bool(spec.get("match")),
                        "spills": bool(spills)})

    fails = {"hit": False, "wound": False}
    # ONE Damage re-roll for the whole activation, if an ability grants
    # one and there is a Damage ROLL for it to work on.
    dmg_budget = [am.damage_reroll_range(weapon.D)
                  if mech.single_reroll == "damage" else None]

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
            if defer_save:
                pend_mortal(crit_mw, mw_spills)
            else:
                raw = (_roll_damage(rng, weapon.D, mech, half, dmg_budget)
                       if crit_mw["match"] else (crit_mw["value"] or 1))
                kept = _fnp_keep(rng, _mw_save_keep(rng, raw, mech), fnp,
                                 mech, mw=True)
                if kept > 0:
                    events.append({"kind": "mortal", "amount": kept,
                                   "spills": mw_spills})
            go_on = not crit_mw["end"]
        if wound_crit and (mech.crit_ap_delta or mech.crit_ap_set is not None):
            ap_eff = am._crit_ap(weapon.AP.value() or 0, mech)
        if not go_on:
            return
        if defer_save:
            # The AP is settled here (the critical branch may have
            # sharpened it) but the Sv it is compared against is not
            # known until the allocation order has been declared.
            pending.append({"kind": "wound", "ap": ap_eff})
            return
        if _save_made(rng, defender_ref, ap_eff, mech):
            return
        raw = _roll_damage(rng, weapon.D, mech, half, dmg_budget)
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
                if defer_save:
                    # A hit-roll mortal wound is a plain mortal wound:
                    # it spills unless the ability says otherwise.
                    pend_mortal(mech.hitroll_mw,
                                mech.hitroll_mw.get("spill", True))
                    return
                raw = (_roll_damage(rng, weapon.D, mech, half,
                                    dmg_budget)
                       if mech.hitroll_mw["match"]
                       else (mech.hitroll_mw["value"] or 1))
                kept = _fnp_keep(rng, _mw_save_keep(rng, raw, mech), fnp,
                                 mech, mw=True)
                if kept > 0:
                    # A hit-roll mortal wound is a plain mortal wound:
                    # it spills unless the ability says otherwise.
                    events.append(
                        {"kind": "mortal", "amount": kept,
                         "spills": mech.hitroll_mw.get("spill", True)})
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
    return {"attacks": n_att, "events": events, "pending": pending,
            "self_damage": self_damage, "warnings": list(mech.warnings)}


# ---------------- deferred save stage ----------------


def resolve_saves(pending, weapon, mech, rng: random.Random, alloc,
                  ctx: dict = None) -> dict:
    """Second half of a deferred sequence: allocate every wound that was
    scored, roll the save of the MODEL it lands on, roll the damage and
    take it off.

    'pending' comes from resolve_weapon(..., defer_save=True) and is
    walked in roll order. 'alloc' is an alloc_groups.Allocation whose
    order has already been declared - the rules settle it before any
    save is rolled, and a save made against a 3+ cannot be moved onto a
    2+ model afterwards.

    Three things follow the model rather than the unit, and this is the
    whole reason the split exists: the Save (and the invulnerable it is
    weighed against), Feel No Pain, and the wounds the damage is capped
    by. The rest - Toughness, the target's keywords, how many models it
    has - belongs to the unit and was settled in the first half.

    Order of resolution, as 06.02 and [DEVASTATING WOUNDS] require:
    normal damage and the mortal wounds that do NOT spill land in roll
    order, one model at a time; the spilling ones are pooled and applied
    LAST, one point at a time, each point picking its own model - and so
    each shrugged with THAT model's Feel No Pain.

    Returns {'events', 'saves_made', 'shrugged', 'no_target'}, where an
    event carries the amount that got through and the (model key,
    wounds removed) pairs it came off.
    """
    half = bool((ctx or {}).get("half_range"))
    # ONE Damage re-roll for the whole activation (Aquilon Optics): the
    # first half rolled no damage at all, so the budget starts here and
    # is spent in the same order it would have been.
    budget = [am.damage_reroll_range(weapon.D)
              if mech.single_reroll == "damage" else None]
    events, spill_pool = [], 0
    saves_made = shrugged = no_target = 0

    def record(kind, amount, spills, hits):
        events.append({"kind": kind, "amount": amount, "spills": spills,
                       "hits": [(alloc.models[i].get("key"), n)
                                for i, n in hits]})

    for item in pending:
        if item["kind"] == "mortal":
            raw = (_roll_damage(rng, weapon.D, mech, half, budget)
                   if item["match"] else (item["value"] or 1))
            # The invulnerable that applies to mortal wounds is a
            # property of the ATTACK's target unit, not of the model,
            # so it is rolled here either way.
            kept = _mw_save_keep(rng, raw, mech)
            if item["spills"]:
                spill_pool += kept
                continue
            # DEVASTATING WOUNDS: a mortal wound for every rule that
            # keys on it, but allocated like ordinary damage - one
            # model, no spill, the excess wasted.
            i = alloc.current_model()
            if i is None:
                no_target += 1
                continue
            got = _fnp_keep(rng, kept, alloc.ref_of(i).get("fnp"), mech,
                            mw=True)
            shrugged += kept - got
            if got > 0:
                record("mortal", got, False,
                       alloc.allocate(got, target=i))
            continue
        i = alloc.current_model()
        if i is None:
            # The unit is gone: the attacks still owed have nowhere to
            # be allocated and are simply lost.
            no_target += 1
            continue
        ref = alloc.ref_of(i)
        if _save_made(rng, ref, item["ap"], mech):
            saves_made += 1
            continue
        raw = _roll_damage(rng, weapon.D, mech, half, budget)
        kept = _fnp_keep(rng, raw, ref.get("fnp"), mech, mw=False)
        shrugged += raw - kept
        if kept > 0:
            # 'i' was picked BEFORE the save was rolled, which is the
            # order the rules prescribe; the damage has to land on that
            # same model and not be looked up a second time.
            record("damage", kept, False, alloc.allocate(kept, target=i))
    # The spilling mortal wounds, last and one point at a time (06.02).
    # The model is named once and passed on, so the Feel No Pain rolled
    # for the point and the model that loses it cannot be two different
    # models.
    for _ in range(spill_pool):
        i = alloc.mortal_model()
        if i is None:
            no_target += 1
            continue
        if _fnp_keep(rng, 1, alloc.ref_of(i).get("fnp"), mech,
                     mw=True) <= 0:
            shrugged += 1
            continue
        record("mortal", 1, True,
               alloc.allocate(1, spill=True, target=i))
    return {"events": events, "saves_made": saves_made,
            "shrugged": shrugged, "no_target": no_target}
